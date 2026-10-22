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
The ConfigItem sync never fails the object write it reports on

The app runs as a hosted cloud installation whose service portal is NOT configured - no ``X-ACCESS-TOKEN`` and no
``DG_SP_BASE_URL`` - so the real ``DgServicePortalManager`` constructor raises. The object create, the single and
the bulk delete must still answer success, with the write and its log in place, and the skipped sync logged. A
configured portal is the control: it is asked once per write, through a stub, so nothing leaves the process
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.framework import config_item_sync
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser

from tests.utils.cloud_mode import cloud_auth_header, enable_hosted_cloud_mode
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID: int = 9790
USER_ID: int = 9791
SEEDED_IDS: list[int] = [9792, 9793, 9794]
AUTHOR_ID: int = 1
VERSION: str = '1.0.0'

PORTAL_ENV_VARS: tuple[str, ...] = ('X-ACCESS-TOKEN', 'DG_SP_BASE_URL')
SKIPPED_MARKER: str = 'not configured, sync skipped'


def _object_doc(public_id: int) -> dict[str, Any]:
    """A stored object of the seeded type."""
    return {'public_id': public_id, 'type_id': TYPE_ID, 'active': True, 'author_id': AUTHOR_ID, 'version': VERSION,
            'creation_time': datetime.now(timezone.utc), 'fields': [], 'multi_data_sections': []}


@pytest.fixture(autouse=True)
def _seeded(database_manager: MongoDatabaseManager, database_name: str):
    """A field-less type, three objects of it and a tenant user in the admin group - removed after, with the logs."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    logs = database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name)

    def purge() -> None:
        written: list[int] = [document['public_id'] for document in objects.find({'type_id': TYPE_ID})]
        types.delete_many({'public_id': TYPE_ID})
        objects.delete_many({'type_id': TYPE_ID})
        users.delete_many({'public_id': USER_ID})
        logs.delete_many({'object_id': {'$in': written + SEEDED_IDS}})

    purge()
    types.insert_one({
        'public_id': TYPE_ID, 'name': 'config-item-sync-type', 'label': 'Config Item Sync Type',
        'author_id': AUTHOR_ID, 'creation_time': datetime.now(timezone.utc), 'active': True, 'fields': [],
        'render_meta': {'icon': 'fa-cube', 'sections': [], 'summary': {'fields': []}},
        'acl': {'activated': False, 'groups': {'includes': None}}, 'version': VERSION,
    })
    objects.insert_many([_object_doc(public_id) for public_id in SEEDED_IDS])
    users.insert_one({
        'public_id': USER_ID, 'user_name': 'config-item-sync-user', 'active': True, 'group_id': ADMIN_GROUP_ID,
        'registration_time': datetime.now(timezone.utc), 'database': database_name, 'config_items_limit': None,
    })
    yield
    purge()


@pytest.fixture(name='unconfigured_portal')
def fixture_unconfigured_portal(rest_api, monkeypatch, database_manager: MongoDatabaseManager) -> None:
    """Hosted cloud, and no portal configuration at all: the real constructor raises NoAccessTokenError"""
    enable_hosted_cloud_mode(rest_api, monkeypatch, database_manager)

    for env_var in PORTAL_ENV_VARS:
        monkeypatch.delenv(env_var, raising=False)


@pytest.fixture(name='portal')
def fixture_portal(rest_api, monkeypatch, database_manager: MongoDatabaseManager) -> MagicMock:
    """Hosted cloud with a portal stub - the control"""
    enable_hosted_cloud_mode(rest_api, monkeypatch, database_manager)
    portal = MagicMock(name='DgServicePortalManager')
    monkeypatch.setattr(config_item_sync, 'DgServicePortalManager', portal)

    return portal


def _as_tenant(rest_api, database_name: str) -> dict[str, Any]:
    """The request kwargs authenticating as the tenant user."""
    return {'environ_overrides': cloud_auth_header(rest_api, USER_ID, database_name)}


def _stored(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> bool:
    """Whether the object is stored."""
    return database_manager.get_collection(CmdbObject.COLLECTION, database_name).count_documents(
        {'public_id': public_id}) == 1


def _logged(database_manager: MongoDatabaseManager, database_name: str, public_id: int, action: LogAction) -> bool:
    """Whether the object's log of that action is stored."""
    return database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name).count_documents(
        {'object_id': public_id, 'action': action.value}) == 1


