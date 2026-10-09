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
Integration tests for the subscription teardown against a real MongoDB database

``DELETE /setup/subscriptions?database=<name>`` drops a database on the cluster. A throwaway database is created for
each test and the setup blueprint is mounted on a cloud-mode app with the real database manager. A Bearer request -
which verify_api_access passes through and nothing else on these routes validated - must leave the database in place;
the Service Portal's channel (Basic + ``x-api-key``, the portal's SUPER_ADMIN answer stubbed) drops it.

And only a DataGerry tenant database: the throwaway one is tenant-shaped (it holds ``framework.types``, the first
collection tenant creation makes); a database without it, the shared user cache and the process's own database are
refused and left in place
"""
import base64
import os
from http import HTTPStatus
from typing import Any

import pytest
from flask import Flask

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_constants import DG_CACHE_DB
from cmdb.models.type_model import CmdbType
from cmdb.interface import route_utils
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.routes.setup_routes.setup_routes import setup_blueprint
# -------------------------------------------------------------------------------------------------------------------- #

# One name per test process, so a parallel run on the same server cannot collide
THROWAWAY_DATABASE: str = f'itest_setup_drop_{os.getpid()}'
FOREIGN_DATABASE: str = f'itest_setup_foreign_{os.getpid()}'
PROCESS_DATABASE: str = f'itest_setup_process_{os.getpid()}'
SUBSCRIPTIONS_ROUTE: str = f'/setup/subscriptions?database={THROWAWAY_DATABASE}'


def _subscriptions_route(database: str) -> str:
    """The teardown route naming the given database"""
    return f'/setup/subscriptions?database={database}'

PORTAL_CREDENTIALS: str = base64.b64encode(b'portal@datagerry.com:portal-password').decode('ascii')
PORTAL_HEADERS: dict[str, str] = {'Authorization': f'Basic {PORTAL_CREDENTIALS}', 'x-api-key': 'portal-key'}


@pytest.fixture(name='throwaway_database')
def fixture_throwaway_database(database_manager: MongoDatabaseManager):
    """A tenant-shaped database (it holds framework.types), dropped afterwards whatever the test did"""
    client = database_manager.connector.client
    client[THROWAWAY_DATABASE][CmdbType.COLLECTION].insert_one({'public_id': 1})

    yield client

    client.drop_database(THROWAWAY_DATABASE)


@pytest.fixture(name='cloud_client')
def fixture_cloud_client(monkeypatch: pytest.MonkeyPatch, database_manager: MongoDatabaseManager):
    """A cloud-mode app carrying only the setup blueprint, with the portal's answer stubbed as SUPER_ADMIN"""
    app = Flask(__name__)
    app.cloud_mode = True
    app.local_mode = False
    app.database_manager = database_manager
    app.register_blueprint(setup_blueprint, url_prefix='/setup')

    portal_account: dict[str, Any] = {'api_level': ApiLevel.SUPER_ADMIN.value, 'subscriptions': []}
    monkeypatch.setattr(route_utils, 'check_user_in_service_portal', lambda *_args, **_kwargs: portal_account)

    return app.test_client()


@pytest.mark.parametrize('authorization', ['Bearer not-a-real-token', 'Bearer eyJhbGciOiJSUzI1NiJ9.e30.sig'],
                         ids=['garbage', 'jwt-shaped'])
def test_a_bearer_request_leaves_the_database_in_place(cloud_client, throwaway_database, authorization: str) -> None:
    """This request used to drop the database: verify_api_access let it through and nothing checked the token"""
    response = cloud_client.delete(SUBSCRIPTIONS_ROUTE, headers={'Authorization': authorization})

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert THROWAWAY_DATABASE in throwaway_database.list_database_names()


def test_the_portal_channel_drops_it(cloud_client, throwaway_database) -> None:
    """The contrast: Basic + x-api-key, held to SUPER_ADMIN by the portal check, is the teardown"""
    response = cloud_client.delete(SUBSCRIPTIONS_ROUTE, headers=PORTAL_HEADERS)

    assert response.status_code == HTTPStatus.OK
    assert response.get_json() is True
    assert THROWAWAY_DATABASE not in throwaway_database.list_database_names()


