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
Functional smoke for the ``/settings/system`` REST routes.

Covers the general system-information endpoint and the config-information endpoint, including the
section serialization (the harness itself runs config-less, so the sections are stubbed) and the
failure -> 500 mappings of both routes. Pinned besides:

  - both routes ask for ``base.system.view``: a group without it - the seeded ``user`` group included - is a 403
    naming the right, a group holding only it reads both
  - in cloud mode the system information leaves out the host process's uptime and command line
  - the database version is the one the updater recorded; an unreadable one is ``UNKNOWN_DB_VERSION``, any other
    failure a 500
"""
from datetime import datetime, timezone
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import SettingsManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID, USER_GROUP_ID
from cmdb.models.user_model import CmdbUser
from cmdb.interface.rest_api.routes.settings_routes.system_constants import (
    SYSTEM_VIEW_RIGHT,
    UNKNOWN_DB_VERSION,
    UPDATER_SETTINGS_SECTION,
    SystemInfoKey,
)
from cmdb.interface import route_utils
from cmdb.errors.database import DocumentGetError
from tests.utils.cloud_mode import cloud_auth_header, enable_hosted_cloud_mode
# -------------------------------------------------------------------------------------------------------------------- #

SYSTEM_ROUTES: str = 'cmdb.interface.rest_api.routes.settings_routes.system_routes'
INFO_URL: str = '/settings/system/'
CONFIG_URL: str = '/settings/system/config/'

# What `APIBlueprint.protect` answers a user whose group lacks the route's right
RIGHT_REFUSAL: str = 'User has not the required right {right}'

RIGHTLESS_GROUP_ID: int = 88501
VIEWER_GROUP_ID: int = 88502
RIGHTLESS_USER_ID: int = 88511
VIEWER_USER_ID: int = 88512
DEFAULT_USER_ID: int = 88513

ALL_KEYS: set[str] = {key.value for key in SystemInfoKey}
CLOUD_KEYS: set[str] = {SystemInfoKey.TITLE.value, SystemInfoKey.VERSION.value, SystemInfoKey.DB_VERSION.value}


class TestSystemInformation:
    """GET /settings/system/ returns basic DataGerry system information."""

    def test_returns_system_information(self, rest_api) -> None:
        """The response carries the expected system-information keys."""
        response = rest_api.get('/settings/system/')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        for key in ('title', 'version', 'db_version', 'runtime', 'starting_parameters'):
            assert key in body

    def test_manager_failure_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected failure obtaining the settings manager is reported as 500."""
        original = ManagerProvider.get_manager

        def _selective(manager_type, request_user):
            if manager_type == ManagerType.SETTINGS:
                raise RuntimeError('boom')
            return original(manager_type, request_user)

        monkeypatch.setattr(ManagerProvider, 'get_manager', _selective)

        assert rest_api.get('/settings/system/').status_code == HTTPStatus.INTERNAL_SERVER_ERROR


