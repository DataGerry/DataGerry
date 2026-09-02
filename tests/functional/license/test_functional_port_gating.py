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
Functional tests for Port Connectivity feature-gating over HTTP

The whole ``/ports`` surface is gated behind ``LicenseFeature.IPAM`` (decision D6): a CmdbType can not
declare ``uses_ports`` without that licence either, so an unlicensed installation has no ports to
read. Reads lock too - the gate is a blueprint guard that runs before the view.

These cases are also the regression guard for a trap in the wiring: ``gate_blueprint`` installs a
``before_request`` hook and Flask runs a blueprint's deferred setup at registration time, so gating a
blueprint that is *already registered* silently does nothing. This suite fails if the port blueprint is
ever registered before the gate loop
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.license_manager.active_license_manager import ActiveLicenseManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.object_model import CmdbObject
from cmdb.models.port_model import CmdbPort, PortKey, PortSide
from cmdb.models.type_model import CmdbType, FieldType, SectionType
from cmdb.security.license.license_constants import LicenseFeature
# -------------------------------------------------------------------------------------------------------------------- #

PORT_TYPE_ID: int = 9860
PORT_OBJECT_ID: int = 9861
PORT_ID: int = 9862

NAME_FIELD: str = 'dg-name'

PORTS_URL: str = '/ports'
PORT_URL: str = f'{PORTS_URL}/{PORT_ID}'
PORTS_OF_OBJECT_URL: str = f'{PORTS_URL}/object/{PORT_OBJECT_ID}'

GATED_READ_URLS: list[str] = [PORT_URL, PORTS_OF_OBJECT_URL]


def _port_type_doc() -> dict[str, Any]:
    """A port-bearing CmdbType, so the gate is what blocks - not a missing flag."""
    return {
        'public_id': PORT_TYPE_ID,
        'name': 'gating-switch',
        'label': 'Gating Switch',
        'author_id': 1,
        'active': True,
        'version': '1.0.0',
        'uses_ports': True,
        'selectable_as_parent': True,
        'global_template_ids': [],
        'fields': [{'type': FieldType.TEXT.value, 'name': NAME_FIELD, 'label': 'Name'}],
        'render_meta': {
            'icon': 'fa-cube',
            'externals': [],
            'sections': [{'type': SectionType.SECTION.value, 'name': 'main', 'label': 'Main',
                          'fields': [NAME_FIELD]}],
            'summary': {'fields': [NAME_FIELD]},
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
    }


@pytest.fixture(autouse=True)
def _no_active_license(database_manager: MongoDatabaseManager, database_name: str):
    """Guarantees the free (unlicensed) default by clearing the active-license store around each test"""
    database_manager.get_collection(ActiveLicenseManager.COLLECTION, database_name).delete_many({})
    yield
    database_manager.get_collection(ActiveLicenseManager.COLLECTION, database_name).delete_many({})


@pytest.fixture(name='seeded_port')
def fixture_seeded_port(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds a port-bearing type, an object of it and one port, so the gate is the only thing blocking."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    ports = database_manager.get_collection(CmdbPort.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': PORT_TYPE_ID})
        objects.delete_many({'public_id': PORT_OBJECT_ID})
        ports.delete_many({PortKey.PUBLIC_ID.value: PORT_ID})

    _purge()

    types.insert_one(_port_type_doc())
    objects.insert_one({
        'public_id': PORT_OBJECT_ID,
        'type_id': PORT_TYPE_ID,
        'active': True,
        'author_id': 1,
        'version': '1.0.0',
        'fields': [{'name': NAME_FIELD, 'value': 'switch-1', 'type': FieldType.TEXT.value}],
        'multi_data_sections': [],
    })
    ports.insert_one({
        PortKey.PUBLIC_ID.value: PORT_ID,
        PortKey.OBJECT_ID.value: PORT_OBJECT_ID,
        PortKey.SIDE.value: PortSide.SINGLE.value,
        PortKey.NAME.value: 'Gi0/1',
        PortKey.AUTHOR_ID.value: 1,
    })

    yield

    _purge()

# -------------------------------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize('url', GATED_READ_URLS)
@pytest.mark.usefixtures('seeded_port')
def test_port_read_routes_blocked_without_license(rest_api, url: str) -> None:
    """Every /ports read is blocked with 403 when IPAM is not licensed - reads lock too"""
    assert rest_api.get(url).status_code == HTTPStatus.FORBIDDEN


@pytest.mark.usefixtures('seeded_port')
def test_port_create_blocked_without_license(rest_api) -> None:
    """Creating a port is blocked before the view runs"""
    response = rest_api.post(f'{PORTS_URL}/', json={'object_id': PORT_OBJECT_ID, 'name': 'Gi0/2'})

    assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.usefixtures('seeded_port')
def test_port_update_blocked_without_license(rest_api) -> None:
    """Editing a port is blocked before the view runs"""
    response = rest_api.put(PORT_URL, json={'object_id': PORT_OBJECT_ID, 'name': 'renamed'})

    assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.usefixtures('seeded_port')
def test_port_delete_blocked_without_license(rest_api) -> None:
    """Deleting a port is blocked before the view runs"""
    assert rest_api.delete(PORT_URL).status_code == HTTPStatus.FORBIDDEN


@pytest.mark.parametrize('url', GATED_READ_URLS)
@pytest.mark.usefixtures('seeded_port')
def test_port_read_routes_reachable_once_licensed(rest_api, monkeypatch: pytest.MonkeyPatch,
                                                  url: str) -> None:
    """
    The same reads answer normally once IPAM is licensed

    Without this the 403s above would also pass on a surface that is broken for an entirely different
    reason.
    """
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.IPAM)

    assert rest_api.get(url).status_code == HTTPStatus.OK


@pytest.mark.usefixtures('seeded_port')
def test_the_gate_does_not_depend_on_the_object_existing(rest_api) -> None:
    """
    The blueprint guard runs BEFORE the view, so a missing target still answers 403, not 404

    That ordering is what makes the gate a real lock rather than an error-message difference.
    """
    assert rest_api.get(f'{PORTS_URL}/object/999999').status_code == HTTPStatus.FORBIDDEN
