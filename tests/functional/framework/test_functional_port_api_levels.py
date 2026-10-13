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
Port Connectivity through the hosted cloud's API key (HTTP Basic + ``x-api-key``)

The port, connection, bulk, preview and interface-link routes are ``ApiLevel.ADMIN``: an ADMIN-level key works the
whole surface end to end - creates ports one by one and in bulk, reads them, their overview and cabling, connects two
devices with a cable, reads and deletes the connection, updates and deletes a port. A key below ADMIN is refused on
every route with the level's 403, and writes nothing. The rights still decide inside the level: the account's user
is in the admin group here. The portal is stubbed
"""
import base64
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.interface import route_utils
from cmdb.interface.route_utils import API_KEY_HEADER
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.object_model import CmdbObject
from cmdb.models.port_connection_model import CmdbPortConnection, ConnectionType, PortConnectionKey
from cmdb.models.port_model import CmdbPort, PortKey
from cmdb.models.type_model import CmdbType, FieldType, SectionType
from cmdb.models.user_model import CmdbUser
from cmdb.framework.port.name_syntax_constants import PortDeviceKind
from cmdb.security.license.license_constants import LicenseFeature
from tests.utils.cloud_mode import enable_hosted_cloud_mode
# -------------------------------------------------------------------------------------------------------------------- #

PORTS_URL: str = '/ports'
CONNECTIONS_URL: str = '/port_connections'

USER_ID: int = 93991
EMAIL: str = 'cloud-port-levels@x.io'
PASSWORD: str = 'portal-password'
API_KEY: str = 'subscription-key'
LEVEL_REFUSAL: str = 'No permission for this action!'
ADMIN_GROUP_ID: int = 1
API_KEY_ENVIRON: str = f'HTTP_{API_KEY_HEADER.upper().replace("-", "_")}'

PORT_TYPE_ID: int = 93990
SERVER_ID: int = 93992
SWITCH_ID: int = 93993
NAME_FIELD: str = 'dg-name'
BULK_COUNT: int = 3


def _type_doc() -> dict[str, Any]:
    """A port-bearing CmdbType"""
    return {
        'public_id': PORT_TYPE_ID, 'name': f'port-api-type-{PORT_TYPE_ID}', 'label': 'Port API Type', 'author_id': 1,
        'active': True, 'version': '1.0.0', 'uses_ports': True, 'selectable_as_parent': True,
        'global_template_ids': [],
        'fields': [{'type': FieldType.TEXT.value, 'name': NAME_FIELD, 'label': 'Name'}],
        'render_meta': {'icon': 'fa-cube', 'externals': [], 'summary': {'fields': [NAME_FIELD]},
                        'sections': [{'type': SectionType.SECTION.value, 'name': 'main', 'label': 'Main',
                                      'fields': [NAME_FIELD]}]},
        'acl': {'activated': False, 'groups': {'includes': None}},
    }


def _object_doc(public_id: int) -> dict[str, Any]:
    """A device of the port-bearing type"""
    return {'public_id': public_id, 'type_id': PORT_TYPE_ID, 'active': True, 'author_id': 1, 'version': '1.0.0',
            'fields': [{'name': NAME_FIELD, 'value': f'device-{public_id}', 'type': FieldType.TEXT.value}],
            'multi_data_sections': []}


def _portal_answer(database: str, level: ApiLevel) -> dict[str, Any]:
    """The ServicePortal's answer: a subscription on the test database at the given level"""
    return {
        'email': EMAIL, 'user_name': 'cloud-port-levels', 'password': PASSWORD, 'api_level': level,
        'subscriptions': [{'id': 1, 'name': 'sub', 'database': database, 'api_level': level,
                           'config_item_limit': 100}],
    }