def test_a_portal_account_below_super_admin_is_refused(
        cloud_client, throwaway_database, monkeypatch: pytest.MonkeyPatch) -> None:
    """The level check runs for the portal's channel - an ADMIN account cannot tear down"""
    admin_account: dict[str, Any] = {'api_level': ApiLevel.ADMIN.value, 'subscriptions': []}
    monkeypatch.setattr(route_utils, 'check_user_in_service_portal', lambda *_args, **_kwargs: admin_account)

    response = cloud_client.delete(SUBSCRIPTIONS_ROUTE, headers=PORTAL_HEADERS)

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert THROWAWAY_DATABASE in throwaway_database.list_database_names()


@pytest.fixture(name='foreign_database')
def fixture_foreign_database(database_manager: MongoDatabaseManager):
    """Another application's database on the same cluster: data, but no DataGerry collections"""
    client = database_manager.connector.client
    client[FOREIGN_DATABASE]['orders'].insert_one({'order': 1})

    yield client

    client.drop_database(FOREIGN_DATABASE)


def test_a_database_datagerry_did_not_create_is_refused(cloud_client, foreign_database) -> None:
    """The portal's channel, SUPER_ADMIN - and still 400: only a tenant database may be torn down"""
    response = cloud_client.delete(_subscriptions_route(FOREIGN_DATABASE), headers=PORTAL_HEADERS)

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert FOREIGN_DATABASE in foreign_database.list_database_names()
    assert foreign_database[FOREIGN_DATABASE]['orders'].count_documents({}) == 1


def test_the_shared_user_cache_is_refused(cloud_client, database_manager: MongoDatabaseManager) -> None:
    """Every tenant's cached logins live there"""
    client = database_manager.connector.client
    client[DG_CACHE_DB]['itest_probe'].insert_one({'probe': True})
    try:
        response = cloud_client.delete(_subscriptions_route(DG_CACHE_DB), headers=PORTAL_HEADERS)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert DG_CACHE_DB in client.list_database_names()
    finally:
        client[DG_CACHE_DB].drop_collection('itest_probe')


def test_the_process_database_is_refused(monkeypatch: pytest.MonkeyPatch, mongodb_parameters: tuple) -> None:
    """
    The database the server runs on is never a teardown target, even when it is tenant-shaped

    A second database manager is pointed at a throwaway, tenant-shaped database as its process database - so the
    name rule alone decides, and a broken guard would drop only the throwaway, never the suite's own database
    """
    host, port, _database = mongodb_parameters
    process_dbm = MongoDatabaseManager(host, port, PROCESS_DATABASE)
    client = process_dbm.connector.client
    client[PROCESS_DATABASE][CmdbType.COLLECTION].insert_one({'public_id': 1})
    try:
        app = Flask(__name__)
        app.cloud_mode = True
        app.local_mode = False
        app.database_manager = process_dbm
        app.register_blueprint(setup_blueprint, url_prefix='/setup')
        portal_account: dict[str, Any] = {'api_level': ApiLevel.SUPER_ADMIN.value, 'subscriptions': []}
        monkeypatch.setattr(route_utils, 'check_user_in_service_portal', lambda *_args, **_kwargs: portal_account)

        response = app.test_client().delete(_subscriptions_route(PROCESS_DATABASE), headers=PORTAL_HEADERS)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert PROCESS_DATABASE in client.list_database_names()
    finally:
        client.drop_database(PROCESS_DATABASE)


def test_the_slash_form_drops_nothing(cloud_client, throwaway_database) -> None:
    """'/setup/subscriptions/' is a 404 - the portal's spelling is the only one - and the database stays"""
    response = cloud_client.delete(f'/setup/subscriptions/?database={THROWAWAY_DATABASE}', headers=PORTAL_HEADERS)

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert THROWAWAY_DATABASE in throwaway_database.list_database_names()