def _create(rest_api, database_name: str) -> Any:
    """POSTs a new object of the seeded type as the tenant user."""
    return rest_api.post('/objects/', json={'type_id': TYPE_ID, 'active': True, 'author_id': AUTHOR_ID,
                                            'version': VERSION, 'fields': []}, **_as_tenant(rest_api, database_name))


@pytest.mark.usefixtures('unconfigured_portal')
class TestAnUnconfiguredPortalFailsNoWrite:
    """Every count-changing object write answers success, with its write and its log, and logs the skipped sync."""

    def test_the_create_answers_200_and_keeps_its_log(self, rest_api, database_manager, database_name,
                                                      caplog) -> None:
        """The CREATE log is written before the sync, and the sync cannot fail the request"""
        response = _create(rest_api, database_name)

        assert response.status_code == HTTPStatus.OK
        created: int = response.get_json()
        assert _stored(database_manager, database_name, created)
        assert _logged(database_manager, database_name, created, LogAction.CREATE)
        assert SKIPPED_MARKER in caplog.text

    def test_the_single_delete_answers_200(self, rest_api, database_manager, database_name, caplog) -> None:
        """The object is gone and the answer says so"""
        response = rest_api.delete(f'/objects/{SEEDED_IDS[0]}', **_as_tenant(rest_api, database_name))

        assert response.status_code == HTTPStatus.OK
        assert not _stored(database_manager, database_name, SEEDED_IDS[0])
        assert _logged(database_manager, database_name, SEEDED_IDS[0], LogAction.DELETE)
        assert SKIPPED_MARKER in caplog.text

    def test_the_bulk_delete_answers_200(self, rest_api, database_manager, database_name, caplog) -> None:
        """Every listed object is gone and acknowledged"""
        ids: str = ','.join(str(public_id) for public_id in SEEDED_IDS[1:])

        response = rest_api.delete(f'/objects/delete/{ids}', **_as_tenant(rest_api, database_name))

        assert response.status_code == HTTPStatus.OK
        assert sorted(response.get_json()['successfully']) == SEEDED_IDS[1:]
        assert not any(_stored(database_manager, database_name, public_id) for public_id in SEEDED_IDS[1:])
        assert SKIPPED_MARKER in caplog.text


class TestAConfiguredPortalIsAskedOncePerWrite:
    """The control: with a portal, every count-changing write reports once."""

    def test_the_create_reports(self, rest_api, database_name, portal: MagicMock) -> None:
        """One report, after the object exists"""
        assert _create(rest_api, database_name).status_code == HTTPStatus.OK
        portal.return_value.sync_config_items.assert_called_once()

    def test_the_bulk_delete_reports_once(self, rest_api, database_name, portal: MagicMock) -> None:
        """Once for the whole selection, not per object"""
        ids: str = ','.join(str(public_id) for public_id in SEEDED_IDS)

        assert rest_api.delete(f'/objects/delete/{ids}', **_as_tenant(rest_api, database_name)).status_code == \
            HTTPStatus.OK
        portal.return_value.sync_config_items.assert_called_once()

    def test_on_premise_nothing_is_reported(self, rest_api, monkeypatch, database_name) -> None:
        """The default app: no portal is even built"""
        portal = MagicMock(name='DgServicePortalManager')
        monkeypatch.setattr(config_item_sync, 'DgServicePortalManager', portal)

        response = rest_api.post('/objects/', json={'type_id': TYPE_ID, 'active': True, 'author_id': AUTHOR_ID,
                                                    'version': VERSION, 'fields': []})

        assert response.status_code == HTTPStatus.OK
        portal.assert_not_called()
        del database_name
