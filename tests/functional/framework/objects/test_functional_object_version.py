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
Functional tests for the version an object update writes

The version moves only when a field value or a multi-data section changed. A save that changes nothing
else - the stored object sent back, the active flag alone, a field entry whose ``type`` key was filled in -
is still written, stamped and logged, and keeps its version. The rule itself is unit-tested with
``compute_object_version``; these pin it at the routes
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.object_model import CmdbObject, CmdbObjectKey
from cmdb.models.type_model import CmdbType

from tests.functional.framework.objects.objects_route_helpers import (
    MDS_REF_FIELD,
    MDS_REF_TYPE_ID,
    NAME_FIELD,
    ORIGINAL_VALUE,
    REQUEST_USER_ID,
    ROUTE_URL,
    SEED_VERSION,
    UPDATED_VALUE,
    UPDATE_VERSION,
    mds_ref_type_doc,
    mds_referencing_object_doc,
    object_doc,
    object_payload,
)
# -------------------------------------------------------------------------------------------------------------------- #

OBJECT_ID: int = 9484

MDS_SOURCE_ID: int = 9485

MDS_TARGET_ID: int = 9487

MDS_OTHER_TARGET_ID: int = 9488

MDS_SECTION_ID: str = 'mds-section'

ALL_IDS: list[int] = [OBJECT_ID, MDS_SOURCE_ID, MDS_TARGET_ID, MDS_OTHER_TARGET_ID]


@pytest.fixture(name='collections')
def fixture_collections(database_manager: MongoDatabaseManager, database_name: str):
    """The objects and logs collections, with the MDS type and the module's objects removed after each test."""
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    logs = database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name)
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)

    yield {'objects': objects, 'logs': logs, 'types': types}

    objects.delete_many({'public_id': {'$in': ALL_IDS}})
    logs.delete_many({'object_id': {'$in': ALL_IDS}})
    types.delete_one({'public_id': MDS_REF_TYPE_ID})


def _edit_logs(collections: dict[str, Any], public_id: int) -> list[dict[str, Any]]:
    """Every EDIT log entry of one object."""
    return list(collections['logs'].find({'object_id': public_id, 'action_name': LogAction.EDIT.name}))


class TestASaveThatChangesNothingKeepsTheVersion:
    """Written, stamped and logged as before - only the version stays"""

    def test_put_of_the_stored_object(self, rest_api, collections) -> None:
        """PUT with the stored values"""
        collections['objects'].insert_one(object_doc(OBJECT_ID, ORIGINAL_VALUE))

        response = rest_api.put(f'{ROUTE_URL}/{OBJECT_ID}', json=object_payload(OBJECT_ID, ORIGINAL_VALUE))

        assert response.status_code == HTTPStatus.ACCEPTED
        stored: dict[str, Any] = collections['objects'].find_one({'public_id': OBJECT_ID})
        assert stored['version'] == SEED_VERSION
        assert stored['editor_id'] == REQUEST_USER_ID
        assert stored['last_edit_time'] is not None
        [edit_log] = _edit_logs(collections, OBJECT_ID)
        assert edit_log['version'] == SEED_VERSION
        assert edit_log['changes'] == {'old': [], 'new': []}

    def test_patch_with_the_stored_value(self, rest_api, collections) -> None:
        """PATCH naming a field with the value it already has"""
        collections['objects'].insert_one(object_doc(OBJECT_ID, ORIGINAL_VALUE))

        response = rest_api.patch(
            f'{ROUTE_URL}/{OBJECT_ID}', json={'fields': [{'name': NAME_FIELD, 'value': ORIGINAL_VALUE}]},
        )

        assert response.status_code == HTTPStatus.ACCEPTED
        assert collections['objects'].find_one({'public_id': OBJECT_ID})['version'] == SEED_VERSION

    def test_the_active_flag_alone(self, rest_api, collections) -> None:
        """Deactivating through PUT is written but not versioned - like the state route"""
        collections['objects'].insert_one(object_doc(OBJECT_ID, ORIGINAL_VALUE))
        payload: dict[str, Any] = {**object_payload(OBJECT_ID, ORIGINAL_VALUE), 'active': False}

        assert rest_api.put(f'{ROUTE_URL}/{OBJECT_ID}', json=payload).status_code == HTTPStatus.ACCEPTED

        stored: dict[str, Any] = collections['objects'].find_one({'public_id': OBJECT_ID})
        assert stored['active'] is False
        assert stored['version'] == SEED_VERSION

    def test_a_type_key_filled_in_alone(self, rest_api, collections) -> None:
        """A stored entry without its type key, sent back with it, is the same value"""
        document: dict[str, Any] = object_doc(OBJECT_ID, ORIGINAL_VALUE)
        document['fields'] = [{'name': NAME_FIELD, 'value': ORIGINAL_VALUE}]
        collections['objects'].insert_one(document)

        response = rest_api.put(f'{ROUTE_URL}/{OBJECT_ID}', json=object_payload(OBJECT_ID, ORIGINAL_VALUE))

        assert response.status_code == HTTPStatus.ACCEPTED
        assert collections['objects'].find_one({'public_id': OBJECT_ID})['version'] == SEED_VERSION
        [edit_log] = _edit_logs(collections, OBJECT_ID)
        assert edit_log['changes'] == {'old': [], 'new': []}


def test_a_changed_value_still_bumps(rest_api, collections) -> None:
    """The control case: a changed value is a patch"""
    collections['objects'].insert_one(object_doc(OBJECT_ID, ORIGINAL_VALUE))

    response = rest_api.put(f'{ROUTE_URL}/{OBJECT_ID}', json=object_payload(OBJECT_ID, UPDATED_VALUE))

    assert response.status_code == HTTPStatus.ACCEPTED
    assert collections['objects'].find_one({'public_id': OBJECT_ID})['version'] == UPDATE_VERSION


def test_a_multi_data_row_edit_alone_bumps_and_logs_the_section(rest_api, collections) -> None:
    """A PATCH that edits only an MDS row is a patch, and its log records the section both ways"""
    collections['types'].insert_one(mds_ref_type_doc())
    collections['objects'].insert_one(object_doc(MDS_TARGET_ID, ORIGINAL_VALUE))
    collections['objects'].insert_one(object_doc(MDS_OTHER_TARGET_ID, ORIGINAL_VALUE))
    collections['objects'].insert_one(mds_referencing_object_doc(MDS_SOURCE_ID, MDS_TARGET_ID))

    response = rest_api.patch(f'{ROUTE_URL}/{MDS_SOURCE_ID}', json={'edited_mds_rows': [{
        'section_id': MDS_SECTION_ID, 'multi_data_id': 1,
        'data': [{'name': MDS_REF_FIELD, 'value': MDS_OTHER_TARGET_ID}],
    }]})

    assert response.status_code == HTTPStatus.ACCEPTED
    assert collections['objects'].find_one({'public_id': MDS_SOURCE_ID})['version'] == UPDATE_VERSION
    [edit_log] = _edit_logs(collections, MDS_SOURCE_ID)
    assert edit_log['version'] == UPDATE_VERSION
    section_changes: dict[str, Any] = edit_log['changes'][CmdbObjectKey.MULTI_DATA_SECTIONS.value]
    [old_section] = section_changes['old']
    [new_section] = section_changes['new']
    assert old_section['values'][0]['data'][0]['value'] == MDS_TARGET_ID
    assert new_section['values'][0]['data'][0]['value'] == MDS_OTHER_TARGET_ID
