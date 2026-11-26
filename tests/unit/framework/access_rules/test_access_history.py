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
Unit tests for the pure half of the access change history

Pinned: the keys a change touches; an entry's shape (states without their database id, groups once each, ascending,
an empty comment as none); the groups an assignment, and a field's protection change, concern; the export's CSV; the
kinds the history records - a new kind of access document is a deliberate decision (a secret-bearing one must not slip
in)
"""
import csv
import io
from datetime import datetime, timezone
from typing import Any

from cmdb.framework.access_engine import build_grants
from cmdb.framework.access_rules.access_history import (
    EXPORT_COLUMNS,
    HistoryChange,
    assignment_groups,
    changed_keys,
    csv_lines,
    groups_writing_field,
    history_entry,
)
from cmdb.models.access_model import AccessHistoryKey, HistoryKind
# -------------------------------------------------------------------------------------------------------------------- #

NOW: datetime = datetime(2026, 11, 26, tzinfo=timezone.utc)
SERVER, OPEN = 11, 12
WRITERS, READERS, OTHERS = 21, 22, 23


def test_changed_keys() -> None:
    """Differing values, keys only on one side; a create or delete every key; never the database id"""
    assert changed_keys({'a': 1, 'b': 2, '_id': 'x'}, {'a': 1, 'b': 3, 'c': 4, '_id': 'y'}) == ['b', 'c']
    assert changed_keys(None, {'a': 1}) == ['a']
    assert changed_keys({'a': 1}, None) == ['a']
    assert changed_keys({'a': 1}, {'a': 1}) == []


def test_an_entry() -> None:
    """The change, who, when"""
    change = HistoryChange('update', 'scope_role', 4, {'_id': 'x', 'types': [1]}, {'types': [2]}, [3, 1, 3],
                           'route', '')
    entry: dict[str, Any] = history_entry(change, NOW, 1, 'admin')

    assert entry == {'time': NOW, 'user_id': 1, 'user_name': 'admin', 'action': 'update', 'kind': 'scope_role',
                     'document_id': 4, 'before': {'types': [1]}, 'after': {'types': [2]}, 'changed': ['types'],
                     'comment': None, 'group_ids': [1, 3], 'source': 'route'}
    assert set(entry) | {AccessHistoryKey.PUBLIC_ID.value} == set(EXPORT_COLUMNS)


def test_assignment_groups() -> None:
    """Before and after; none skipped"""
    assert assignment_groups([{'group_id': 2}, None, {'group_id': 5}, {'group_id': 'x'}]) == {2, 5}


def test_the_groups_writing_a_field() -> None:
    """On a restricted Type by a role writing the class; on an open Type every group"""
    def grants(group_id: int, classes: list[str]) -> Any:
        return build_grants([{'public_id': group_id, 'group_id': group_id, 'role_id': 31, 'scope': '*'}],
                            [{'public_id': 31, 'types': [SERVER], 'operations': ['view', 'edit'],
                              'write_regular_fields': False, 'field_classes': classes}], [group_id])

    by_group = {WRITERS: grants(WRITERS, ['compliance']), READERS: grants(READERS, [])}

    assert groups_writing_field(by_group, 'iso', ['compliance'], [SERVER]) == {WRITERS}
    assert groups_writing_field(by_group, 'iso', [None, 'compliance'], [SERVER]) == {WRITERS}
    assert groups_writing_field(by_group, 'iso', ['compliance'], [OPEN]) == {WRITERS, READERS}


def test_the_csv() -> None:
    """A header, a row per entry; lists and states as JSON, the time as ISO"""
    entry: dict[str, Any] = {**history_entry(HistoryChange('create', 'field_class', 3, None, {'name': 'x'}, [2],
                                                           'route'), NOW, 1, 'admin'), 'public_id': 9}
    rows = list(csv.DictReader(io.StringIO(''.join(csv_lines([entry])))))

    assert len(rows) == 1
    assert (rows[0]['public_id'], rows[0]['time'], rows[0]['after'], rows[0]['group_ids']) == (
        '9', NOW.isoformat(), '{"name": "x"}', '[2]')


def test_the_kinds_recorded() -> None:
    """Exactly the access documents and the history's own setting"""
    assert {kind.value for kind in HistoryKind} == {'field_class', 'scope_role', 'assignment', 'field_rule',
                                                    'field_protection', 'history_settings'}
