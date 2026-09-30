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
Integration tests for the MDS propagation of a CmdbType edit against a real MongoDB

What only a real database can show: that the server-side statements `build_mds_updates` produces do
what the plan says. A field added to an MDS section lands in every row of that section that lacks it -
with the type and the default value the updated type declares - a dropped field leaves every row, and
a section the type no longer declares leaves the objects. Objects without the section, other sections
and the flat `fields` list are not touched, and no object is read to do it.

Two properties follow from the statements being server-side and are pinned here because they are the
reason the propagation is built this way: a second run modifies nothing, and an edit saved to an
object between the type edit and the propagation survives it.
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.objects_manager import ObjectsManager
from cmdb.manager.types_mds_helper import build_mds_updates, plan_mds_changes
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


def _type_doc(
        section_fields: list[str] | None,
        field_types: dict[str, str] | None = None,
        field_defaults: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
    """
    A CmdbType document declaring one MDS section named SECTION_A

    `section_fields=None` describes a type that no longer declares the section at all.
    `field_defaults` gives a field a declared default ``value``.
    """
    types: dict[str, str] = field_types or {}
    defaults: dict[str, Any] = field_defaults or {}
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
            {'type': types.get(name, 'text'), 'name': name, 'label': name.upper(),
             **({'value': defaults[name]} if name in defaults else {})}
            for name in (section_fields or [])
        ],
        'render_meta': {'icon': '', 'sections': sections, 'summary': {'fields': []}},
        'version': '1.0.0',
    }


def _old_type(section_fields: list[str]) -> CmdbType:
    """The stored CmdbType the propagation compares against."""
    return CmdbType.from_data(_type_doc(section_fields))


@pytest.fixture(name='objects_manager')
def fixture_objects_manager(database_manager: MongoDatabaseManager) -> ObjectsManager:
    """Provides an ObjectsManager wired to the test database."""
    return ObjectsManager(database_manager)


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


