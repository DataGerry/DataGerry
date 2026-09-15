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
Functional tests for the Cable CI delete guard and its pre-check route

A `CABLE` CmdbPortConnection may describe its cable through a Cable CI, and the connection is a fact
about two ports that outlives that inventory record. So deleting a Cable CI a connection still names
is REFUSED (400) rather than cascaded or left dangling - see `cmdb.framework.port.cable_usage` for
why that direction was chosen. This module measures the rule where it actually applies: over the two
object-delete routes, and over the pre-check a client asks before it offers the delete at all.

Three things only a functional test can show here:

  1. the guard really runs on BOTH delete routes. It lives in `objects_helper.guard_objects_delete`,
     which each route calls for itself; a unit test of the guard cannot tell whether a route calls it
  2. the bulk delete is refused as a WHOLE - one blocked cable in the selection means nothing is
     deleted, which is only visible by asking for the other targets afterwards
  3. the bulk delete runs the Port cascade. It used to be wired into the single delete's
     `delete_one_cascade` only, so bulk-deleting a switch left its CmdbPorts (and their connections)
     behind, pointing at an object that no longer existed

The whole surface is gated behind LicenseFeature.IPAM (decision D6), which is why the license fixture
is autouse here
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.object_model import CmdbObject
from cmdb.models.port_model import CmdbPort, PortKey, PortSide
from cmdb.models.port_connection_model import ConnectionType, PortConnectionKey, CmdbPortConnection
from cmdb.models.special_type_model.cable_constants import CableField
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model import CmdbType, FieldType, SectionType
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.manager.port_connections_manager import PortConnectionsManager
from cmdb.errors.manager.port_connections_manager import PortConnectionsManagerGetError
from cmdb.errors.security import AccessDeniedError
from cmdb.security.license.license_constants import LicenseFeature
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/port_connections'
PORTS_URL: str = '/ports'
OBJECTS_URL: str = '/objects'
CABLE_USAGE_ROUTE: str = '/cable_usage'

PORT_TYPE_ID: int = 9501
CABLE_TYPE_ID: int = 9502
PLAIN_TYPE_ID: int = 9503

OWNER_OBJECT_ID: int = 9511
PEER_OBJECT_ID: int = 9512
CABLE_CI_ID: int = 9513
OTHER_CABLE_CI_ID: int = 9514
PLAIN_OBJECT_ID: int = 9515

FRONT_PORT_ID: int = 9521
SERVER_PORT_ID: int = 9522
SWITCH_PORT_ID: int = 9523

MISSING_OBJECT_ID: int = 9549

NAME_FIELD: str = 'dg-name'

ALL_TYPE_IDS: list[int] = [PORT_TYPE_ID, CABLE_TYPE_ID, PLAIN_TYPE_ID]
ALL_OBJECT_IDS: list[int] = [
    OWNER_OBJECT_ID, PEER_OBJECT_ID, CABLE_CI_ID, OTHER_CABLE_CI_ID, PLAIN_OBJECT_ID,
]
ALL_PORT_IDS: list[int] = [FRONT_PORT_ID, SERVER_PORT_ID, SWITCH_PORT_ID]


@pytest.fixture(autouse=True)
def _ipam_licensed(monkeypatch: pytest.MonkeyPatch):
    """Licenses IPAM so the gated Cable + Port Connectivity surface is reachable (decision D6)."""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.IPAM)


