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
Functional tests for the activation right on the object edit routes

``PUT /objects/state/<id>`` changes the active state behind ``base.framework.object.activation``. The edit routes
carry ``active`` in their body behind ``base.framework.object.edit``, so they ask for the activation right as well -
for each target whose stored state would change. Pinned, for a group with the edit right alone and one with both:
a change is a 403 naming the right on the single PUT, the bulk PUT and the bulk PATCH, and nothing is written; the
same body re-sending the stored state passes; with both rights it passes, and each changed target gets an
ACTIVE_CHANGE entry beside its EDIT entry
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.object_model import CmdbObject
from cmdb.models.right_model.right_constants import ObjectRightName
from cmdb.models.user_model import CmdbUser
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_constants import (
    ACTIVATION_RIGHT_MISSING_MESSAGE,
)

from tests.functional.framework.objects.objects_route_helpers import (
    NAME_FIELD,
    ORIGINAL_VALUE,
    ROUTE_URL,
    UPDATED_VALUE,
    object_doc,
    object_payload,
)
# -------------------------------------------------------------------------------------------------------------------- #

FIRST_ID: int = 93731
SECOND_ID: int = 93732
OBJECT_IDS: list[int] = [FIRST_ID, SECOND_ID]

EDITOR_GROUP_ID: int = 93733
ACTIVATOR_GROUP_ID: int = 93734
EDITOR_ID: int = 93735
ACTIVATOR_ID: int = 93736
EDITOR_NAME: str = 'activation-right-editor'
ACTIVATOR_NAME: str = 'activation-right-activator'

EDIT_RIGHTS: list[str] = [ObjectRightName.VIEW.value, ObjectRightName.EDIT.value]
ACTIVATION_MESSAGE: str = ACTIVATION_RIGHT_MISSING_MESSAGE.format(
    public_id=FIRST_ID, right=ObjectRightName.ACTIVATION.value,
)


@pytest.fixture(name='collections', autouse=True)
def fixture_collections(database_manager: MongoDatabaseManager, database_name: str):
    """Two active objects, an edit-only group and a group with the activation right too, one user each."""
    def collection(name: str) -> Any:
        return database_manager.get_collection(name, database_name)

    collections: dict[str, Any] = {
        'objects': collection(CmdbObject.COLLECTION), 'logs': collection(CmdbMetaLog.COLLECTION),
        'groups': collection(CmdbUserGroup.COLLECTION), 'users': collection(CmdbUser.COLLECTION),
    }
    _purge(collections)
    collections['objects'].insert_many([object_doc(public_id, ORIGINAL_VALUE) for public_id in OBJECT_IDS])
    collections['groups'].insert_many([
        {'public_id': EDITOR_GROUP_ID, 'name': EDITOR_NAME, 'label': EDITOR_NAME, 'rights': EDIT_RIGHTS},
        {'public_id': ACTIVATOR_GROUP_ID, 'name': ACTIVATOR_NAME, 'label': ACTIVATOR_NAME,
         'rights': [*EDIT_RIGHTS, ObjectRightName.ACTIVATION.value]},
    ])
    collections['users'].insert_many([
        {'public_id': EDITOR_ID, 'user_name': EDITOR_NAME, 'active': True, 'group_id': EDITOR_GROUP_ID,
         'registration_time': datetime.now(timezone.utc)},
        {'public_id': ACTIVATOR_ID, 'user_name': ACTIVATOR_NAME, 'active': True, 'group_id': ACTIVATOR_GROUP_ID,
         'registration_time': datetime.now(timezone.utc)},
    ])

    yield collections

    _purge(collections)


def _purge(collections: dict[str, Any]) -> None:
    """Removes everything the module wrote."""
    collections['objects'].delete_many({'public_id': {'$in': OBJECT_IDS}})
    collections['logs'].delete_many({'object_id': {'$in': OBJECT_IDS}})
    collections['groups'].delete_many({'public_id': {'$in': [EDITOR_GROUP_ID, ACTIVATOR_GROUP_ID]}})
    collections['users'].delete_many({'public_id': {'$in': [EDITOR_ID, ACTIVATOR_ID]}})


def _editor() -> dict[str, Any]:
    """The request kwargs that send it as the edit-only user."""
    return {'user': CmdbUser(public_id=EDITOR_ID, user_name=EDITOR_NAME, active=True, group_id=EDITOR_GROUP_ID)}


def _activator() -> dict[str, Any]:
    """The request kwargs that send it as the user holding the activation right too."""
    return {'user': CmdbUser(public_id=ACTIVATOR_ID, user_name=ACTIVATOR_NAME, active=True,
                             group_id=ACTIVATOR_GROUP_ID)}


def _put(rest_api, active: bool, value: str = ORIGINAL_VALUE, bulk: bool = False, **kwargs: Any):
    """PUT /objects/<FIRST_ID>, or the bulk PUT over both objects."""
    query: dict[str, Any] = {'objectIDs': OBJECT_IDS} if bulk else {}

    return rest_api.put(f'{ROUTE_URL}/{FIRST_ID}', json={**object_payload(FIRST_ID, value), 'active': active},
                        query_string=query, **kwargs)


def _bulk_patch(rest_api, body: dict[str, Any], **kwargs: Any):
    """PATCH /objects/?objectIDs= over both objects."""
    return rest_api.patch(f'{ROUTE_URL}/', json=body, query_string={'objectIDs': OBJECT_IDS}, **kwargs)


