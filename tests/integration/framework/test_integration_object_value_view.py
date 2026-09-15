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
Integration tests for the CmdbObject value view against a real MongoDB instance

The unit tests pin the reshaping against hand-written documents; these pin it against documents that
went through ``ObjectsManager`` and came back out of storage. That is the part a unit test cannot
cover: if the STORED shape of ``fields`` or ``multi_data_sections`` ever drifts from what
``build_object_value_view`` reads, the unit tests keep passing while the route stops answering
anything useful, so the round trip is asserted here.

The value view is a read-only serialisation - it drops each field entry's ``type``, every MDS row's
``multi_data_id`` and each section's ``highest_id`` - so the write-back direction is deliberately
NOT exercised: there is nothing to write back
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.objects_manager import ObjectsManager
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_helper import (
    build_object_value_view,
)
# -------------------------------------------------------------------------------------------------------------------- #

SEED_TYPE_ID: int = 9601
SEED_TYPE_NAME: str = 'test-value-view-type'
SEED_AUTHOR_ID: int = 1
SEED_VERSION: str = '1.0.0'

NAME_FIELD: str = 'name-field'
NUMBER_FIELD: str = 'number-field'

OBJECT_ID_PLAIN: int = 9611
OBJECT_ID_WITH_MDS: int = 9612
OBJECT_ID_EMPTY_MDS: int = 9613

NAME_VALUE: str = 'srv-01'
NUMBER_VALUE: int = 8

# Two sections, each with two rows, and the two sections deliberately reuse the row ids 1 and 2: a
# multi_data_id is unique only WITHIN its section, so this is the shape that would break any reshaping
# that keyed rows globally
FIRST_SECTION: str = 'mds-first-section'
SECOND_SECTION: str = 'mds-second-section'
FIRST_SECTION_FIELD: str = 'first-row-field'
SECOND_SECTION_FIELD: str = 'second-row-field'
FIRST_SECTION_VALUES: list[str] = ['first-row-one', 'first-row-two']
SECOND_SECTION_VALUES: list[str] = ['second-row-one', 'second-row-two']

SEED_OBJECT_IDS: list[int] = [OBJECT_ID_PLAIN, OBJECT_ID_WITH_MDS, OBJECT_ID_EMPTY_MDS]