class TestConfigInformation:
    """GET /settings/system/config/ returns the config-file information."""

    def test_returns_config_information(self, rest_api) -> None:
        """The response carries the config path key and a properties list.

        In config-less mode (the test harness) 'path' is None (regression for B7: the route used to
        read ssc.config_file directly, which is unset config-less -> AttributeError -> 500).
        """
        response = rest_api.get('/settings/system/config/')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert 'path' in body
        assert isinstance(body['properties'], list)

    def test_sections_are_serialized_as_key_value_pairs(self, rest_api, monkeypatch) -> None:
        """Each config section is emitted as [name, [[key, value], ...]] in reader order."""
        reader = SimpleNamespace(
            config_file='/etc/cmdb.conf',
            get_sections=lambda: ['Database', 'WebServer'],
            get_all_values_from_section=lambda section: (
                {'host': 'localhost', 'port': '27017'} if section == 'Database' else {'port': '4000'}
            ),
        )
        monkeypatch.setattr(f'{SYSTEM_ROUTES}.SystemConfigReader', lambda *_a, **_k: reader)

        body = rest_api.get('/settings/system/config/').get_json()

        assert body['path'] == '/etc/cmdb.conf'
        assert body['properties'] == [
            ['Database', [['host', 'localhost'], ['port', '27017']]],
            ['WebServer', [['port', '4000']]],
        ]

    def test_reader_failure_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected failure reading the configuration is reported as 500."""
        def _boom(*_args, **_kwargs):
            raise RuntimeError('boom')

        monkeypatch.setattr(f'{SYSTEM_ROUTES}.SystemConfigReader', _boom)

        assert rest_api.get('/settings/system/config/').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

# ---------------------------------------------------- the right ----------------------------------------------------- #

def _insert_user(database_manager: MongoDatabaseManager, database_name: str, user_id: int,
                 group_id: int) -> CmdbUser:
    """Stores an active user in ``group_id`` and answers the model the test client sends as"""
    user_name: str = f'system-route-{user_id}'
    database_manager.get_collection(CmdbUser.COLLECTION, database_name).insert_one({
        'public_id': user_id, 'user_name': user_name, 'active': True, 'group_id': group_id,
        'registration_time': datetime.now(timezone.utc),
    })

    return CmdbUser(public_id=user_id, user_name=user_name, active=True, group_id=group_id)


@pytest.fixture(name='users')
def fixture_users(database_manager: MongoDatabaseManager, database_name: str):
    """A user with no right, one holding only the system view right, and a member of the seeded user group"""
    groups = database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)

    def _purge() -> None:
        groups.delete_many({'public_id': {'$in': [RIGHTLESS_GROUP_ID, VIEWER_GROUP_ID]}})
        users.delete_many({'public_id': {'$in': [RIGHTLESS_USER_ID, VIEWER_USER_ID, DEFAULT_USER_ID]}})

    _purge()
    groups.insert_many([
        {'public_id': RIGHTLESS_GROUP_ID, 'name': 'system-route-rightless', 'label': 'No rights', 'rights': []},
        {'public_id': VIEWER_GROUP_ID, 'name': 'system-route-viewers', 'label': 'System viewers',
         'rights': [SYSTEM_VIEW_RIGHT]},
    ])
    yield {
        'rightless': _insert_user(database_manager, database_name, RIGHTLESS_USER_ID, RIGHTLESS_GROUP_ID),
        'viewer': _insert_user(database_manager, database_name, VIEWER_USER_ID, VIEWER_GROUP_ID),
        'default': _insert_user(database_manager, database_name, DEFAULT_USER_ID, USER_GROUP_ID),
    }
    _purge()


class TestTheRight:
    """Both routes ask for base.system.view"""

    @pytest.mark.parametrize('url', [INFO_URL, CONFIG_URL], ids=['information', 'config'])
    @pytest.mark.parametrize('who', ['rightless', 'default'])
    def test_without_it_the_route_is_a_403_naming_it(self, rest_api, users: dict[str, CmdbUser], who: str,
                                                     url: str) -> None:
        """The seeded user group does not hold it either - the footer reads the version from GET /rest/"""
        response = rest_api.get(url, user=users[who])

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.get_json()['message'] == RIGHT_REFUSAL.format(right=SYSTEM_VIEW_RIGHT)
        assert 'starting_parameters' not in response.get_data(as_text=True)

    @pytest.mark.parametrize('url', [INFO_URL, CONFIG_URL], ids=['information', 'config'])
    def test_the_right_alone_is_enough(self, rest_api, users: dict[str, CmdbUser], url: str) -> None:
        """Nothing else is needed"""
        assert rest_api.get(url, user=users['viewer']).status_code == HTTPStatus.OK

    def test_on_premise_every_key_is_answered(self, rest_api, users: dict[str, CmdbUser]) -> None:
        """Including the uptime and the command line"""
        assert set(rest_api.get(INFO_URL, user=users['viewer']).get_json()) == ALL_KEYS

# ---------------------------------------------------- cloud mode ---------------------------------------------------- #

CLOUD_USER_ID: int = 88521
CLOUD_EMAIL: str = 'system-route-cloud@x.io'


@pytest.fixture(name='cloud_tenant_admin')
def fixture_cloud_tenant_admin(rest_api, monkeypatch: pytest.MonkeyPatch, database_manager: MongoDatabaseManager,
                               database_name: str):
    """A hosted-cloud app and a tenant admin stored in the test database, accepted by a stubbed portal"""
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    users.delete_many({'public_id': CLOUD_USER_ID})
    users.insert_one({
        'public_id': CLOUD_USER_ID, 'user_name': 'system-route-cloud', 'email': CLOUD_EMAIL, 'active': True,
        'group_id': ADMIN_GROUP_ID, 'database': database_name, 'api_level': 3,
        'registration_time': datetime.now(timezone.utc),
    })
    portal: dict[str, Any] = {
        'email': CLOUD_EMAIL, 'user_name': 'system-route-cloud', 'api_level': 3,
        'subscriptions': [{'id': 1, 'name': 'sub', 'database': database_name, 'api_level': 3,
                           'config_item_limit': 100}],
    }
    enable_hosted_cloud_mode(rest_api, monkeypatch, database_manager)
    monkeypatch.setattr(route_utils, 'check_user_in_service_portal', lambda *_args, **_kwargs: portal)
    yield cloud_auth_header(rest_api, CLOUD_USER_ID, database_name)
    users.delete_many({'public_id': CLOUD_USER_ID})


def test_in_cloud_mode_the_host_process_is_left_out(rest_api, cloud_tenant_admin: dict[str, str]) -> None:
    """The uptime and the command line describe the host every tenant shares - even its admin does not get them"""
    response = rest_api.get(INFO_URL, environ_overrides=cloud_tenant_admin)

    assert response.status_code == HTTPStatus.OK
    assert set(response.get_json()) == CLOUD_KEYS

# -------------------------------------------------- the db version -------------------------------------------------- #

def test_the_db_version_is_the_one_the_updater_recorded(rest_api, database_manager: MongoDatabaseManager,
                                                        database_name: str) -> None:
    """Read from the tenant's settings"""
    section: dict[str, Any] | None = database_manager.get_collection(SettingsManager.COLLECTION, database_name)\
        .find_one({'_id': UPDATER_SETTINGS_SECTION})
    expected: Any = (section or {}).get(SystemInfoKey.VERSION.value, UNKNOWN_DB_VERSION)

    assert rest_api.get(INFO_URL).get_json()[SystemInfoKey.DB_VERSION.value] == expected


def test_an_unreadable_db_version_is_unknown(rest_api, monkeypatch) -> None:
    """A failed settings read does not fail the request"""
    def _fail(*_args: Any, **_kwargs: Any) -> None:
        raise DocumentGetError('down')

    monkeypatch.setattr(SettingsManager, 'get_all_values_from_section', _fail)

    response = rest_api.get(INFO_URL)

    assert response.status_code == HTTPStatus.OK
    assert response.get_json()[SystemInfoKey.DB_VERSION.value] == UNKNOWN_DB_VERSION


def test_any_other_version_failure_is_a_500(rest_api, monkeypatch) -> None:
    """A defect is no longer read as 'unknown'"""
    def _fail(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError('boom')

    monkeypatch.setattr(SettingsManager, 'get_all_values_from_section', _fail)

    assert rest_api.get(INFO_URL).status_code == HTTPStatus.INTERNAL_SERVER_ERROR
