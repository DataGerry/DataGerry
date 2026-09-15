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

The whole ``/ports`` and ``/port_connections`` surface is gated behind ``LicenseFeature.IPAM``
(decision D6): a CmdbType can not declare ``uses_ports`` without that licence either, so an unlicensed
installation has no ports to read and nothing to connect. Reads lock too - the gate is a blueprint
guard that runs before the view.

The CABLE SpecialType - the optional Cable CI a connection may reference - is gated the same way, and
through a different mechanism: it is a member of ``SpecialType.get_license_gated_types``, so the guard
sits on the ordinary ``/types`` write rather than on a blueprint of its own.

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
from cmdb.models.special_type_model.cable_constants import CableField, CableSection
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model import CmdbType, FieldType, SectionType, TypeSchemaKey
from cmdb.security.license.license_constants import LicenseFeature
# -------------------------------------------------------------------------------------------------------------------- #

PORT_TYPE_ID: int = 9860
PORT_OBJECT_ID: int = 9861
PORT_ID: int = 9862

NAME_FIELD: str = 'dg-name'

PORTS_URL: str = '/ports'
PORT_URL: str = f'{PORTS_URL}/{PORT_ID}'
PORTS_OF_OBJECT_URL: str = f'{PORTS_URL}/object/{PORT_OBJECT_ID}'

LINKS_URL: str = f'{PORTS_URL}/interface_links'
LINK_ID: int = 9864

CONNECTIONS_URL: str = '/port_connections'
CONNECTION_ID: int = 9863
CONNECTION_URL: str = f'{CONNECTIONS_URL}/{CONNECTION_ID}'
CONNECTIONS_OF_PORT_URL: str = f'{CONNECTIONS_URL}/port/{PORT_ID}'

GATED_READ_URLS: list[str] = [PORT_URL, PORTS_OF_OBJECT_URL]

# The connection reads answer 404 once licensed (nothing is seeded), so they are listed apart from the
# port reads above - what matters here is only that they are 403 while the licence is missing
GATED_CONNECTION_READ_URLS: list[str] = [CONNECTION_URL, CONNECTIONS_OF_PORT_URL]

# The port <-> interface link surface shares the /ports prefix but is its own blueprint, so it needs its
# own gate - and its own regression guard for the registration-order trap
PREVIEW_URL: str = f'{PORTS_URL}/object/{PORT_OBJECT_ID}/name_preview'
BULK_URL: str = f'{PORTS_URL}/object/{PORT_OBJECT_ID}/bulk'

GATED_LINK_READ_URLS: list[str] = [
    f'{LINKS_URL}/{LINK_ID}',
    f'{LINKS_URL}/dangling',
    f'{PORTS_URL}/{PORT_ID}/interface_links/',
]


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


TYPES_URL: str = '/types'
CABLE_TYPE_ID: int = 9865