def _stored(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> dict[str, Any]:
    """Reads one seeded object back as stored."""
    return database_manager.get_collection(CmdbObject.COLLECTION, database_name).find_one({'public_id': public_id})


def _row_data(document: dict[str, Any], section_id: str = SECTION_A, row_index: int = 0) -> list[dict[str, Any]]:
    """The data entries of one row of one MDS section of a stored object."""
    section = next(mds for mds in document['multi_data_sections'] if mds['section_id'] == section_id)

    return section['values'][row_index]['data']


def _propagate(
        objects_manager: ObjectsManager,
        old_fields: list[str],
        updated_fields: list[str] | None,
        **type_options: Any,
) -> int:
    """Plans the edit, runs its statements and answers how many documents they modified."""
    plan = plan_mds_changes(_old_type(old_fields), _type_doc(updated_fields, **type_options))

    return objects_manager.apply_raw_updates(build_mds_updates(TYPE_ID, plan))


class TestThePropagationAgainstARealDatabase:
    """What each kind of change does to the stored objects."""

    def test_adds_a_field_only_to_the_affected_object(
            self, objects_manager: ObjectsManager, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Adding 'b' to sec-a changes OBJECT_WITH_A only; sec-b and the MDS-less object stay as seeded."""
        assert _propagate(objects_manager, ['a'], ['a', 'b']) == 1

        assert [entry['name'] for entry in _row_data(_stored(database_manager, database_name, OBJECT_WITH_A))] \
            == ['a', 'b']
        assert _stored(database_manager, database_name, OBJECT_WITH_B)['multi_data_sections'] \
            == [_mds_section(SECTION_B)]
        assert _stored(database_manager, database_name, OBJECT_WITHOUT_MDS)['multi_data_sections'] == []

    def test_the_flat_fields_list_is_not_touched(
            self, objects_manager: ObjectsManager, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The MDS statements address the rows only - the flat list is the realign's business."""
        _propagate(objects_manager, ['a'], ['a', 'b'])

        assert _stored(database_manager, database_name, OBJECT_WITH_A)['fields'] \
            == [{'type': 'text', 'name': 'a', 'value': 'x'}]

    def test_a_new_field_carries_its_declared_type(
            self, objects_manager: ObjectsManager, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The type comes from the UPDATED type - the stored one cannot contain a field just added."""
        _propagate(objects_manager, ['a'], ['a', 'b'], field_types={'b': 'date'})

        new_entry = _row_data(_stored(database_manager, database_name, OBJECT_WITH_A))[1]
        assert new_entry == {'name': 'b', 'type': 'date', 'value': None}

    def test_a_new_field_starts_from_its_declared_default(
            self, objects_manager: ObjectsManager, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A definition's `value` is what an existing row gets for the new field."""
        _propagate(objects_manager, ['a'], ['a', 'b'], field_defaults={'b': 'preset'})

        assert _row_data(_stored(database_manager, database_name, OBJECT_WITH_A))[1]['value'] == 'preset'

    def test_every_row_gains_the_field_once(
            self, objects_manager: ObjectsManager, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Several rows each get one entry; a row already carrying the name is left alone."""
        second_row: dict[str, Any] = {'multi_data_id': 2, 'data': [
            {'name': 'a', 'value': 'y', 'type': 'text'}, {'name': 'b', 'value': 'kept', 'type': 'text'},
        ]}
        database_manager.get_collection(CmdbObject.COLLECTION, database_name).update_one(
            {'public_id': OBJECT_WITH_A}, {'$push': {'multi_data_sections.0.values': second_row}},
        )

        _propagate(objects_manager, ['a'], ['a', 'b'])

        stored = _stored(database_manager, database_name, OBJECT_WITH_A)
        assert [entry['name'] for entry in _row_data(stored, row_index=0)] == ['a', 'b']
        assert _row_data(stored, row_index=1) == second_row['data']

    def test_a_section_without_rows_gains_nothing(
            self, objects_manager: ObjectsManager, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A row only exists once a user captured one, so an empty section stays empty."""
        database_manager.get_collection(CmdbObject.COLLECTION, database_name).update_one(
            {'public_id': OBJECT_WITH_A}, {'$set': {'multi_data_sections.0.values': []}},
        )

        assert _propagate(objects_manager, ['a'], ['a', 'b']) == 0

    def test_removes_a_field_from_the_affected_object(
            self, objects_manager: ObjectsManager, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The destructive half: the entry goes from every row of the section."""
        assert _propagate(objects_manager, ['a', 'b'], ['b']) == 1

        assert _row_data(_stored(database_manager, database_name, OBJECT_WITH_A)) == []

    def test_removes_a_section_the_type_no_longer_declares(
            self, objects_manager: ObjectsManager, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The rule: the object stops carrying rows of a section its type does not have."""
        assert _propagate(objects_manager, ['a'], None) == 1

        assert _stored(database_manager, database_name, OBJECT_WITH_A)['multi_data_sections'] == []
        assert _stored(database_manager, database_name, OBJECT_WITH_B)['multi_data_sections'] \
            == [_mds_section(SECTION_B)]

    def test_an_unchanged_section_issues_no_statement(self, objects_manager: ObjectsManager) -> None:
        """A pure metadata edit has an empty plan, so nothing runs at all."""
        plan = plan_mds_changes(_old_type(['a']), _type_doc(['a']))

        assert build_mds_updates(TYPE_ID, plan) == []
        assert objects_manager.apply_raw_updates([]) == 0


class TestTheStatementsAreServerSide:
    """The two properties that come from not reading the objects."""

    @pytest.mark.parametrize('old_fields, updated_fields', [
        (['a'], ['a', 'b']),
        (['a', 'b'], ['b']),
        (['a'], None),
    ], ids=['add', 'remove-field', 'remove-section'])
    def test_a_second_run_modifies_nothing(
            self, objects_manager: ObjectsManager, old_fields: list[str], updated_fields: list[str] | None,
    ) -> None:
        """Every statement is idempotent, so re-running an edit is safe."""
        _propagate(objects_manager, old_fields, updated_fields)

        assert _propagate(objects_manager, old_fields, updated_fields) == 0

    def test_an_edit_saved_before_the_propagation_survives_it(
            self, objects_manager: ObjectsManager, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """
        A user's row edit that lands after the type edit is planned is kept

        The statements add and remove single entries in place, so they never write back a copy of the
        object that could be older than the object itself.
        """
        plan = plan_mds_changes(_old_type(['a']), _type_doc(['a', 'b']))
        database_manager.get_collection(CmdbObject.COLLECTION, database_name).update_one(
            {'public_id': OBJECT_WITH_A},
            {'$set': {'multi_data_sections.0.values.0.data.0.value': 'edited meanwhile'}},
        )

        objects_manager.apply_raw_updates(build_mds_updates(TYPE_ID, plan))

        assert _row_data(_stored(database_manager, database_name, OBJECT_WITH_A)) == [
            {'name': 'a', 'value': 'edited meanwhile', 'type': 'text'},
            {'name': 'b', 'value': None, 'type': 'text'},
        ]