def _type_doc() -> dict[str, Any]:
    """Builds the active CmdbType the seeded objects belong to."""
    return {
        'public_id': SEED_TYPE_ID,
        'name': SEED_TYPE_NAME,
        'label': 'Value View Type',
        'author_id': SEED_AUTHOR_ID,
        'creation_time': datetime.now(timezone.utc),
        'active': True,
        'fields': [
            {'type': 'text', 'name': NAME_FIELD, 'label': 'Name'},
            {'type': 'number', 'name': NUMBER_FIELD, 'label': 'Number'},
        ],
        'render_meta': {
            'icon': 'fa-cube',
            'sections': [{
                'type': 'section',
                'name': 'main',
                'label': 'Main',
                'fields': [NAME_FIELD, NUMBER_FIELD],
            }],
            'summary': {'fields': [NAME_FIELD]},
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': SEED_VERSION,
    }


def _object_data(public_id: int) -> dict[str, Any]:
    """Builds a CmdbObject payload with both regular fields populated."""
    return {
        'public_id': public_id,
        'type_id': SEED_TYPE_ID,
        'active': True,
        'author_id': SEED_AUTHOR_ID,
        'version': SEED_VERSION,
        'creation_time': datetime.now(timezone.utc),
        'fields': [
            {'type': 'text', 'name': NAME_FIELD, 'value': NAME_VALUE},
            {'type': 'number', 'name': NUMBER_FIELD, 'value': NUMBER_VALUE},
        ],
    }


def _mds_section(section_id: str, field_name: str, row_values: list[str]) -> dict[str, Any]:
    """Builds one stored MDS section whose rows are numbered from 1, as the write paths number them."""
    return {
        'section_id': section_id,
        'highest_id': len(row_values),
        'values': [
            {
                'multi_data_id': index + 1,
                'data': [{'name': field_name, 'value': row_value, 'type': 'text'}],
            }
            for index, row_value in enumerate(row_values)
        ],
    }


@pytest.fixture(scope='module', autouse=True)
def _seed_type_and_cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the CmdbType and the three objects, and removes everything afterwards."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    types.insert_one(_type_doc())

    plain = _object_data(OBJECT_ID_PLAIN)

    with_mds = _object_data(OBJECT_ID_WITH_MDS)
    with_mds['multi_data_sections'] = [
        _mds_section(FIRST_SECTION, FIRST_SECTION_FIELD, FIRST_SECTION_VALUES),
        _mds_section(SECOND_SECTION, SECOND_SECTION_FIELD, SECOND_SECTION_VALUES),
    ]

    empty_mds = _object_data(OBJECT_ID_EMPTY_MDS)
    empty_mds['multi_data_sections'] = [_mds_section(FIRST_SECTION, FIRST_SECTION_FIELD, [])]

    objects.insert_many([plain, with_mds, empty_mds])

    yield

    types.delete_one({'public_id': SEED_TYPE_ID})
    objects.delete_many({'public_id': {'$in': SEED_OBJECT_IDS}})


@pytest.fixture(name='objects_manager')
def fixture_objects_manager(database_manager: MongoDatabaseManager) -> ObjectsManager:
    """Provides an ObjectsManager wired to the test database."""
    return ObjectsManager(database_manager)


def _value_view(objects_manager: ObjectsManager, public_id: int) -> dict[str, Any]:
    """Reads one object back out of storage and reshapes it the way the routes do."""
    stored: dict[str, Any] = objects_manager.get_object(public_id, as_dict=True)

    return build_object_value_view(stored)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   REGULAR FIELDS                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestStoredFieldsReshaping:
    """A document read back from Mongo reshapes into a name-keyed field map."""

    def test_every_stored_field_becomes_one_key(self, objects_manager: ObjectsManager) -> None:
        """Both fields of the stored object appear in the map, keyed by their names."""
        view = _value_view(objects_manager, OBJECT_ID_PLAIN)

        assert view['fields'] == {NAME_FIELD: NAME_VALUE, NUMBER_FIELD: NUMBER_VALUE}

    def test_value_types_survive_the_round_trip(self, objects_manager: ObjectsManager) -> None:
        """
        A number stays a number through storage and reshaping

        The view drops each entry's declared 'type', so the JSON type of the value is all a consumer
        has left to go on - it must not be stringified on the way out.
        """
        view = _value_view(objects_manager, OBJECT_ID_PLAIN)

        assert isinstance(view['fields'][NUMBER_FIELD], int)
        assert isinstance(view['fields'][NAME_FIELD], str)

    def test_the_identity_keys_are_the_stored_ones(self, objects_manager: ObjectsManager) -> None:
        """public_id and type_id come from storage untouched, so a list row is identifiable."""
        view = _value_view(objects_manager, OBJECT_ID_PLAIN)

        assert view['public_id'] == OBJECT_ID_PLAIN
        assert view['type_id'] == SEED_TYPE_ID

    def test_an_object_stored_without_mds_answers_an_empty_map(self, objects_manager: ObjectsManager) -> None:
        """
        The key is always present

        An object of a type with no MDS section stores no 'multi_data_sections' at all, and the view
        still has to answer the key so a consumer never has to branch on its absence.
        """
        view = _value_view(objects_manager, OBJECT_ID_PLAIN)

        assert view['multi_data_sections'] == {}


# -------------------------------------------------------------------------------------------------------------------- #
#                                             MULTI DATA SECTIONS                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
class TestStoredMdsReshaping:
    """Stored MDS sections reshape into a section-keyed map of row value maps."""

    def test_each_stored_section_becomes_one_key(self, objects_manager: ObjectsManager) -> None:
        """Both sections of the stored object appear, keyed by their section_id."""
        view = _value_view(objects_manager, OBJECT_ID_WITH_MDS)

        assert set(view['multi_data_sections']) == {FIRST_SECTION, SECOND_SECTION}

    def test_rows_keep_their_stored_order(self, objects_manager: ObjectsManager) -> None:
        """Rows come back in the order they are stored in, since the view carries no row ids."""
        view = _value_view(objects_manager, OBJECT_ID_WITH_MDS)

        assert view['multi_data_sections'][FIRST_SECTION] == [
            {FIRST_SECTION_FIELD: row_value} for row_value in FIRST_SECTION_VALUES
        ]

    def test_two_sections_reusing_the_same_row_ids_stay_separate(
        self,
        objects_manager: ObjectsManager,
    ) -> None:
        """
        A multi_data_id is unique only WITHIN its section

        Both seeded sections hold a row 1 and a row 2. Keyed by section, that is not a collision -
        which is exactly what a globally-keyed reshaping would have got wrong.
        """
        view = _value_view(objects_manager, OBJECT_ID_WITH_MDS)

        assert view['multi_data_sections'][SECOND_SECTION] == [
            {SECOND_SECTION_FIELD: row_value} for row_value in SECOND_SECTION_VALUES
        ]

    def test_the_row_identity_is_not_in_the_payload(self, objects_manager: ObjectsManager) -> None:
        """
        No row carries its multi_data_id or the section's highest_id

        This is the property that makes the view read-only, asserted against a document that really
        does carry both in storage.
        """
        stored: dict[str, Any] = objects_manager.get_object(OBJECT_ID_WITH_MDS, as_dict=True)
        stored_section = next(
            section for section in stored['multi_data_sections']
            if section['section_id'] == FIRST_SECTION
        )
        assert stored_section['highest_id'] == len(FIRST_SECTION_VALUES)
        assert stored_section['values'][0]['multi_data_id'] == 1

        view = build_object_value_view(stored)

        for row in view['multi_data_sections'][FIRST_SECTION]:
            assert list(row) == [FIRST_SECTION_FIELD]

    def test_a_stored_empty_section_stays_an_empty_list(self, objects_manager: ObjectsManager) -> None:
        """
        A section stored with no rows is reported as present and empty

        "The section exists and has no rows" has to stay distinguishable from "no such section".
        """
        view = _value_view(objects_manager, OBJECT_ID_EMPTY_MDS)

        assert view['multi_data_sections'] == {FIRST_SECTION: []}


# -------------------------------------------------------------------------------------------------------------------- #
#                                              THE STORED DOCUMENT                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestStorageIsUntouched:
    """Reshaping is a read-path transform and must not reach storage."""

    def test_reshaping_does_not_rewrite_the_stored_document(
        self,
        objects_manager: ObjectsManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """
        After building the view, the stored document still holds its arrays

        The view is handed the document the manager just read; if it reshaped in place, a later write
        of that same object would persist the lossy shape.
        """
        _value_view(objects_manager, OBJECT_ID_WITH_MDS)

        raw = database_manager.get_collection(CmdbObject.COLLECTION, database_name).find_one(
            {'public_id': OBJECT_ID_WITH_MDS},
        )

        assert isinstance(raw['fields'], list)
        assert raw['fields'][0]['name'] == NAME_FIELD
        assert raw['fields'][0]['type'] == 'text'
        assert isinstance(raw['multi_data_sections'], list)
        assert raw['multi_data_sections'][0]['values'][0]['multi_data_id'] == 1
