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
An OpenCelium route in hosted cloud mode when a concurrent request caches the same user first - over HTTP

The route checks the connection id against the user's cached subscription, seeding the cache from the Service Portal
on a miss. A concurrent request caches the user while this one waits on the portal (the write is made from inside the
portal stub). The seed writes only into an empty slot, so this request reads the concurrent entry - the one listing
the connection - and is served; before, its insert lost on the unique email index and the route answered a 500
"""
from collections.abc import Iterator
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.interface.rest_api.routes.open_celium_routes import oc_connection_routes
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.manager.system_manager.cached_user_manager import CachedUserManager
from cmdb.models.cached_user_model import CachedOcIdListKey, CachedSubscriptionKey, CachedUserKey, CmdbCachedUser
from cmdb.models.user_model import CmdbUser
from cmdb.security.license.license_constants import LicenseFeature

from tests.utils.cloud_mode import cloud_auth_header, enable_hosted_cloud_mode
# -------------------------------------------------------------------------------------------------------------------- #

TENANT_USER_ID: int = 9301
EMAIL: str = 'ftest_oc_race@acme.com'
CONNECTION_ID: int = 77
CONNECTION_TITLE: str = 'nightly-sync'
ADMIN_GROUP: int = 1


@pytest.fixture(name='tenant_user')
def fixture_tenant_user(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[None]:
    """A tenant user with an email in the test tenant database"""
    users: Any = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    users.delete_many({'public_id': TENANT_USER_ID})
    users.insert_one({
        'public_id': TENANT_USER_ID, 'user_name': EMAIL, 'email': EMAIL, 'active': True,
        'group_ids': [ADMIN_GROUP], 'database': database_name, 'registration_time': datetime.now(timezone.utc),
    })

    yield

    users.delete_many({'public_id': TENANT_USER_ID})


@pytest.fixture(name='cached_user_manager')
def fixture_cached_user_manager(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """A CachedUserManager on the test database's cache collection, built with its declared indexes"""
    collection: Any = database_manager.get_collection(CmdbCachedUser.COLLECTION, database_name)
    collection.delete_many({CachedUserKey.EMAIL.value: EMAIL})
    collection.create_indexes(CmdbCachedUser.get_index_keys())
    manager: CachedUserManager = CachedUserManager(database_manager)
    manager.db_name = database_name

    yield manager

    collection.delete_many({CachedUserKey.EMAIL.value: EMAIL})

    for index in CmdbCachedUser.get_index_keys():
        collection.drop_index(index.document['name'])


def _subscriber(database_name: str, connection_ids: list[int]) -> dict[str, Any]:
    """The portal's user document: one subscription on the tenant listing the given connection ids (as strings)"""
    return {
        CachedUserKey.EMAIL.value: EMAIL,
        CachedUserKey.SUBSCRIPTIONS.value: [{
            CachedSubscriptionKey.DATABASE.value: database_name,
            CachedSubscriptionKey.OPENCELIUM.value: {
                CachedOcIdListKey.CONNECTIONS.value: [str(oc_id) for oc_id in connection_ids],
            },
        }],
    }


@pytest.mark.usefixtures('tenant_user')
def test_a_seed_racing_a_concurrent_seed_is_served_from_the_first_entry(
        rest_api, monkeypatch: pytest.MonkeyPatch, database_manager: MongoDatabaseManager, database_name: str,
        cached_user_manager: CachedUserManager) -> None:
    """200 from the concurrent entry's connection list, and the user keeps one cache entry"""
    enable_hosted_cloud_mode(rest_api, monkeypatch, database_manager)
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.AUTOMATIONS)

    def _portal_answer(_email: str) -> dict[str, Any]:
        cached_user_manager.insert_cached_user(_subscriber(database_name, [CONNECTION_ID]))
        return _subscriber(database_name, [])

    portal: MagicMock = MagicMock(name='dg_sp_manager')
    portal.get_dg_sp_user_data.side_effect = _portal_answer
    connection_manager: MagicMock = MagicMock(name='oc_connection_manager')
    connection_manager.get_connection.return_value = {
        'connectionId': CONNECTION_ID, 'title': f'{database_name}_{CONNECTION_TITLE}',
    }
    monkeypatch.setattr(oc_connection_routes, 'DgServicePortalManager', lambda: portal)
    monkeypatch.setattr(oc_connection_routes, 'get_cached_user_manager', lambda: cached_user_manager)
    monkeypatch.setattr(oc_connection_routes, 'build_connection_manager', lambda _request_user: connection_manager)

    response: Any = rest_api.get(f'/open_celium/connections/{CONNECTION_ID}',
                                 environ_overrides=cloud_auth_header(rest_api, TENANT_USER_ID, database_name))

    assert response.status_code == HTTPStatus.OK
    assert database_manager.get_collection(CmdbCachedUser.COLLECTION, database_name)\
        .count_documents({CachedUserKey.EMAIL.value: EMAIL}) == 1
