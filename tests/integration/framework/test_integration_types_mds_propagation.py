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
Integration tests for the MDS-field propagation path of TypesManager against a real MongoDB

Pins the P1 optimisation: get_objects_for_type(section_ids=...) narrows the object fetch to the
objects that actually carry an affected multi_data_section, and update_multi_data_fields returns
exactly the objects it changed (objects lacking the affected section are neither loaded nor
returned - behaviour identical to loading every object of the type)
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.types_manager import TypesManager
from cmdb.models.type_model import CmdbType
from cmdb.models.object_model import CmdbObject
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID: int = 9601
SECTION_A: str = 'sec-a'
SECTION_B: str = 'sec-b'

OBJECT_WITH_A: int = 9611     # carries MDS section sec-a
OBJECT_WITH_B: int = 9612     # carries MDS section sec-b
OBJECT_WITHOUT_MDS: int = 9613  # no multi_data_sections at all
ALL_OBJECT_IDS: list[int] = [OBJECT_WITH_A, OBJECT_WITH_B, OBJECT_WITHOUT_MDS]


def _mds_section(section_id: str) -> dict[str, Any]:
    """Builds one MDS section carrying a single row with field 'a'."""
    return {
        'section_id': section_id,
        'highest_id': 1,
        'values': [{'multi_data_id': 1, 'data': [{'name': 'a', 'value': 'x', 'type': 'text'}]}],
    }


def _object_doc(public_id: int, mds: list[dict[str, Any]]) -> dict[str, Any]:
    """Builds a complete CmdbObject doc of TYPE_ID with the given multi_data_sections."""
    return {
        'public_id': public_id,
        'type_id': TYPE_ID,
        'active': True,
        'author_id': 1,
        'creation_time': datetime.now(timezone.utc),
        'version': '1.0.0',
        'fields': [{'type': 'text', 'name': 'a', 'value': 'x'}],
        'multi_data_sections': mds,
    }


def _type_with_fields() -> CmdbType:
    """A CmdbType whose fields declare 'a' and 'b' (b is the field being propagated into MDS rows)."""
    return CmdbType.from_data({
        'public_id': TYPE_ID,
        'name': 'mds-type',
        'label': 'MDS Type',
        'author_id': 1,
        'active': True,
        'fields': [
            {'type': 'text', 'name': 'a', 'label': 'A'},
            {'type': 'text', 'name': 'b', 'label': 'B'},
        ],
        'render_meta': {'icon': '', 'sections': [], 'summary': {'fields': []}},
        'version': '1.0.0',
    })


@pytest.fixture(name='objects_manager')
def fixture_types_manager(database_manager: MongoDatabaseManager) -> TypesManager:
    """Provides a TypesManager wired to the test database."""
    return TypesManager(database_manager)


@pytest.fixture(autouse=True)
def _seed(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds three objects of TYPE_ID (sec-a / sec-b / no MDS), removed after the test."""
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    objects.insert_many([
        _object_doc(OBJECT_WITH_A, [_mds_section(SECTION_A)]),
        _object_doc(OBJECT_WITH_B, [_mds_section(SECTION_B)]),
        _object_doc(OBJECT_WITHOUT_MDS, []),
    ])
    yield
    objects.delete_many({'public_id': {'$in': ALL_OBJECT_IDS}})


class TestGetObjectsForTypeSectionNarrowing:
    """get_objects_for_type(section_ids=...) loads only objects carrying an affected MDS section."""

    def test_narrows_to_single_section(self, objects_manager: TypesManager) -> None:
        """Only the object carrying sec-a is returned when narrowing to [sec-a]."""
        result = objects_manager.get_objects_for_type(TYPE_ID, section_ids=[SECTION_A])

        assert {obj.public_id for obj in result} == {OBJECT_WITH_A}

    def test_narrows_to_multiple_sections(self, objects_manager: TypesManager) -> None:
        """Objects carrying either sec-a or sec-b are returned; the MDS-less object is excluded."""
        result = objects_manager.get_objects_for_type(TYPE_ID, section_ids=[SECTION_A, SECTION_B])

        assert {obj.public_id for obj in result} == {OBJECT_WITH_A, OBJECT_WITH_B}

    def test_without_section_ids_returns_all(self, objects_manager: TypesManager) -> None:
        """With no narrowing every object of the type (including the MDS-less one) is loaded."""
        result = objects_manager.get_objects_for_type(TYPE_ID)

        assert set(ALL_OBJECT_IDS).issubset({obj.public_id for obj in result})


class TestUpdateMultiDataFieldsNarrowedBehaviour:
    """update_multi_data_fields changes (and returns) only the objects with the affected section."""

    def test_adds_field_only_to_affected_object(self, objects_manager: TypesManager) -> None:
        """Adding 'b' to sec-a touches only OBJECT_WITH_A; the others are neither changed nor returned."""
        changed = objects_manager.update_multi_data_fields(_type_with_fields(), {SECTION_A: ['b']}, {})

        assert [obj.public_id for obj in changed] == [OBJECT_WITH_A]
        row_data = changed[0].multi_data_sections[0]['values'][0]['data']
        assert {entry['name'] for entry in row_data} == {'a', 'b'}