def _type_doc(public_id: int, uses_ports: bool = False, special_type: str | None = None) -> dict[str, Any]:
    """A CmdbType document, optionally port-bearing or marked as the Cable SpecialType."""
    doc: dict[str, Any] = {
        'public_id': public_id,
        'name': f'cable-guard-type-{public_id}',
        'label': f'Cable Guard Type {public_id}',
        'author_id': 1,
        'active': True,
        'version': '1.0.0',
        'uses_ports': uses_ports,
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

    if special_type:
        doc['special_type'] = special_type

    return doc


def _object_doc(public_id: int, type_id: int) -> dict[str, Any]:
    """A CmdbObject document of the given type."""
    return {
        'public_id': public_id,
        'type_id': type_id,
        'active': True,
        'author_id': 1,
        'version': '1.0.0',
        'fields': [{'name': NAME_FIELD, 'value': f'host-{public_id}', 'type': FieldType.TEXT.value}],
        'multi_data_sections': [],
    }


def _cable_ci_doc(public_id: int, cable_name: str) -> dict[str, Any]:
    """A CABLE SpecialType CmdbObject carrying its dg-cable-name."""
    document: dict[str, Any] = _object_doc(public_id, CABLE_TYPE_ID)
    document['fields'] = [
        {'name': CableField.NAME.value, 'value': cable_name, 'type': FieldType.TEXT.value},
    ]

    return document


def _port_doc(public_id: int, object_id: int, name: str) -> dict[str, Any]:
    """A stored CmdbPort document."""
    return {
        PortKey.PUBLIC_ID.value: public_id,
        PortKey.OBJECT_ID.value: object_id,
        PortKey.SIDE.value: PortSide.SINGLE.value,
        PortKey.NAME.value: name,
        PortKey.AUTHOR_ID.value: 1,
    }


@pytest.fixture(name='seeded', autouse=True)
def fixture_seeded(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the types, objects and ports; clears the connections around each test."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    ports = database_manager.get_collection(CmdbPort.COLLECTION, database_name)
    connections = database_manager.get_collection(CmdbPortConnection.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': {'$in': ALL_TYPE_IDS}})
        objects.delete_many({'public_id': {'$in': ALL_OBJECT_IDS}})
        ports.delete_many({PortKey.PUBLIC_ID.value: {'$in': ALL_PORT_IDS}})
        connections.delete_many({PortConnectionKey.ENDPOINTS.value: {'$in': ALL_PORT_IDS}})

    _purge()

    types.insert_many([
        _type_doc(PORT_TYPE_ID, uses_ports=True),
        _type_doc(CABLE_TYPE_ID, special_type=SpecialType.CABLE.value),
        _type_doc(PLAIN_TYPE_ID),
    ])
    objects.insert_many([
        _object_doc(OWNER_OBJECT_ID, PORT_TYPE_ID),
        _object_doc(PEER_OBJECT_ID, PORT_TYPE_ID),
        _cable_ci_doc(CABLE_CI_ID, 'patch 1'),
        _cable_ci_doc(OTHER_CABLE_CI_ID, 'patch 2'),
        _object_doc(PLAIN_OBJECT_ID, PLAIN_TYPE_ID),
    ])
    ports.insert_many([
        _port_doc(FRONT_PORT_ID, OWNER_OBJECT_ID, '1'),
        _port_doc(SERVER_PORT_ID, PEER_OBJECT_ID, 'eth0'),
        _port_doc(SWITCH_PORT_ID, PEER_OBJECT_ID, 'Gi0/1'),
    ])

    yield connections

    _purge()


def _create(rest_api, endpoints: list[int], **overrides: Any):
    """POSTs a CABLE connection between the two ports."""
    payload: dict[str, Any] = {'endpoints': endpoints, 'connection_type': ConnectionType.CABLE.value}
    payload.update(overrides)

    return rest_api.post(f'{ROUTE_URL}/', json=payload)


def _created_id(response) -> int:
    """Reads the public_id out of an InsertSingleResponse."""
    return response.get_json()['result_id']


def _raiser(error: Exception):
    """A replacement that always raises the given error."""
    def _raise(*_args: Any, **_kwargs: Any) -> None:
        raise error

    return _raise


# -------------------------------------------------------------------------------------------------------------------- #
#                                    the cable pre-check and the delete refusal                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCableUsagePreCheck:
    """GET /port_connections/cable_usage/<object_id> - what a client asks before offering the delete."""

    @staticmethod
    def _get(rest_api, object_id: int):
        """Asks the pre-check for one object."""
        return rest_api.get(f'{ROUTE_URL}{CABLE_USAGE_ROUTE}/{object_id}')

    def test_a_free_cable_reports_no_usage(self, rest_api) -> None:
        """Nothing is cabled to it, so the delete may be offered"""
        payload = self._get(rest_api, CABLE_CI_ID).get_json()

        assert payload == {'in_use': False, 'connection_id': None, 'endpoints': None}

    def test_a_used_cable_names_its_connection_and_both_ports(self, rest_api) -> None:
        """The ids the user needs to resolve the connection, before they hit the refusal"""
        connection_id = _created_id(
            _create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID], cable_ci_id=CABLE_CI_ID),
        )

        payload = self._get(rest_api, CABLE_CI_ID).get_json()

        assert payload == {
            'in_use': True,
            'connection_id': connection_id,
            'endpoints': sorted([SERVER_PORT_ID, FRONT_PORT_ID]),
        }

    def test_an_inline_cabled_connection_leaves_its_cable_ci_free(self, rest_api) -> None:
        """A connection describing its cable inline claims no CI at all"""
        _create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID], cable_name='Patch 1')

        assert self._get(rest_api, CABLE_CI_ID).get_json()['in_use'] is False

    def test_an_object_that_is_not_a_cable_reports_no_usage(self, rest_api) -> None:
        """No connection can name it as its cable, which is the honest answer for it"""
        assert self._get(rest_api, PLAIN_OBJECT_ID).get_json()['in_use'] is False

    def test_an_unknown_object_is_a_404(self, rest_api) -> None:
        """Asking about an object that does not exist is a different answer from 'not in use'"""
        assert self._get(rest_api, MISSING_OBJECT_ID).status_code == HTTPStatus.NOT_FOUND

    def test_head_answers_without_a_body(self, rest_api) -> None:
        """The route serves HEAD like its siblings"""
        response = rest_api.head(f'{ROUTE_URL}{CABLE_USAGE_ROUTE}/{CABLE_CI_ID}')

        assert response.status_code == HTTPStatus.OK
        assert not response.get_data()

    @pytest.mark.parametrize('error, expected', [
        (PortConnectionsManagerGetError('boom'), HTTPStatus.BAD_REQUEST),
        (RuntimeError('boom'), HTTPStatus.INTERNAL_SERVER_ERROR),
        (AccessDeniedError('nope'), HTTPStatus.FORBIDDEN),
    ], ids=['read-failed', 'unexpected', 'acl'])
    def test_a_failing_read_maps_to_its_own_status(
            self, rest_api, monkeypatch, error: Exception, expected: int,
    ) -> None:
        """A failed lookup is refused readably instead of surfacing as a blanket 500"""
        monkeypatch.setattr(PortConnectionsManager, 'get_connections_by_cable_cis', _raiser(error))

        assert self._get(rest_api, CABLE_CI_ID).status_code == expected