@pytest.fixture(name='seeded', autouse=True)
def fixture_seeded(database_manager: MongoDatabaseManager, database_name: str, monkeypatch: pytest.MonkeyPatch):
    """IPAM licensed, the type and two devices; every port and connection of them removed around each test"""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.IPAM)
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    ports = database_manager.get_collection(CmdbPort.COLLECTION, database_name)
    connections = database_manager.get_collection(CmdbPortConnection.COLLECTION, database_name)
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)

    def _purge() -> None:
        port_ids = [port[PortKey.PUBLIC_ID.value]
                    for port in ports.find({PortKey.OBJECT_ID.value: {'$in': [SERVER_ID, SWITCH_ID]}})]
        connections.delete_many({PortConnectionKey.ENDPOINTS.value: {'$in': port_ids}})
        ports.delete_many({PortKey.OBJECT_ID.value: {'$in': [SERVER_ID, SWITCH_ID]}})
        objects.delete_many({'public_id': {'$in': [SERVER_ID, SWITCH_ID]}})
        types.delete_many({'public_id': PORT_TYPE_ID})
        users.delete_many({'public_id': USER_ID})

    _purge()
    types.insert_one(_type_doc())
    objects.insert_many([_object_doc(SERVER_ID), _object_doc(SWITCH_ID)])
    users.insert_one({
        'public_id': USER_ID, 'user_name': 'cloud-port-levels', 'email': EMAIL, 'active': True,
        'group_id': ADMIN_GROUP_ID, 'database': database_name, 'api_level': ApiLevel.ADMIN,
        'registration_time': datetime.now(timezone.utc),
    })

    yield ports, connections

    _purge()


def _cloud(rest_api, monkeypatch: pytest.MonkeyPatch, database_manager: MongoDatabaseManager, database_name: str,
           level: ApiLevel) -> dict[str, str]:
    """Hosted-cloud mode with a portal answering at `level`; the API-key request environ"""
    enable_hosted_cloud_mode(rest_api, monkeypatch, database_manager)
    answer: dict[str, Any] = _portal_answer(database_name, level)
    monkeypatch.setattr(route_utils, 'check_user_in_service_portal', lambda *_args, **_kwargs: answer)
    basic: str = base64.b64encode(f'{EMAIL}:{PASSWORD}'.encode('utf-8')).decode('utf-8')

    return {'HTTP_AUTHORIZATION': f'Basic {basic}', API_KEY_ENVIRON: API_KEY}


@pytest.fixture(name='admin_key')
def fixture_admin_key(rest_api, monkeypatch, database_manager, database_name) -> dict[str, str]:
    """An ADMIN-level API key"""
    return _cloud(rest_api, monkeypatch, database_manager, database_name, ApiLevel.ADMIN)


@pytest.fixture(name='low_key')
def fixture_low_key(rest_api, monkeypatch, database_manager, database_name) -> dict[str, str]:
    """An API key below ADMIN"""
    return _cloud(rest_api, monkeypatch, database_manager, database_name, ApiLevel.NO_API)


