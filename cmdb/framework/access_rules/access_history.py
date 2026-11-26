# DataGerry - OpenSource Enterprise CMDB
# Copyright (C) 2026 becon GmbH
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""
The access change history - pure: one entry per changed access document, which keys changed, which user groups the
change concerns, and the export's rows

What concerns a group is fixed when the entry is written: an assignment its group (before and after), a scope role the
groups holding an assignment of it, a field class the groups whose roles grant it, a Field Rule the groups that can
trigger it, a field's protection the groups writing the field - each before or after the change
"""
import csv
import io
import json
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from cmdb.models.access_model import AccessAssignmentKey, AccessHistoryKey, ScopeOperation
from cmdb.framework.access_engine.access_decision import refused_fields
from cmdb.framework.access_engine.access_grants import AccessGrants
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'EXPORT_COLUMNS',
    'HistoryChange',
    'changed_keys',
    'history_entry',
    'assignment_groups',
    'groups_writing_field',
    'csv_lines',
]

# The keys an export's CSV carries, in order - before and after as JSON text
EXPORT_COLUMNS: tuple[str, ...] = tuple(key.value for key in AccessHistoryKey)
# The stored key of a document's database id - never part of the history
_MONGO_ID: str = '_id'


def changed_keys(before: Mapping[str, Any] | None, after: Mapping[str, Any] | None) -> list[str]:
    """
    The top-level keys whose value differs between two states of a document

    Args:
        before (Mapping[str, Any] | None): The document before; None for a create
        after (Mapping[str, Any] | None): The document after; None for a delete

    Returns:
        list[str]: The keys, ascending - every key of the one state there is for a create or a delete
    """
    old: Mapping[str, Any] = before or {}
    new: Mapping[str, Any] = after or {}

    return sorted(key for key in set(old) | set(new) if key != _MONGO_ID and old.get(key) != new.get(key))


@dataclass(frozen=True)
class HistoryChange:
    """
    One changed access document, as the history records it

    Attributes:
        action (str): ``HistoryAction`` value
        kind (str): ``HistoryKind`` value
        document_id (Any): The changed document's id
        before (Mapping[str, Any] | None): The document before; None for a create
        after (Mapping[str, Any] | None): The document after; None for a delete
        group_ids (Iterable[int]): The user groups the change concerns
        source (str): ``HistorySource`` value
        comment (str | None): The writer's comment
    """
    action: str
    kind: str
    document_id: Any
    before: Mapping[str, Any] | None
    after: Mapping[str, Any] | None
    group_ids: Iterable[int]
    source: str
    comment: str | None = None


def history_entry(change: HistoryChange, time: datetime, user_id: int | None, user_name: str | None) -> dict[str, Any]:
    """
    One entry of the history, without its public_id

    Args:
        change (HistoryChange): The change
        time (datetime): When it was written (UTC)
        user_id (int | None): Who made it
        user_name (str | None): Their name now

    Returns:
        dict[str, Any]: The entry - the states without their database id, the groups once each, ascending
    """
    def clean(state: Mapping[str, Any] | None) -> dict[str, Any] | None:
        return None if state is None else {key: value for key, value in state.items() if key != _MONGO_ID}

    return {AccessHistoryKey.TIME.value: time, AccessHistoryKey.USER_ID.value: user_id,
            AccessHistoryKey.USER_NAME.value: user_name, AccessHistoryKey.ACTION.value: change.action,
            AccessHistoryKey.KIND.value: change.kind, AccessHistoryKey.DOCUMENT_ID.value: change.document_id,
            AccessHistoryKey.BEFORE.value: clean(change.before), AccessHistoryKey.AFTER.value: clean(change.after),
            AccessHistoryKey.CHANGED.value: changed_keys(change.before, change.after),
            AccessHistoryKey.COMMENT.value: change.comment or None,
            AccessHistoryKey.GROUP_IDS.value: sorted(set(change.group_ids)),
            AccessHistoryKey.SOURCE.value: change.source}


def assignment_groups(assignments: Iterable[Mapping[str, Any] | None]) -> set[int]:
    """
    The user groups of assignments - an assignment's own change concerns its group, before and after

    Args:
        assignments (Iterable[Mapping[str, Any] | None]): Assignments (None skipped)

    Returns:
        set[int]: Their group ids
    """
    return {assignment[AccessAssignmentKey.GROUP_ID.value] for assignment in assignments
            if assignment and isinstance(assignment.get(AccessAssignmentKey.GROUP_ID.value), int)}


def groups_writing_field(grants_by_group: Mapping[int, AccessGrants], name: str, field_classes: Iterable[str | None],
                         type_ids: Iterable[Any]) -> set[int]:
    """
    The user groups that write a field - under any of its classes (before or after a change) - on one of its Types

    Args:
        grants_by_group (Mapping[int, AccessGrants]): Each group's own grants
        name (str): The field's name
        field_classes (Iterable[str | None]): Its classes to judge (None for no class)
        type_ids (Iterable[Any]): The Types carrying it

    Returns:
        set[int]: The groups
    """
    classes: list[str | None] = list(field_classes)
    types: list[Any] = list(type_ids)

    return {group_id for group_id, grants in grants_by_group.items()
            if any(not refused_fields(grants, ScopeOperation.EDIT, type_id, [name],
                                      field_classes={name: field_class} if field_class else None)
                   for type_id in types for field_class in classes)}


def csv_lines(entries: Iterable[Mapping[str, Any]]) -> Iterator[str]:
    """
    The export's CSV, line by line - a header, then one row per entry; lists and states as JSON text

    Args:
        entries (Iterable[Mapping[str, Any]]): Stored entries

    Yields:
        str: One CSV line each
    """
    def line(values: list[Any]) -> str:
        buffer: io.StringIO = io.StringIO()
        csv.writer(buffer).writerow(values)

        return buffer.getvalue()

    yield line(list(EXPORT_COLUMNS))

    for entry in entries:
        yield line([_cell(entry.get(column)) for column in EXPORT_COLUMNS])


def _cell(value: Any) -> Any:
    """
    One CSV cell

    Args:
        value (Any): The stored value

    Returns:
        Any: A time as ISO text, a list or a state as JSON text, anything else as it is
    """
    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, (list, dict)):
        return json.dumps(value, default=str, sort_keys=True)

    return value
