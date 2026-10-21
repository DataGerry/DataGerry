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
Integration tests for realign_type_objects_if_fields_changed against a real MongoDB

This is the automatic object reconciliation that replaced the manual "clean" step: on a type update
the type's objects are re-aligned with its field set, but only when the set of field names actually
changed. Seeds a type + two objects and asserts a field add reaches every object, a field removal is
pulled from every object, and a metadata-only edit (same field names) leaves the objects untouched.
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.type_model import CmdbType
from cmdb.models.object_model import CmdbObject
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_helper import (
    realign_type_objects_if_fields_changed,
)
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID: int = 9701
OBJ_ONE: int = 9711
OBJ_TWO: int = 9712
ALL_OBJECT_IDS: list[int] = [OBJ_ONE, OBJ_TWO]

FIELD_A: str = 'field-a'
FIELD_B: str = 'field-b'
FIELD_C: str = 'field-c'


@pytest.fixture(autouse=True)
def _render_context(rest_api):
    """Pushes the REST API app context so ManagerProvider resolves the database manager."""
    with rest_api.application.app_context():
        yield


def _type(field_names: list[str]) -> CmdbType:
    """Builds a CmdbType whose flat fields are the given (text) field names."""
    return CmdbType.from_data({
        'public_id': TYPE_ID,
        'name': 'realign-type',
        'label': 'Realign Type',
        'author_id': 1,
        'active': True,
        'fields': [{'type': 'text', 'name': name, 'label': name} for name in field_names],
        'render_meta': {
            'icon': '',
            'sections': [{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': field_names}],
            'summary': {'fields': []},
        },
        'version': '1.0.0',
    })


def _object_doc(public_id: int) -> dict[str, Any]:
    """A CmdbObject of TYPE_ID carrying field-a and field-b."""
    return {
        'public_id': public_id,
        'type_id': TYPE_ID,
        'active': True,
        'author_id': 1,
        'creation_time': datetime.now(timezone.utc),
        'version': '1.0.0',
        'fields': [
            {'type': 'text', 'name': FIELD_A, 'value': 'x'},
            {'type': 'text', 'name': FIELD_B, 'value': 'y'},
        ],
    }


@pytest.fixture(autouse=True)
def _seed(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds two objects of TYPE_ID (each with field-a + field-b), removed after the test."""
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    objects.delete_many({'public_id': {'$in': ALL_OBJECT_IDS}})
    objects.insert_many([_object_doc(OBJ_ONE), _object_doc(OBJ_TWO)])
    yield
    objects.delete_many({'public_id': {'$in': ALL_OBJECT_IDS}})


def _field_name_sets(database_manager: MongoDatabaseManager, database_name: str) -> list[set[str]]:
    """Returns the flat field-name set of each seeded object."""
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    return [
        {field['name'] for field in objects.find_one({'public_id': oid})['fields']}
        for oid in ALL_OBJECT_IDS
    ]


class TestRealignOnFieldChange:
    """realign_type_objects_if_fields_changed reconciles objects only when the field set changed."""

    def test_added_field_reaches_every_object(self, full_access_user,
                                              database_manager, database_name) -> None:
        """Adding a field name to the type adds it (empty) to every object of the type."""
        realign_type_objects_if_fields_changed(
            full_access_user, _type([FIELD_A, FIELD_B]), _type([FIELD_A, FIELD_B, FIELD_C]),
        )

        assert all(names == {FIELD_A, FIELD_B, FIELD_C} for names in _field_name_sets(database_manager, database_name))

    def test_removed_field_is_pulled_from_every_object(self, full_access_user,
                                                       database_manager, database_name) -> None:
        """Removing a field name from the type drops it from every object of the type."""
        realign_type_objects_if_fields_changed(
            full_access_user, _type([FIELD_A, FIELD_B]), _type([FIELD_A]),
        )

        assert all(names == {FIELD_A} for names in _field_name_sets(database_manager, database_name))

    def test_metadata_only_change_leaves_objects_untouched(self, full_access_user,
                                                          database_manager, database_name) -> None:
        """An edit that keeps the same field names (e.g. a label change) reconciles nothing."""
        realign_type_objects_if_fields_changed(
            full_access_user, _type([FIELD_A, FIELD_B]), _type([FIELD_A, FIELD_B]),
        )

        assert all(names == {FIELD_A, FIELD_B} for names in _field_name_sets(database_manager, database_name))