def _stored(collections: dict[str, Any], public_id: int) -> dict[str, Any]:
    """One object as stored."""
    return collections['objects'].find_one({'public_id': public_id})


def _actions(collections: dict[str, Any], public_id: int) -> list[str]:
    """The action names of one object's log entries, oldest first."""
    entries = collections['logs'].find({'object_id': public_id}).sort('public_id', 1)

    return [entry['action_name'] for entry in entries]


class TestTheEditRightAloneCannotChangeTheState:
    """403 naming the right, and nothing written"""

    def test_single_put(self, rest_api, collections) -> None:
        """A PUT deactivating the object, with a field change beside it - neither is written"""
        response = _put(rest_api, False, UPDATED_VALUE, **_editor())

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.get_json()['message'] == ACTIVATION_MESSAGE
        stored: dict[str, Any] = _stored(collections, FIRST_ID)
        assert stored['active'] is True
        assert stored['fields'][0]['value'] == ORIGINAL_VALUE
        assert not _actions(collections, FIRST_ID)

    def test_bulk_put(self, rest_api, collections) -> None:
        """The first target is refused, so neither target is written"""
        assert _put(rest_api, False, bulk=True, **_editor()).status_code == HTTPStatus.FORBIDDEN

        for public_id in OBJECT_IDS:
            assert _stored(collections, public_id)['active'] is True
            assert not _actions(collections, public_id)

    def test_bulk_patch(self, rest_api, collections) -> None:
        """The bulk change's active toggle"""
        response = _bulk_patch(rest_api, {'active': False}, **_editor())

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.get_json()['message'] == ACTIVATION_MESSAGE
        for public_id in OBJECT_IDS:
            assert _stored(collections, public_id)['active'] is True

    def test_a_later_target_refused_undoes_the_earlier_one(self, rest_api, collections) -> None:
        """Only the second object would change: the first, already written, is put back"""
        collections['objects'].update_one({'public_id': FIRST_ID}, {'$set': {'active': False}})

        response = _bulk_patch(
            rest_api, {'active': False, 'fields': [{'name': NAME_FIELD, 'value': UPDATED_VALUE}]}, **_editor(),
        )

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert _stored(collections, FIRST_ID)['fields'][0]['value'] == ORIGINAL_VALUE
        assert _stored(collections, SECOND_ID)['active'] is True


class TestTheStoredStateNeedsNoActivationRight:
    """Re-sending the state an object has is an ordinary edit"""

    def test_single_put_with_the_stored_state(self, rest_api, collections) -> None:
        """active: true on an active object, with a field change"""
        response = _put(rest_api, True, UPDATED_VALUE, **_editor())

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _stored(collections, FIRST_ID)['fields'][0]['value'] == UPDATED_VALUE
        assert _actions(collections, FIRST_ID) == [LogAction.EDIT.name]

    def test_bulk_patch_with_the_stored_state(self, rest_api) -> None:
        """active: true over two active objects"""
        assert _bulk_patch(rest_api, {'active': True}, **_editor()).status_code == HTTPStatus.ACCEPTED

    def test_a_patch_without_active(self, rest_api) -> None:
        """The single PATCH carries no active state, so the edit right is enough"""
        response = rest_api.patch(
            f'{ROUTE_URL}/{FIRST_ID}', json={'fields': [{'name': NAME_FIELD, 'value': UPDATED_VALUE}]}, **_editor(),
        )

        assert response.status_code == HTTPStatus.ACCEPTED


class TestWithTheActivationRight:
    """The change is written, and recorded as the state route records it"""

    def test_single_put_writes_and_logs_the_state_change(self, rest_api, collections) -> None:
        """An EDIT entry for the edit, an ACTIVE_CHANGE entry with {old, new} for the state"""
        assert _put(rest_api, False, **_activator()).status_code == HTTPStatus.ACCEPTED

        assert _stored(collections, FIRST_ID)['active'] is False
        assert _actions(collections, FIRST_ID) == [LogAction.EDIT.name, LogAction.ACTIVE_CHANGE.name]
        state_entry: dict[str, Any] = collections['logs'].find_one(
            {'object_id': FIRST_ID, 'action_name': LogAction.ACTIVE_CHANGE.name},
        )
        assert state_entry['changes'] == {'old': True, 'new': False}
        assert state_entry['user_id'] == ACTIVATOR_ID

    def test_bulk_patch_logs_each_changed_target(self, rest_api, collections) -> None:
        """Only the target whose state changed gets an ACTIVE_CHANGE entry"""
        collections['objects'].update_one({'public_id': SECOND_ID}, {'$set': {'active': False}})

        assert _bulk_patch(rest_api, {'active': False}, **_activator()).status_code == HTTPStatus.ACCEPTED

        assert _actions(collections, FIRST_ID) == [LogAction.EDIT.name, LogAction.ACTIVE_CHANGE.name]
        assert _actions(collections, SECOND_ID) == [LogAction.EDIT.name]

    def test_bulk_put_reactivates(self, rest_api, collections) -> None:
        """The other direction"""
        collections['objects'].update_many({'public_id': {'$in': OBJECT_IDS}}, {'$set': {'active': False}})

        assert _put(rest_api, True, bulk=True, **_activator()).status_code == HTTPStatus.ACCEPTED

        for public_id in OBJECT_IDS:
            assert _stored(collections, public_id)['active'] is True
