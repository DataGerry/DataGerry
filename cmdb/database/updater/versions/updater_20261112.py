# DATAGERRY - OpenSource Enterprise CMDB
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
Database update 20261112: every multi-data section's row-id counter is at least its largest row id

A PATCH creating a row now takes the id above the section's ``highest_id`` and above every row id present, and the
full writes align the counter - but a section stored before could hold a ``highest_id`` below one of its row ids (or
none, or one that is no whole number), and the PATCH of that time handed the next row an id a row already held. This
update raises every such counter to the largest row id. It changes no row and nothing a reader shows: the counter is
not data, only the source of the next row id.

The other breaks of the object structure rule are not repaired here - a section sent twice, a section without a
``section_id``, a row without a row id, a row id two rows share: which copy or which row is the right one is no
updater's decision. Each object holding one is logged (a warning naming the object and the breaks), and its next edit
is refused with the 400 naming them.

Re-run safe: a second run finds every counter at or above its largest row id and writes nothing
"""
from logging import Logger, getLogger
from typing import Any

from pymongo import UpdateOne

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The literals of this migration are frozen: it must keep meaning what it meant when it shipped
OBJECTS_COLLECTION: str = 'framework.objects'
MONGO_ID_FIELD: str = '_id'
PUBLIC_ID_FIELD: str = 'public_id'
SECTIONS_FIELD: str = 'multi_data_sections'
SECTION_ID_FIELD: str = 'section_id'
HIGHEST_ID_FIELD: str = 'highest_id'
VALUES_FIELD: str = 'values'
ROW_ID_FIELD: str = 'multi_data_id'
MIN_ROW_ID: int = 0
OBJECT_PROJECTION: dict[str, int] = {MONGO_ID_FIELD: 1, PUBLIC_ID_FIELD: 1, SECTIONS_FIELD: 1}
OBJECTS_WITH_SECTIONS: dict[str, Any] = {SECTIONS_FIELD: {'$type': 'array', '$ne': []}}

SECTIONS_NOT_A_LIST: str = "multi_data_sections is not a list"
SECTION_NOT_AN_OBJECT: str = "section {position} is not an object"
SECTION_WITHOUT_ID: str = "section {position} has no section_id"
SECTION_REPEATED: str = "section '{section_id}' is stored more than once"
ROW_WITHOUT_ID: str = "section '{section_id}': a row has no row id"
ROW_IDS_REPEATED: str = "section '{section_id}': row id(s) {row_ids} held by more than one row"

# -------------------------------------------------------------------------------------------------------------------- #

def is_row_id(value: Any) -> bool:
    """
    Whether a stored value is a row id: an int from MIN_ROW_ID; a bool is none

    Args:
        value (Any): The stored value

    Returns:
        bool: True for a row id
    """
    return isinstance(value, int) and not isinstance(value, bool) and value >= MIN_ROW_ID


def section_row_ids(section: dict[str, Any]) -> list[int]:
    """
    The row ids a stored section's rows hold, in row order; a row without one counts for nothing

    Args:
        section (dict[str, Any]): The stored section

    Returns:
        list[int]: The row ids
    """
    rows: Any = section.get(VALUES_FIELD)

    return [row[ROW_ID_FIELD] for row in rows if isinstance(row, dict) and is_row_id(row.get(ROW_ID_FIELD))] \
        if isinstance(rows, list) else []


def repaired_highest_id(section: dict[str, Any]) -> int | None:
    """
    The counter a stored section needs, when its own is below its largest row id (or is none)

    Args:
        section (dict[str, Any]): The stored section

    Returns:
        int | None: The largest row id; None when the counter is in line or the section holds no row id
    """
    row_ids: list[int] = section_row_ids(section)

    if not row_ids:
        return None

    highest: Any = section.get(HIGHEST_ID_FIELD)

    if is_row_id(highest) and highest >= max(row_ids):
        return None

    return max(row_ids)


def section_breaks(position: int, section: Any, seen: set[str]) -> list[str]:
    """
    What a stored section breaks of the rule this update does not repair

    Args:
        position (int): The section's position
        section (Any): The stored section
        seen (set[str]): The section_ids before it - this one's is added

    Returns:
        list[str]: The breaks, empty for a section in line
    """
    if not isinstance(section, dict):
        return [SECTION_NOT_AN_OBJECT.format(position=position)]

    section_id: Any = section.get(SECTION_ID_FIELD)

    if not isinstance(section_id, str) or not section_id:
        return [SECTION_WITHOUT_ID.format(position=position)]

    breaks: list[str] = [SECTION_REPEATED.format(section_id=section_id)] if section_id in seen else []
    seen.add(section_id)

    rows: Any = section.get(VALUES_FIELD)
    rows = rows if isinstance(rows, list) else []
    row_ids: list[int] = section_row_ids(section)

    if len(row_ids) < len(rows):
        breaks.append(ROW_WITHOUT_ID.format(section_id=section_id))

    if repeated := sorted({row_id for row_id in row_ids if row_ids.count(row_id) > 1}):
        breaks.append(ROW_IDS_REPEATED.format(section_id=section_id, row_ids=repeated))

    return breaks


def object_changes(sections: Any) -> tuple[dict[str, int], list[str]]:
    """
    The counters to set on one stored object, and what it breaks beyond them

    Args:
        sections (Any): The object's stored ``multi_data_sections``

    Returns:
        tuple[dict[str, int], list[str]]: The ``$set`` document (``multi_data_sections.<position>.highest_id``) and
            the breaks to report
    """
    if not isinstance(sections, list):
        return {}, [SECTIONS_NOT_A_LIST]

    changes: dict[str, int] = {}
    breaks: list[str] = []
    seen: set[str] = set()

    for position, section in enumerate(sections):
        breaks.extend(section_breaks(position, section, seen))

        if isinstance(section, dict) and (repaired := repaired_highest_id(section)) is not None:
            changes[f'{SECTIONS_FIELD}.{position}.{HIGHEST_ID_FIELD}'] = repaired

    return changes, breaks

# ---------------------------------------------- Update20261112 - CLASS ---------------------------------------------- #

class Update20261112(BaseDatabaseUpdate):
    """
    Raises every multi-data section's row-id counter to its largest row id; logs the breaks it does not repair

    Extends: BaseDatabaseUpdate
    """
    def creation_date(self) -> int:
        return 20261112


    def description(self) -> str:
        return "Raises multi-data section row-id counters to the largest row id"


    def start_update(self) -> None:
        """
        Reads every object holding sections, writes the raised counters in one bulk write, then bumps the version

        Raises:
            UpdaterException: If a read or a write fails
        """
        try:
            operations: list[UpdateOne] = []

            for document in self.dbm.find(collection=OBJECTS_COLLECTION, db_name=self.db_name,
                                          filter=OBJECTS_WITH_SECTIONS, projection=OBJECT_PROJECTION):
                changes, breaks = object_changes(document.get(SECTIONS_FIELD))

                if changes:
                    operations.append(UpdateOne({MONGO_ID_FIELD: document[MONGO_ID_FIELD]}, {'$set': changes}))

                if breaks:
                    LOGGER.warning("[updater_20261112] Object ID:%s breaks the structure rule (left as is): %s",
                                   document.get(PUBLIC_ID_FIELD), '; '.join(breaks))

            if operations:
                self.dbm.bulk_write(OBJECTS_COLLECTION, self.db_name, operations)

            LOGGER.info("[updater_20261112] Raised the row-id counters of %s object(s)", len(operations))

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(err) from err
