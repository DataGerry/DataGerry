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
Unit tests for cmdb.database.updater.versions.updater_20261112

The migration raises every multi-data section's row-id counter to its largest row id and logs the breaks it does not
repair. Its run against a real database is its own integration test; this module owns the frozen literals, the row id
rule, the repair rule, the reported breaks, the one bulk write, the version bump and the failure tail
"""
import logging
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.database.updater.versions import updater_20261112 as module
from cmdb.database.updater.versions.updater_20261112 import (
    Update20261112,
    is_row_id,
    object_changes,
    repaired_highest_id,
    section_breaks,
    section_row_ids,
)
from cmdb.models.object_model import CmdbObject, CmdbObjectKey, CmdbObjectMdsKey, CmdbObjectMdsRowKey
from cmdb.framework.object_section_structure_constants import MIN_ROW_ID
from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

CREATION_DATE: int = 20261112
DATABASE_NAME: str = 'cmdb-unit'
DB_FAILURE: str = 'objects gone'
NICS: str = 'nics'


def _rows(*row_ids: Any) -> list[dict[str, Any]]:
    """Rows holding the given ids"""
    return [{'multi_data_id': row_id, 'data': []} for row_id in row_ids]


def test_the_frozen_literals_match_the_code() -> None:
    """The collection and keys still mean what the code means today"""
    assert (module.OBJECTS_COLLECTION, module.SECTIONS_FIELD, module.SECTION_ID_FIELD, module.HIGHEST_ID_FIELD,
            module.VALUES_FIELD, module.ROW_ID_FIELD, module.MIN_ROW_ID) == (
        CmdbObject.COLLECTION, CmdbObjectKey.MULTI_DATA_SECTIONS.value, CmdbObjectMdsKey.SECTION_ID.value,
        CmdbObjectMdsKey.HIGHEST_ID.value, CmdbObjectMdsKey.VALUES.value, CmdbObjectMdsRowKey.MULTI_DATA_ID.value,
        MIN_ROW_ID,
    )


@pytest.mark.parametrize('value, expected', [(0, True), (3, True), (-1, False), (True, False), ('1', False)])
def test_the_row_id_rule(value: Any, expected: bool) -> None:
    """An int from 0; a bool is none"""
    assert is_row_id(value) is expected


def test_the_row_ids_of_a_section() -> None:
    """A row without one counts for nothing; values that are no list hold none"""
    assert section_row_ids({'values': [*_rows(2, None, 0), 'x']}) == [2, 0]
    assert not section_row_ids({'values': 'x'})


@pytest.mark.parametrize('section, expected', [
    ({'highest_id': 0, 'values': _rows(0, 1)}, 1),
    ({'values': _rows(3)}, 3),
    ({'highest_id': True, 'values': _rows(2)}, 2),
    ({'highest_id': 5, 'values': _rows(1, 2)}, None),
    ({'highest_id': 2, 'values': _rows(2)}, None),
    ({'highest_id': 1, 'values': []}, None),
], ids=['below', 'absent', 'bool', 'above', 'equal', 'no-rows'])
def test_the_repair_rule(section: dict[str, Any], expected: int | None) -> None:
    """Raised to the largest row id; a counter at or above it, or a section without ids, is left"""
    assert repaired_highest_id(section) == expected


@pytest.mark.parametrize('section, seen, expected', [
    ('x', set(), ["section 1 is not an object"]),
    ({'values': []}, set(), ["section 1 has no section_id"]),
    ({'section_id': NICS, 'values': []}, {NICS}, ["section 'nics' is stored more than once"]),
    ({'section_id': NICS, 'values': _rows(1, None)}, set(), ["section 'nics': a row has no row id"]),
    ({'section_id': NICS, 'values': _rows(2, 1, 2, 1)}, set(), ["section 'nics': row id(s) [1, 2] held by more than "
                                                                 "one row"]),
    ({'section_id': NICS, 'values': _rows(0, 1)}, set(), []),
], ids=['no-object', 'no-id', 'repeated', 'row-without-id', 'repeated-row-ids', 'in-line'])
def test_the_reported_breaks(section: Any, seen: set[str], expected: list[str]) -> None:
    """Named, never repaired"""
    assert section_breaks(1, section, seen) == expected


def test_the_changes_of_one_object() -> None:
    """A $set per stale counter, by position; the breaks beside them"""
    sections: list[Any] = [
        {'section_id': NICS, 'highest_id': 0, 'values': _rows(0, 1)},
        'x',
        {'section_id': 'disks', 'highest_id': 9, 'values': _rows(1)},
    ]

    assert object_changes(sections) == ({'multi_data_sections.0.highest_id': 1}, ["section 1 is not an object"])
    assert object_changes('x') == ({}, ["multi_data_sections is not a list"])


def _updater(documents: list[dict[str, Any]]) -> tuple[Update20261112, MagicMock]:
    """The migration over a mocked database manager answering the given objects"""
    dbm = MagicMock()
    dbm.find.return_value = iter(documents)
    updater = Update20261112(dbm, DATABASE_NAME)
    updater.increase_updater_version = MagicMock()

    return updater, dbm


def test_the_version_and_description() -> None:
    """The date it is registered under"""
    updater, _dbm = _updater([])

    assert updater.creation_date() == CREATION_DATE
    assert updater.description()


def test_stale_counters_are_raised_in_one_write_and_breaks_logged(caplog: pytest.LogCaptureFixture) -> None:
    """Only the objects holding sections are read, projected"""
    updater, dbm = _updater([
        {'_id': 'a', 'public_id': 1, 'multi_data_sections': [{'section_id': NICS, 'highest_id': 0,
                                                              'values': _rows(0, 1)}]},
        {'_id': 'b', 'public_id': 2, 'multi_data_sections': [{'section_id': NICS, 'highest_id': 1,
                                                              'values': _rows(1, 1)}]},
        {'_id': 'c', 'public_id': 3, 'multi_data_sections': [{'section_id': NICS, 'highest_id': 4,
                                                              'values': _rows(4)}]},
    ])

    with caplog.at_level(logging.WARNING, logger=module.__name__):
        updater.start_update()

    assert dbm.find.call_args.kwargs == {
        'collection': CmdbObject.COLLECTION, 'db_name': DATABASE_NAME, 'filter': module.OBJECTS_WITH_SECTIONS,
        'projection': module.OBJECT_PROJECTION,
    }
    (collection, db_name, operations), _kwargs = dbm.bulk_write.call_args
    # pylint: disable-next=protected-access
    assert (collection, db_name, [(op._filter, op._doc) for op in operations]) == (
        CmdbObject.COLLECTION, DATABASE_NAME, [({'_id': 'a'}, {'$set': {'multi_data_sections.0.highest_id': 1}})],
    )
    assert [record.getMessage() for record in caplog.records if record.levelno == logging.WARNING] == [
        "[updater_20261112] Object ID:2 breaks the structure rule (left as is): section 'nics': row id(s) [1] held by "
        "more than one row",
    ]
    updater.increase_updater_version.assert_called_once_with(CREATION_DATE)


def test_a_clean_database_writes_nothing_and_still_bumps() -> None:
    """The second run"""
    updater, dbm = _updater([{'_id': 'a', 'multi_data_sections': [{'section_id': NICS, 'highest_id': 1,
                                                                   'values': _rows(0, 1)}]}])

    updater.start_update()

    dbm.bulk_write.assert_not_called()
    updater.increase_updater_version.assert_called_once_with(CREATION_DATE)


def test_a_failing_write_is_the_updater_exception_carrying_the_error() -> None:
    """The exception itself, not its text; the version is not bumped"""
    updater, dbm = _updater([{'_id': 'a', 'multi_data_sections': [{'section_id': NICS, 'values': _rows(1)}]}])
    failure = RuntimeError(DB_FAILURE)
    dbm.bulk_write.side_effect = failure

    with pytest.raises(UpdaterException) as raised:
        updater.start_update()

    assert raised.value.args[0] is failure
    updater.increase_updater_version.assert_not_called()
