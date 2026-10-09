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
Integration tests for the alignment that follows a CmdbType update, against a real MongoDB

The situation a failed save leaves: the Type already stored in its new form and marked ``alignment_pending``, while
its Objects, Locations and Reports still carry the old one. Saving the Type again (old state == new state) must still
bring everything in line - every step forced, state-based - clear the marker, and change nothing on a second run.
Without the marker, an unchanged save stays the cheap no-op it always was
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager.types_mds_helper import build_mds_alignment_updates
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType, TypeSchemaKey
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_helper import apply_type_update_side_effects
from tests.utils import type_alignment_seed as seed
# -------------------------------------------------------------------------------------------------------------------- #

GHOST_SECTION: str = 'ghost-section'
PENDING: str = TypeSchemaKey.ALIGNMENT_PENDING.value


@pytest.fixture(autouse=True)
def _seeded(rest_api, database_manager: MongoDatabaseManager, database_name: str):
    """
    The state a failed save leaves: the Type in its new form and marked, everything else in the old one - plus an
    MDS section no version of the Type declares
    """
    seed.seed(database_manager, database_name, with_template=False)
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    new_form: dict[str, Any] = seed.updated_payload(types.find_one({'public_id': seed.TYPE_ID}))
    new_form[PENDING] = True
    types.replace_one({'public_id': seed.TYPE_ID}, new_form)
    database_manager.get_collection(CmdbObject.COLLECTION, database_name).update_many(
        {'public_id': {'$in': seed.OBJECT_IDS}},
        {'$push': {'multi_data_sections': {'section_id': GHOST_SECTION, 'values': []}}},
    )

    with rest_api.application.test_request_context():
        yield

    seed.purge(database_manager, database_name)


def _stored(database_manager: MongoDatabaseManager, database_name: str) -> CmdbType:
    """The stored Type."""
    return CmdbType.from_data(seed.stored_type(database_manager, database_name))


def _save_again(user: Any, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """What a second save of the same payload runs: the stored Type is both the old and the new state"""
    stored = _stored(database_manager, database_name)
    apply_type_update_side_effects(user, ManagerProvider.get_manager(ManagerType.TYPES, user), stored, stored)


def _objects(database_manager: MongoDatabaseManager, database_name: str) -> list[dict[str, Any]]:
    """The seeded objects as stored, without their _id."""
    return [{key: value for key, value in doc.items() if key != '_id'}
            for doc in database_manager.get_collection(CmdbObject.COLLECTION, database_name).find(
                {'public_id': {'$in': seed.OBJECT_IDS}}, sort=[('public_id', 1)])]


class TestAPendingTypeSavedAgain:
    """Every step forced: the drift is gone and the marker cleared."""

    def test_the_locations_follow(self, full_access_user, database_manager, database_name) -> None:
        """The label the nodes carry is the Type's, although the save changed none"""
        _save_again(full_access_user, database_manager, database_name)

        assert seed.node_labels(database_manager, database_name) == {seed.AFTER_LABEL}

    def test_the_flat_fields_follow(self, full_access_user, database_manager, database_name) -> None:
        """The removed fields are gone from every object, the kept one kept its value"""
        _save_again(full_access_user, database_manager, database_name)

        for names in seed.object_field_names(database_manager, database_name):
            assert names == {seed.NAME_FIELD, seed.KEEP, seed.MDS_A}
        assert all(field['value'] == seed.STORED_VALUE
                   for doc in _objects(database_manager, database_name) for field in doc['fields'])

    def test_the_mds_rows_follow(self, full_access_user, database_manager, database_name) -> None:
        """The removed row field is gone, and so is a section the Type never declared"""
        _save_again(full_access_user, database_manager, database_name)

        for names in seed.mds_row_names(database_manager, database_name):
            assert names == {seed.MDS_A}
        for doc in _objects(database_manager, database_name):
            assert [section['section_id'] for section in doc['multi_data_sections']] == [seed.MDS_SECTION]

    def test_the_report_follows(self, full_access_user, database_manager, database_name) -> None:
        """Its stale column and rule go, although the save itself removed no field"""
        _save_again(full_access_user, database_manager, database_name)
        report = seed.report(database_manager, database_name)

        assert report['selected_fields'] == [seed.KEEP]
        assert report['conditions'] is None

    def test_the_marker_is_cleared(self, full_access_user, database_manager, database_name) -> None:
        """Only once every step succeeded"""
        _save_again(full_access_user, database_manager, database_name)

        assert _stored(database_manager, database_name).alignment_pending is False

    def test_a_second_run_changes_nothing(self, full_access_user, database_manager, database_name) -> None:
        """Idempotent: forced once more, the objects are exactly as the first run left them"""
        _save_again(full_access_user, database_manager, database_name)
        after_first: list[dict[str, Any]] = _objects(database_manager, database_name)
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        types.update_one({'public_id': seed.TYPE_ID}, {'$set': {PENDING: True}})

        _save_again(full_access_user, database_manager, database_name)

        assert _objects(database_manager, database_name) == after_first


class TestAnUnmarkedTypeSavedUnchanged:
    """Without the marker an unchanged save is the cheap no-op it always was."""

    def test_nothing_is_touched(self, full_access_user, database_manager, database_name) -> None:
        """The drift stays - nothing says there is any"""
        database_manager.get_collection(CmdbType.COLLECTION, database_name).update_one(
            {'public_id': seed.TYPE_ID}, {'$set': {PENDING: False}})
        before: list[dict[str, Any]] = _objects(database_manager, database_name)

        _save_again(full_access_user, database_manager, database_name)

        assert _objects(database_manager, database_name) == before
        assert seed.node_labels(database_manager, database_name) == {seed.BEFORE_LABEL}


class TestTheMdsAlignmentStatements:
    """build_mds_alignment_updates against the real server."""

    def test_they_keep_every_declared_value(self, database_manager, database_name) -> None:
        """Only what the type does not declare goes; MDS_A keeps its value"""
        objects_manager = ManagerProvider.get_manager(ManagerType.OBJECTS, None)

        objects_manager.apply_raw_updates(build_mds_alignment_updates(_stored(database_manager, database_name)))

        for doc in _objects(database_manager, database_name):
            (row,) = doc['multi_data_sections'][0]['values']
            assert row['data'] == [{'name': seed.MDS_A, 'type': 'text', 'value': seed.STORED_VALUE}]