class TestCableCiDeleteRefusal:
    """A Cable CI a connection still uses may not be deleted - through EITHER object-delete route."""

    @staticmethod
    def _object_exists(rest_api, object_id: int) -> bool:
        """Whether the CmdbObject is still stored."""
        return rest_api.get(f'{OBJECTS_URL}/native/{object_id}').status_code == HTTPStatus.OK

    def test_the_single_delete_is_refused_with_400(self, rest_api) -> None:
        """The connection describes a physical patch, so the cable record may not simply vanish"""
        connection_id = _created_id(
            _create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID], cable_ci_id=CABLE_CI_ID),
        )

        response = rest_api.delete(f'{OBJECTS_URL}/{CABLE_CI_ID}')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert self._object_exists(rest_api, CABLE_CI_ID)
        assert rest_api.get(f'{ROUTE_URL}/{connection_id}').status_code == HTTPStatus.OK

    def test_the_refusal_names_the_cable_the_connection_and_the_ports(self, rest_api) -> None:
        """Everything the user needs to act on is in the message itself"""
        connection_id = _created_id(
            _create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID], cable_ci_id=CABLE_CI_ID),
        )

        message = rest_api.delete(f'{OBJECTS_URL}/{CABLE_CI_ID}').get_json()['message']

        assert f'ID:{CABLE_CI_ID}' in message
        assert f'ID:{connection_id}' in message
        assert str(SERVER_PORT_ID) in message
        assert str(FRONT_PORT_ID) in message

    def test_a_free_cable_still_deletes(self, rest_api) -> None:
        """The guard refuses the used cable only; nothing else about the delete changes"""
        assert rest_api.delete(f'{OBJECTS_URL}/{OTHER_CABLE_CI_ID}').status_code == HTTPStatus.OK
        assert self._object_exists(rest_api, OTHER_CABLE_CI_ID) is False

    def test_resolving_the_connection_allows_the_delete(self, rest_api) -> None:
        """The way out of the refusal, and the reason it is a refusal rather than a cascade"""
        connection_id = _created_id(
            _create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID], cable_ci_id=CABLE_CI_ID),
        )

        assert rest_api.delete(f'{OBJECTS_URL}/{CABLE_CI_ID}').status_code == HTTPStatus.BAD_REQUEST

        rest_api.delete(f'{ROUTE_URL}/{connection_id}')

        assert rest_api.delete(f'{OBJECTS_URL}/{CABLE_CI_ID}').status_code == HTTPStatus.OK

    def test_the_bulk_delete_is_refused_as_a_whole(self, rest_api) -> None:
        """
        One blocked cable refuses the whole selection, and nothing in it is deleted

        The guard runs before the delete loop for exactly this reason: refusing halfway would leave the
        earlier targets already gone, with a 400 telling the user the deletion did not happen.
        """
        _create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID], cable_ci_id=CABLE_CI_ID)

        response = rest_api.delete(f'{OBJECTS_URL}/delete/{OTHER_CABLE_CI_ID},{CABLE_CI_ID}')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert self._object_exists(rest_api, CABLE_CI_ID)
        assert self._object_exists(rest_api, OTHER_CABLE_CI_ID)

    def test_the_bulk_delete_of_free_cables_still_works(self, rest_api) -> None:
        """A selection with nothing in use is deleted as before"""
        response = rest_api.delete(f'{OBJECTS_URL}/delete/{CABLE_CI_ID},{OTHER_CABLE_CI_ID}')

        assert response.status_code == HTTPStatus.OK
        assert sorted(response.get_json()['successfully']) == sorted([CABLE_CI_ID, OTHER_CABLE_CI_ID])

    def test_the_bulk_delete_takes_the_ports_of_its_targets_with_it(self, rest_api) -> None:
        """
        The Port cascade runs in the bulk loop too - it used to be wired into the single delete only

        A port lives outside its owner's document, so nothing else would ever remove it: a bulk-deleted
        switch left its ports (and their connections) behind, referencing an object that no longer
        exists.
        """
        _create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID], cable_ci_id=CABLE_CI_ID)

        response = rest_api.delete(f'{OBJECTS_URL}/delete/{PEER_OBJECT_ID}')

        assert response.status_code == HTTPStatus.OK
        assert rest_api.get(f'{PORTS_URL}/{SERVER_PORT_ID}').status_code == HTTPStatus.NOT_FOUND
        assert rest_api.get(f'{ROUTE_URL}/port/{FRONT_PORT_ID}').get_json() == []