def _cable_type_payload() -> dict[str, Any]:
    """A minimal CABLE SpecialType payload - enough for the license guard to read the marker"""
    return {
        'public_id': CABLE_TYPE_ID,
        'name': 'gating-cable',
        'label': 'Gating Cable',
        'author_id': 1,
        'active': True,
        'version': '1.0.0',
        TypeSchemaKey.SPECIAL_TYPE.value: SpecialType.CABLE.value,
        'fields': [
            {'type': FieldType.TEXT.value, 'name': CableField.NAME.value, 'label': 'Cable name'},
        ],
        'render_meta': {
            'icon': 'fas fa-plug',
            'externals': [],
            'sections': [{
                'type': SectionType.SECTION.value,
                'name': CableSection.INFORMATION.value,
                'label': 'Information',
                'fields': [CableField.NAME.value],
            }],
            'summary': {'fields': [CableField.NAME.value]},
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
    }


@pytest.fixture(name='clean_cable_type')
def fixture_clean_cable_type(database_manager: MongoDatabaseManager, database_name: str):
    """Removes the seeded Cable type around each test - a SpecialType exists at most once"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    types.delete_many({'public_id': CABLE_TYPE_ID})

    yield

    types.delete_many({'public_id': CABLE_TYPE_ID})


# -------------------------------------------------------------------------------------------------------------------- #
#                                 the /port_connections surface, blocked unlicensed                                    #
# -------------------------------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize('url', GATED_CONNECTION_READ_URLS)
@pytest.mark.usefixtures('seeded_port')
def test_connection_read_routes_blocked_without_license(rest_api, url: str) -> None:
    """Every /port_connections read is blocked with 403 when IPAM is not licensed - reads lock too"""
    assert rest_api.get(url).status_code == HTTPStatus.FORBIDDEN


@pytest.mark.usefixtures('seeded_port')
def test_connection_create_blocked_without_license(rest_api) -> None:
    """Creating a connection is blocked before the view runs"""
    response = rest_api.post(f'{CONNECTIONS_URL}/', json={
        'endpoints': [PORT_ID, PORT_ID + 1], 'connection_type': 'CABLE',
    })

    assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.usefixtures('seeded_port')
def test_connection_update_blocked_without_license(rest_api) -> None:
    """Editing a connection is blocked before the view runs"""
    response = rest_api.put(CONNECTION_URL, json={'cable_name': 'Patch 1'})

    assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.usefixtures('seeded_port')
def test_connection_delete_blocked_without_license(rest_api) -> None:
    """Deleting a connection is blocked before the view runs"""
    assert rest_api.delete(CONNECTION_URL).status_code == HTTPStatus.FORBIDDEN


@pytest.mark.parametrize('url', GATED_CONNECTION_READ_URLS)
@pytest.mark.usefixtures('seeded_port')
def test_connection_read_routes_reachable_once_licensed(rest_api, monkeypatch: pytest.MonkeyPatch,
                                                        url: str) -> None:
    """
    The same reads stop being FORBIDDEN once IPAM is licensed

    They answer 404 rather than 200 because nothing is seeded - what this asserts is that the
    blueprint guard let the request reach the view at all, which is the registration-order trap the
    port cases above guard for their own blueprint.
    """
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.IPAM)

    assert rest_api.get(url).status_code != HTTPStatus.FORBIDDEN


# -------------------------------------------------------------------------------------------------------------------- #
#                              the port <-> interface links, blocked unlicensed                                        #
# -------------------------------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize('url', GATED_LINK_READ_URLS)
@pytest.mark.usefixtures('seeded_port')
def test_interface_link_read_routes_blocked_without_license(rest_api, url: str) -> None:
    """Every interface-link read is blocked with 403 when IPAM is not licensed - the report included"""
    assert rest_api.get(url).status_code == HTTPStatus.FORBIDDEN


@pytest.mark.usefixtures('seeded_port')
def test_interface_link_create_blocked_without_license(rest_api) -> None:
    """Creating a link is blocked before the view runs"""
    response = rest_api.post(f'{PORTS_URL}/{PORT_ID}/interface_links/', json={
        'interface_object_id': PORT_OBJECT_ID, 'interface_multi_data_id': 1,
        'relation_type': 'PHYSICAL',
    })

    assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.usefixtures('seeded_port')
def test_interface_link_update_blocked_without_license(rest_api) -> None:
    """Editing a link is blocked before the view runs"""
    response = rest_api.put(f'{LINKS_URL}/{LINK_ID}', json={'relation_type': 'BOND'})

    assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.usefixtures('seeded_port')
def test_interface_link_delete_blocked_without_license(rest_api) -> None:
    """Deleting a link is blocked before the view runs"""
    assert rest_api.delete(f'{LINKS_URL}/{LINK_ID}').status_code == HTTPStatus.FORBIDDEN


@pytest.mark.parametrize('url', GATED_LINK_READ_URLS)
@pytest.mark.usefixtures('seeded_port')
def test_interface_link_read_routes_reachable_once_licensed(rest_api, monkeypatch: pytest.MonkeyPatch,
                                                            url: str) -> None:
    """
    The same reads stop being FORBIDDEN once IPAM is licensed

    This is the registration-order guard for the SECOND blueprint mounted on /ports: gating a blueprint
    that is already registered silently does nothing, and the port cases above would not notice.
    """
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.IPAM)

    assert rest_api.get(url).status_code != HTTPStatus.FORBIDDEN


@pytest.mark.usefixtures('seeded_port')
def test_name_preview_blocked_without_license(rest_api) -> None:
    """
    The preview is gated too, even though it writes nothing

    It reports which port names an object already carries, which is the same information the ports
    list gives - and it previews an operation the licence blocks anyway.
    """
    response = rest_api.post(PREVIEW_URL, json={
        'device_kind': 'STANDARD', 'syntax': 'Gi0/{n}', 'count': 2,
    })

    assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.usefixtures('seeded_port')
def test_name_preview_reachable_once_licensed(rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    The registration-order guard for the THIRD blueprint mounted on /ports

    Gating a blueprint that is already registered silently does nothing, and neither the port nor the
    link cases would notice.
    """
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.IPAM)

    response = rest_api.post(PREVIEW_URL, json={
        'device_kind': 'STANDARD', 'syntax': 'Gi0/{n}', 'count': 2,
    })

    assert response.status_code != HTTPStatus.FORBIDDEN


@pytest.mark.usefixtures('seeded_port')
def test_bulk_create_blocked_without_license(rest_api) -> None:
    """Creating a whole device's ports is blocked before the view runs"""
    response = rest_api.post(BULK_URL, json={
        'device_kind': 'STANDARD', 'syntax': 'Gi0/{n}', 'count': 2,
    })

    assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.usefixtures('seeded_port')
def test_bulk_create_reachable_once_licensed(rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    The registration-order guard for the FOURTH blueprint mounted on /ports

    Gating a blueprint that is already registered silently does nothing, and none of the other three
    surfaces would notice.
    """
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.IPAM)

    response = rest_api.post(BULK_URL, json={
        'device_kind': 'STANDARD', 'syntax': 'Gi0/{n}', 'count': 2,
    })

    assert response.status_code != HTTPStatus.FORBIDDEN


# -------------------------------------------------------------------------------------------------------------------- #
#                                       the Cable CI, gated on the type write                                          #
# -------------------------------------------------------------------------------------------------------------------- #

@pytest.mark.usefixtures('clean_cable_type')
def test_creating_a_cable_type_is_blocked_without_license(rest_api) -> None:
    """
    The Cable CI is part of Port Connectivity, so it is gated with the rest of the feature

    The guard is the type write's own, not a blueprint gate - CABLE is a member of
    SpecialType.get_license_gated_types, which is what the /types route consults.
    """
    assert rest_api.post(f'{TYPES_URL}/', json=_cable_type_payload()).status_code == HTTPStatus.FORBIDDEN


@pytest.mark.usefixtures('clean_cable_type')
def test_creating_a_cable_type_succeeds_once_licensed(
        rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Without this the refusal above could equally be a broken payload

    It is also what proves CABLE was added to the gated set rather than merely to the enum.
    """
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.IPAM)

    response = rest_api.post(f'{TYPES_URL}/', json=_cable_type_payload())

    assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)
