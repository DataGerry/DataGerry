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
Integration tests for the server-side MDS field propagation in SectionTemplatesManager

Real-MongoDB exercise of ``_add_mds_fields_to_objects`` and ``cleanup_mds_fields``, which mutate
``multi_data_sections[].values[].data[]`` via ``update_many_raw`` with nested positional array
filters (a MongoDB 3.6 feature) instead of loading objects into the app. Asserts that an added
field reaches every row of the matching section without duplicating where present, that removal
strips the named field from every row, and that other sections / other types are left untouched
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.section_templates_manager import SectionTemplatesManager
from cmdb.models.object_model import CmdbObject, CmdbObjectFieldKey, CmdbObjectMdsKey, CmdbObjectMdsRowKey
# -------------------------------------------------------------------------------------------------------------------- #

TARGET_TYPE_ID: int = 9501
OTHER_TYPE_ID: int = 9502

SECTION: str = 'dg-ipam-interface'
OTHER_SECTION: str = 'dg-other-section'

ADD_OBJ_MULTI_ROW: int = 9511
ADD_OBJ_HAS_FIELD: int = 9512
ADD_OBJ_OTHER_SECTION: int = 9513
ADD_OBJ_OTHER_TYPE: int = 9514
CLEANUP_OBJ: int = 9515

ALL_IDS: list[int] = [ADD_OBJ_MULTI_ROW, ADD_OBJ_HAS_FIELD, ADD_OBJ_OTHER_SECTION, ADD_OBJ_OTHER_TYPE, CLEANUP_OBJ]


def _entry(name: str, value: Any) -> dict[str, Any]:
    """Builds one stored MDS field entry as the frontend persists it (name + value)."""
    return {CmdbObjectFieldKey.NAME.value: name, CmdbObjectFieldKey.VALUE.value: value}


def _mds_section(section_id: str, rows: list[list[dict[str, Any]]]) -> dict[str, Any]:
    """Builds one MDS section dict with rows nested under values[].data."""
    return {
        CmdbObjectMdsKey.SECTION_ID.value: section_id,
        CmdbObjectMdsKey.VALUES.value: [
            {'multi_data_id': index, CmdbObjectMdsRowKey.DATA.value: row} for index, row in enumerate(rows)
        ],
    }


def _object_doc(public_id: int, type_id: int, mds_sections: list[dict[str, Any]]) -> dict[str, Any]:
    """Builds a minimal CmdbObject doc carrying the given multi_data_sections."""
    return {
        'public_id': public_id,
        'type_id': type_id,
        'active': True,
        'author_id': 1,
        'creation_time': datetime.now(timezone.utc),
        'version': '1.0.0',
        'fields': [],
        'multi_data_sections': mds_sections,
    }


def _row_names(section: dict[str, Any], row_index: int) -> list[str]:
    """Returns the field names of a given row of an MDS section."""
    row = section[CmdbObjectMdsKey.VALUES.value][row_index][CmdbObjectMdsRowKey.DATA.value]
    return [entry[CmdbObjectFieldKey.NAME.value] for entry in row]


@pytest.fixture(scope='function', autouse=True)
def _seed_objects_and_cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the object fixtures fresh per test and removes them afterwards."""
    collection = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    collection.delete_many({'public_id': {'$in': ALL_IDS}})
    collection.insert_many([
        _object_doc(ADD_OBJ_MULTI_ROW, TARGET_TYPE_ID, [_mds_section(SECTION, [[_entry('a', 1)], [_entry('a', 2)]])]),
        _object_doc(ADD_OBJ_HAS_FIELD, TARGET_TYPE_ID, [_mds_section(SECTION, [[_entry('a', 9), _entry('b', 'x')]])]),
        _object_doc(ADD_OBJ_OTHER_SECTION, TARGET_TYPE_ID, [_mds_section(OTHER_SECTION, [[_entry('a', 1)]])]),
        _object_doc(ADD_OBJ_OTHER_TYPE, OTHER_TYPE_ID, [_mds_section(SECTION, [[_entry('a', 1)]])]),
        _object_doc(CLEANUP_OBJ, TARGET_TYPE_ID, [_mds_section(SECTION, [[_entry('a', 1), _entry('b', 2)], [_entry('a', 3)]])]),
    ])
    yield
    collection.delete_many({'public_id': {'$in': ALL_IDS}})


@pytest.fixture(name='manager')
def fixture_manager(database_manager: MongoDatabaseManager) -> SectionTemplatesManager:
    """Provides a SectionTemplatesManager wired to the test database."""
    return SectionTemplatesManager(database_manager)


def _find(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> dict[str, Any]:
    """Reads back a seeded object document by public_id."""
    return database_manager.get_collection(CmdbObject.COLLECTION, database_name).find_one({'public_id': public_id})


def test_add_seeds_missing_field_into_every_row(
    manager: SectionTemplatesManager, database_manager: MongoDatabaseManager, database_name: str,
) -> None:
    """Every row of the matching section gains the new field (value None, mapped type)."""
    manager._add_mds_fields_to_objects(  # pylint: disable=protected-access
        TARGET_TYPE_ID, [{'name': 'b', 'type': 'text'}], SECTION,
    )

    section = _find(database_manager, database_name, ADD_OBJ_MULTI_ROW)['multi_data_sections'][0]
    assert _row_names(section, 0) == ['a', 'b']
    assert _row_names(section, 1) == ['a', 'b']

    added = section[CmdbObjectMdsKey.VALUES.value][0][CmdbObjectMdsRowKey.DATA.value][-1]
    assert added[CmdbObjectFieldKey.VALUE.value] is None
    assert added[CmdbObjectFieldKey.TYPE.value] == 'text'


def test_add_does_not_duplicate_existing_field(
    manager: SectionTemplatesManager, database_manager: MongoDatabaseManager, database_name: str,
) -> None:
    """A row already carrying the field is left with a single copy of it."""
    manager._add_mds_fields_to_objects(  # pylint: disable=protected-access
        TARGET_TYPE_ID, [{'name': 'b', 'type': 'text'}], SECTION,
    )

    section = _find(database_manager, database_name, ADD_OBJ_HAS_FIELD)['multi_data_sections'][0]
    assert _row_names(section, 0).count('b') == 1


def test_add_leaves_other_section_and_other_type_untouched(
    manager: SectionTemplatesManager, database_manager: MongoDatabaseManager, database_name: str,
) -> None:
    """Objects of another section or another type are not modified."""
    manager._add_mds_fields_to_objects(  # pylint: disable=protected-access
        TARGET_TYPE_ID, [{'name': 'b', 'type': 'text'}], SECTION,
    )

    other_section = _find(database_manager, database_name, ADD_OBJ_OTHER_SECTION)['multi_data_sections'][0]
    other_type = _find(database_manager, database_name, ADD_OBJ_OTHER_TYPE)['multi_data_sections'][0]
    assert _row_names(other_section, 0) == ['a']
    assert _row_names(other_type, 0) == ['a']


def test_cleanup_removes_named_field_from_every_row(
    manager: SectionTemplatesManager, database_manager: MongoDatabaseManager, database_name: str,
) -> None:
    """The named field is pulled from every row of the matching section, leaving the rest."""
    manager.cleanup_mds_fields(TARGET_TYPE_ID, ['b'], SECTION)

    section = _find(database_manager, database_name, CLEANUP_OBJ)['multi_data_sections'][0]
    assert _row_names(section, 0) == ['a']
    assert _row_names(section, 1) == ['a']