class TestAnAdminLevelKey:
    """The whole surface, end to end"""

    def test_ports_are_created_read_updated_and_deleted(self, rest_api, admin_key, seeded) -> None:
        """Single create, list, overview, cabling, preview, bulk create, update, delete"""
        ports, _connections = seeded
        created = rest_api.post(f'{PORTS_URL}/', json={'object_id': SERVER_ID, 'name': 'eth0'},
                                environ_overrides=admin_key)
        assert created.status_code == HTTPStatus.CREATED, created.get_json()
        port_id: int = created.get_json()['result_id']

        for url in (f'{PORTS_URL}/{port_id}', f'{PORTS_URL}/object/{SERVER_ID}',
                    f'{PORTS_URL}/object/{SERVER_ID}/overview', f'{PORTS_URL}/object/{SERVER_ID}/cabling',
                    f'{PORTS_URL}/{port_id}/cabling'):
            assert rest_api.get(url, environ_overrides=admin_key).status_code == HTTPStatus.OK, url

        bulk_body = {'device_kind': PortDeviceKind.STANDARD.value, 'syntax': 'Gi0/{n}', 'count': BULK_COUNT}
        preview = rest_api.post(f'{PORTS_URL}/object/{SWITCH_ID}/name_preview', json=bulk_body,
                                environ_overrides=admin_key)
        assert preview.status_code == HTTPStatus.OK, preview.get_json()
        bulk = rest_api.post(f'{PORTS_URL}/object/{SWITCH_ID}/bulk', json=bulk_body, environ_overrides=admin_key)
        assert bulk.status_code in (HTTPStatus.OK, HTTPStatus.CREATED), bulk.get_json()
        assert ports.count_documents({PortKey.OBJECT_ID.value: SWITCH_ID}) == BULK_COUNT

        updated = rest_api.put(f'{PORTS_URL}/{port_id}', json={'object_id': SERVER_ID, 'name': 'eth1'},
                               environ_overrides=admin_key)
        assert updated.status_code == HTTPStatus.ACCEPTED, updated.get_json()
        assert rest_api.delete(f'{PORTS_URL}/{port_id}', environ_overrides=admin_key).status_code == \
            HTTPStatus.ACCEPTED
        assert ports.count_documents({PortKey.PUBLIC_ID.value: port_id}) == 0

    def test_two_devices_are_cabled_and_uncabled(self, rest_api, admin_key, seeded) -> None:
        """Create, read by id / port / object, delete a CABLE connection"""
        _ports, connections = seeded
        server_port: int = rest_api.post(f'{PORTS_URL}/', json={'object_id': SERVER_ID, 'name': 'eth0'},
                                         environ_overrides=admin_key).get_json()['result_id']
        switch_port: int = rest_api.post(f'{PORTS_URL}/', json={'object_id': SWITCH_ID, 'name': 'Gi0/1'},
                                         environ_overrides=admin_key).get_json()['result_id']

        created = rest_api.post(f'{CONNECTIONS_URL}/', environ_overrides=admin_key, json={
            'endpoints': [server_port, switch_port], 'connection_type': ConnectionType.CABLE.value,
        })
        assert created.status_code == HTTPStatus.CREATED, created.get_json()
        connection_id: int = created.get_json()['result_id']

        for url in (f'{CONNECTIONS_URL}/{connection_id}', f'{CONNECTIONS_URL}/port/{server_port}',
                    f'{CONNECTIONS_URL}/object/{SERVER_ID}'):
            assert rest_api.get(url, environ_overrides=admin_key).status_code == HTTPStatus.OK, url

        deleted = rest_api.delete(f'{CONNECTIONS_URL}/{connection_id}', environ_overrides=admin_key)
        assert deleted.status_code == HTTPStatus.ACCEPTED, deleted.get_json()
        assert connections.count_documents({PortConnectionKey.PUBLIC_ID.value: connection_id}) == 0


class TestAKeyBelowAdmin:
    """Refused by the level, before any right is asked"""

    @pytest.mark.parametrize('method, url', [
        ('get', f'{PORTS_URL}/object/{SERVER_ID}'),
        ('get', f'{PORTS_URL}/object/{SERVER_ID}/overview'),
        ('post', f'{PORTS_URL}/'),
        ('post', f'{PORTS_URL}/object/{SERVER_ID}/bulk'),
        ('post', f'{PORTS_URL}/object/{SERVER_ID}/name_preview'),
        ('get', f'{PORTS_URL}/interface_links/dangling'),
        ('get', f'{CONNECTIONS_URL}/object/{SERVER_ID}'),
        ('post', f'{CONNECTIONS_URL}/'),
    ])
    def test_every_route_is_403_and_writes_nothing(self, rest_api, low_key, seeded, method: str, url: str) -> None:
        """The level's refusal"""
        ports, _connections = seeded

        response = getattr(rest_api, method)(url, json={'object_id': SERVER_ID, 'name': 'eth0'},
                                             environ_overrides=low_key)

        assert (response.status_code, response.get_json()['message']) == (HTTPStatus.FORBIDDEN, LEVEL_REFUSAL)
        assert ports.count_documents({PortKey.OBJECT_ID.value: SERVER_ID}) == 0
