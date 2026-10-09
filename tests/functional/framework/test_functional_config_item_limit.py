# DataGerry - OpenSource Enterprise CMDB
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
Functional coverage of the cloud ConfigItem limit on ``POST /objects/``

The limit is a cloud-mode rule, so every test switches the app into cloud mode and sends as a user
bound to the test database - a cloud token names the tenant database next to the user id, which the
default test client's token does not. Hosted cloud mode reads the RSA keypair from the environment,
so the test database's own keypair is exported there for the duration of a test. The Service Portal
sync that follows a successful create is replaced by a stub, so nothing leaves the process.

What is pinned: a stored limit of 0 refuses the first object, a limit the stored count has reached
refuses the next one, and a stored null limit is the default rather than a crash - each through the
real route, with the refusal leaving nothing behind
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.class_schema.user_model.cmdb_user_schema import DEFAULT_CONFIG_ITEMS_LIMIT
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID
from cmdb.framework import config_item_sync

from tests.utils.cloud_mode import cloud_auth_header, enable_hosted_cloud_mode
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/objects/'

TYPE_ID: int = 9690
USER_ID: int = 9691
AUTHOR_ID: int = 1
VERSION: str = '1.0.0'

LIMIT_REACHED_MESSAGE: str = 'The maximum amount of ConfigItems is reached!'


def _type_doc() -> dict[str, Any]:
    """A field-less CmdbType, enough for an object to be created in it."""
    return {
        'public_id': TYPE_ID,
        'name': 'config-item-limit-type',
        'label': 'Config Item Limit Type',
        'author_id': AUTHOR_ID,
        'creation_time': datetime.now(timezone.utc),
        'active': True,
        'fields': [],
        'render_meta': {'icon': 'fa-cube', 'sections': [], 'summary': {'fields': []}},
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': VERSION,
    }


def _payload() -> dict[str, Any]:
    """A complete, valid object for the seeded type; the server assigns its public_id."""
    return {
        'type_id': TYPE_ID,
        'active': True,
        'author_id': AUTHOR_ID,
        'version': VERSION,
        'fields': [],
    }


@pytest.fixture(scope='module', autouse=True)
def _seed_type_and_cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the CmdbType and removes it, the objects created in it and their logs afterwards."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    types.insert_one(_type_doc())
    yield
    created_ids: list[int] = [document['public_id'] for document in objects.find({'type_id': TYPE_ID})]
    types.delete_one({'public_id': TYPE_ID})
    objects.delete_many({'type_id': TYPE_ID})
    database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name).delete_many(
        {'object_id': {'$in': created_ids}}
    )


@pytest.fixture(name='cloud_mode')
def fixture_cloud_mode(rest_api, monkeypatch, database_manager: MongoDatabaseManager) -> MagicMock:
    """Switches the app into cloud mode and stubs the Service Portal; yields the stub to assert on."""
    enable_hosted_cloud_mode(rest_api, monkeypatch, database_manager)
    portal = MagicMock(name='DgServicePortalManager')
    monkeypatch.setattr(config_item_sync, 'DgServicePortalManager', portal)

    return portal


@pytest.fixture(name='send_as_tenant_user')
def fixture_send_as_tenant_user(rest_api, database_manager: MongoDatabaseManager, database_name: str):
    """
    Stores the tenant user with a given limit and answers a POST function sending as that user

    The user sits in the admin group, so the only thing that can refuse the create is the limit
    """
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)

    def _send(limit: Any) -> Any:
        users.delete_many({'public_id': USER_ID})
        users.insert_one({
            'public_id': USER_ID,
            'user_name': 'config-item-limit-user',
            'active': True,
            'group_id': ADMIN_GROUP_ID,
            'registration_time': datetime.now(timezone.utc),
            'database': database_name,
            'config_items_limit': limit,
        })
        return rest_api.post(
            ROUTE_URL, json=_payload(), environ_overrides=cloud_auth_header(rest_api, USER_ID, database_name),
        )

    yield _send

    users.delete_many({'public_id': USER_ID})


def _stored_objects(database_manager: MongoDatabaseManager, database_name: str) -> int:
    """How many CmdbObjects the tenant database holds."""
    return database_manager.get_collection(CmdbObject.COLLECTION, database_name).count_documents({})


def test_a_limit_of_zero_refuses_the_first_object(
        cloud_mode: MagicMock, send_as_tenant_user, database_manager, database_name) -> None:
    """0 is a real limit: the create is refused and nothing is written or synced"""
    before: int = _stored_objects(database_manager, database_name)

    response = send_as_tenant_user(0)

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert LIMIT_REACHED_MESSAGE in response.get_json()['message']
    assert _stored_objects(database_manager, database_name) == before
    cloud_mode.assert_not_called()


def test_a_reached_limit_refuses_the_next_object(
        cloud_mode: MagicMock, send_as_tenant_user, database_manager, database_name) -> None:
    """A limit equal to the stored count is reached - the next object is one too many"""
    response = send_as_tenant_user(_stored_objects(database_manager, database_name))

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert LIMIT_REACHED_MESSAGE in response.get_json()['message']
    cloud_mode.assert_not_called()


def test_a_free_slot_lets_the_object_through_and_syncs_the_count(
        cloud_mode: MagicMock, send_as_tenant_user, database_manager, database_name) -> None:
    """One slot below the limit the create succeeds, and the new total is reported to the portal"""
    response = send_as_tenant_user(_stored_objects(database_manager, database_name) + 1)

    assert response.status_code == HTTPStatus.OK
    cloud_mode.return_value.sync_config_items.assert_called_once()


def test_a_null_limit_is_the_default_not_a_crash(
        cloud_mode: MagicMock, send_as_tenant_user, database_manager, database_name) -> None:
    """
    A stored null limit means "not configured" and is compared as the default

    The suite's own object count decides which side of the default this run is on, so the expected
    answer is derived from it - either way the route answers the limit rule, never a server error
    """
    del cloud_mode
    below_default: bool = _stored_objects(database_manager, database_name) < DEFAULT_CONFIG_ITEMS_LIMIT

    response = send_as_tenant_user(None)

    assert response.status_code == (HTTPStatus.OK if below_default else HTTPStatus.BAD_REQUEST)
