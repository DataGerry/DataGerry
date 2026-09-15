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
Integration tests for the MDS propagation path of TypesManager against a real MongoDB

What only a real database can show: that the narrowing and the projection actually work as queries.
`get_objects_for_type(section_ids=...)` reads only the objects carrying an affected
multi_data_section (an object with none of them can not change), the propagation reads only the keys
it touches - a type's `fields` list never enters it - and it yields the changed objects batch by
batch, so neither the documents in memory nor the caller's bulk write is sized by the whole type.

Since 2026-09-09 it also pins the section-removal rule: a section the edit no longer declares is
removed from the objects, where it used to be skipped and left every object carrying rows of a
section its type did not have.
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


def _type_doc(section_fields: list[str] | None, field_types: dict[str, str] | None = None) -> dict[str, Any]:
    """
    A CmdbType document declaring one MDS section named SECTION_A

    `section_fields=None` describes a type that no longer declares the section at all.
    """
    types: dict[str, str] = field_types or {}
    sections: list[dict[str, Any]] = [] if section_fields is None else [{
        'type': 'multi-data-section', 'name': SECTION_A, 'label': 'A',
        'fields': section_fields,
    }]

    return {
        'public_id': TYPE_ID,
        'name': 'mds-type',
        'label': 'MDS Type',
        'author_id': 1,
        'active': True,
        'fields': [
            {'type': types.get(name, 'text'), 'name': name, 'label': name.upper()}
            for name in (section_fields or [])
        ],
        'render_meta': {'icon': '', 'sections': sections, 'summary': {'fields': []}},
        'version': '1.0.0',
    }


def _old_type(section_fields: list[str]) -> CmdbType:
    """The stored CmdbType the propagation compares against."""
    return CmdbType.from_data(_type_doc(section_fields))


@pytest.fixture(name='types_manager')
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

    def test_narrows_to_single_section(self, types_manager: TypesManager) -> None:
        """Only the object carrying sec-a is returned when narrowing to [sec-a]."""
        result = types_manager.get_objects_for_type(TYPE_ID, section_ids=[SECTION_A])

        assert {obj.public_id for obj in result} == {OBJECT_WITH_A}

    def test_narrows_to_multiple_sections(self, types_manager: TypesManager) -> None:
        """Objects carrying either sec-a or sec-b are returned; the MDS-less object is excluded."""
        result = types_manager.get_objects_for_type(TYPE_ID, section_ids=[SECTION_A, SECTION_B])

        assert {obj.public_id for obj in result} == {OBJECT_WITH_A, OBJECT_WITH_B}

    def test_without_section_ids_returns_all(self, types_manager: TypesManager) -> None:
        """With no narrowing every object of the type (including the MDS-less one) is loaded."""
        result = types_manager.get_objects_for_type(TYPE_ID)

        assert set(ALL_OBJECT_IDS).issubset({obj.public_id for obj in result})


class TestThePropagationAgainstARealDatabase:
    """The narrowing, the projection, the batching and the two kinds of change."""

    @staticmethod
    def _propagate(
            types_manager: TypesManager,
            old_fields: list[str],
            updated_fields: list[str] | None,
            field_types: dict[str, str] | None = None,
    ) -> list[CmdbObject]:
        """Runs the propagation and flattens its batches."""
        batches = types_manager.handle_multi_data_sections(
            _old_type(old_fields), _type_doc(updated_fields, field_types),
        )

        return [cmdb_object for batch in batches for cmdb_object in batch]

    def test_adds_a_field_only_to_the_affected_object(self, types_manager: TypesManager) -> None:
        """Adding 'b' to sec-a touches only OBJECT_WITH_A; the others are neither read nor changed."""
        changed = self._propagate(types_manager, ['a'], ['a', 'b'])

        assert [obj.public_id for obj in changed] == [OBJECT_WITH_A]
        row_data = changed[0].multi_data_sections[0]['values'][0]['data']
        assert {entry['name'] for entry in row_data} == {'a', 'b'}

    def test_a_new_field_carries_its_declared_type(self, types_manager: TypesManager) -> None:
        """
        The type comes from the UPDATED type

        Reading it from the stored type - which cannot contain a field the edit just added - wrote
        every new MDS field as 'text', whatever it was declared as.
        """
        changed = self._propagate(types_manager, ['a'], ['a', 'b'], {'b': 'date'})

        row_data = changed[0].multi_data_sections[0]['values'][0]['data']
        new_entry = next(entry for entry in row_data if entry['name'] == 'b')
        assert new_entry['type'] == 'date'

    def test_removes_a_field_from_the_affected_object(self, types_manager: TypesManager) -> None:
        """The destructive half, which no test reached before: the entry goes from every row."""
        changed = self._propagate(types_manager, ['a', 'b'], ['b'])

        row_data = changed[0].multi_data_sections[0]['values'][0]['data']
        assert [entry['name'] for entry in row_data] == []

    def test_removes_a_section_the_type_no_longer_declares(self, types_manager: TypesManager) -> None:
        """The 2026-09-09 rule: the object stops carrying rows of a section its type does not have."""
        changed = self._propagate(types_manager, ['a'], None)

        assert [obj.public_id for obj in changed] == [OBJECT_WITH_A]
        assert changed[0].multi_data_sections == []

    def test_an_unchanged_section_changes_nothing(self, types_manager: TypesManager) -> None:
        """A pure metadata edit reads no object at all"""
        assert self._propagate(types_manager, ['a'], ['a']) == []

    def test_the_propagation_reads_only_the_projected_keys(self, types_manager: TypesManager) -> None:
        """
        A type's `fields` list - usually the bulk of an object document - never enters the read

        The projection is a real query here, so this is the tier that can prove it.
        """
        changed = self._propagate(types_manager, ['a'], ['a', 'b'])

        assert changed[0].fields == []
        assert changed[0].public_id == OBJECT_WITH_A

    def test_the_batches_cover_every_affected_object(
            self, types_manager: TypesManager, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """With a batch size of one, each affected object arrives in its own batch"""
        monkeypatch.setattr('cmdb.manager.types_manager.MDS_PROPAGATION_BATCH_SIZE', 1)

        batches = list(types_manager.handle_multi_data_sections(
            _old_type(['a']), _type_doc(None),
        ))

        assert [[obj.public_id for obj in batch] for batch in batches] == [[OBJECT_WITH_A]]


class TestGetObjectIdsForType:
    """The id read the batching is built on."""

    def test_reports_the_ids_of_the_affected_objects(self, types_manager: TypesManager) -> None:
        """Narrowed by section, so an object carrying none of them is not even counted"""
        assert types_manager.get_object_ids_for_type(TYPE_ID, section_ids=[SECTION_A]) == [OBJECT_WITH_A]

    def test_reports_every_object_without_narrowing(self, types_manager: TypesManager) -> None:
        """The unnarrowed read still answers with the whole type"""
        assert set(types_manager.get_object_ids_for_type(TYPE_ID)) == set(ALL_OBJECT_IDS)
