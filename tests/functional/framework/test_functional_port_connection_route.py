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
Functional tests for the ``/port_connections`` REST routes

Covers the whole surface over HTTP: create / read single / read per port / update / delete, plus the
invariants the routes exist to hold - the endpoints and the connection type are immutable, an update
writes cable information only, a cable field is refused on an INTERNAL connection, and the
cardinality rules (one cable and one internal per port, no duplicate pair, one connection per cable
CI) are refused readably.

Two things here can only be measured over the real database, and both are the reason the routes exist
in this shape:

* a cable CI the update OMITS is really removed from the stored document, not merely left unset in
  the response - the key has to be `$unset`, because `$set` alone can not clear it and a null would
  break the index that is filtered on the key's presence
* deleting a port takes its connections with it and leaves its peers' other connections alone

Note the test database never goes through CollectionValidator, so its collections carry no declared
index. The suite builds the CmdbPortConnection indexes itself where the index is the thing under test
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.object_model import CmdbObject
from cmdb.models.port_model import CmdbPort, PortKey, PortSide
from cmdb.models.port_connection_model import CmdbPortConnection, ConnectionType, PortConnectionKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model import CmdbType, FieldType, SectionType
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.manager.port_connections_manager import PortConnectionsManager
from cmdb.errors.manager.port_connections_manager import (
    PortConnectionsManagerDeleteError,
    PortConnectionsManagerGetError,
    PortConnectionsManagerInsertError,
    PortConnectionsManagerUpdateError,
)
from cmdb.security.license.license_constants import LicenseFeature
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/port_connections'
PORTS_URL: str = '/ports'

PORT_TYPE_ID: int = 9920
CABLE_TYPE_ID: int = 9921
PLAIN_TYPE_ID: int = 9922

OWNER_OBJECT_ID: int = 9930
PEER_OBJECT_ID: int = 9931
CABLE_CI_ID: int = 9932
OTHER_CABLE_CI_ID: int = 9933
PLAIN_OBJECT_ID: int = 9934

FRONT_PORT_ID: int = 9940
REAR_PORT_ID: int = 9941
SERVER_PORT_ID: int = 9942
SWITCH_PORT_ID: int = 9943
SPARE_PORT_ID: int = 9944

MISSING_PORT_ID: int = 9998
MISSING_CONNECTION_ID: int = 9997

NAME_FIELD: str = 'dg-name'

ALL_TYPE_IDS: list[int] = [PORT_TYPE_ID, CABLE_TYPE_ID, PLAIN_TYPE_ID]
ALL_OBJECT_IDS: list[int] = [
    OWNER_OBJECT_ID, PEER_OBJECT_ID, CABLE_CI_ID, OTHER_CABLE_CI_ID, PLAIN_OBJECT_ID,
]
ALL_PORT_IDS: list[int] = [
    FRONT_PORT_ID, REAR_PORT_ID, SERVER_PORT_ID, SWITCH_PORT_ID, SPARE_PORT_ID,
]


@pytest.fixture(autouse=True)
def _ipam_licensed(monkeypatch: pytest.MonkeyPatch):
    """
    Licenses IPAM so the gated /port_connections surface is reachable

    Port Connectivity is gated behind LicenseFeature.IPAM by decision D6. That the gate really blocks
    the surface is asserted in tests/functional/license/.
    """
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.IPAM)


def _type_doc(public_id: int, uses_ports: bool = False, special_type: str | None = None) -> dict[str, Any]:
    """A CmdbType document, optionally port-bearing or marked as the Cable SpecialType."""
    doc: dict[str, Any] = {
        'public_id': public_id,
        'name': f'connection-type-{public_id}',
        'label': f'Connection Type {public_id}',
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


def _port_doc(public_id: int, object_id: int, name: str, side: str = PortSide.SINGLE.value) -> dict[str, Any]:
    """A stored CmdbPort document."""
    return {
        PortKey.PUBLIC_ID.value: public_id,
        PortKey.OBJECT_ID.value: object_id,
        PortKey.SIDE.value: side,
        PortKey.NAME.value: name,
        PortKey.AUTHOR_ID.value: 1,
    }


def _payload(
        endpoints: list[int],
        connection_type: str = ConnectionType.CABLE.value,
        **overrides: Any) -> dict[str, Any]:
    """A create/update body for a connection."""
    payload: dict[str, Any] = {'endpoints': endpoints, 'connection_type': connection_type}
    payload.update(overrides)

    return payload


def _connections(database_manager: MongoDatabaseManager, database_name: str):
    """The raw connection collection."""
    return database_manager.get_collection(CmdbPortConnection.COLLECTION, database_name)


@pytest.fixture(name='seeded', autouse=True)
def fixture_seeded(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the types, objects and ports; clears the connections around each test."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    ports = database_manager.get_collection(CmdbPort.COLLECTION, database_name)
    connections = _connections(database_manager, database_name)

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
        _object_doc(CABLE_CI_ID, CABLE_TYPE_ID),
        _object_doc(OTHER_CABLE_CI_ID, CABLE_TYPE_ID),
        _object_doc(PLAIN_OBJECT_ID, PLAIN_TYPE_ID),
    ])
    ports.insert_many([
        _port_doc(FRONT_PORT_ID, OWNER_OBJECT_ID, '1', PortSide.FRONT.value),
        _port_doc(REAR_PORT_ID, OWNER_OBJECT_ID, '1', PortSide.REAR.value),
        _port_doc(SERVER_PORT_ID, PEER_OBJECT_ID, 'eth0'),
        _port_doc(SWITCH_PORT_ID, PEER_OBJECT_ID, 'Gi0/1'),
        _port_doc(SPARE_PORT_ID, PEER_OBJECT_ID, 'Gi0/2'),
    ])

    yield connections

    _purge()


@pytest.fixture(name='indexed')
def fixture_indexed(database_manager: MongoDatabaseManager, database_name: str, seeded):
    """
    Builds the model's declared indexes, for the assertions where the index IS the thing under test

    The application does this at startup through CollectionValidator; the test database never goes
    through it, so without this a duplicate write would simply succeed.
    """
    database_manager.create_indexes(
        CmdbPortConnection.COLLECTION, database_name, CmdbPortConnection.get_index_keys(),
    )

    return seeded


def _create(rest_api, endpoints: list[int], **kwargs: Any):
    """POSTs a connection."""
    return rest_api.post(f'{ROUTE_URL}/', json=_payload(endpoints, **kwargs))


def _created_id(response) -> int:
    """Reads the public_id out of an InsertSingleResponse."""
    return response.get_json()['result_id']


def _raiser(error: Exception):
    """A replacement that always raises the given error."""
    def _raise(*_args: Any, **_kwargs: Any) -> None:
        raise error

    return _raise


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       CREATE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCreateConnection:
    """POST /port_connections/"""

    def test_creates_a_connection_and_stamps_the_server_owned_fields(self, rest_api) -> None:
        """The author and the creation time come from the request, never from the body."""
        response = _create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID], cable_name='Patch 1')

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)

        created = response.get_json()['raw']

        assert created[PortConnectionKey.CABLE_NAME.value] == 'Patch 1'
        assert created[PortConnectionKey.AUTHOR_ID.value] is not None
        assert created[PortConnectionKey.CREATION_TIME.value] is not None

    def test_the_stored_endpoints_are_sorted(self, rest_api) -> None:
        """
        The canonical form is what makes the link undirected and the pair indexable

        Sent high-then-low; stored low-then-high, so the same link has exactly one spelling.
        """
        response = _create(rest_api, [SWITCH_PORT_ID, SERVER_PORT_ID])

        assert response.get_json()['raw'][PortConnectionKey.ENDPOINTS.value] == sorted(
            [SERVER_PORT_ID, SWITCH_PORT_ID],
        )

    def test_a_connection_without_a_cable_ci_omits_the_key(self, rest_api, seeded) -> None:
        """
        ABSENT, never null - the unique index on cable_ci_id is filtered on the key's PRESENCE

        A stored null would put every CI-less connection into that index, and the second one created
        in the installation would be refused as a duplicate.
        """
        new_id: int = _created_id(_create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID]))

        stored = seeded.find_one({PortConnectionKey.PUBLIC_ID.value: new_id})

        assert PortConnectionKey.CABLE_CI_ID.value not in stored

    def test_a_cable_ci_is_stored_when_named(self, rest_api, seeded) -> None:
        """Scenario B - cable info plus an inventoried cable"""
        new_id: int = _created_id(
            _create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID], cable_ci_id=CABLE_CI_ID),
        )

        stored = seeded.find_one({PortConnectionKey.PUBLIC_ID.value: new_id})

        assert stored[PortConnectionKey.CABLE_CI_ID.value] == CABLE_CI_ID

    def test_an_internal_connection_pairs_a_panels_faces(self, rest_api) -> None:
        """The pairing IS the connection - it is never derived from the ports' names"""
        response = _create(
            rest_api, [FRONT_PORT_ID, REAR_PORT_ID], connection_type=ConnectionType.INTERNAL.value,
        )

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)

    def test_a_missing_connection_type_is_refused(self, rest_api) -> None:
        """Deliberately not defaulted: a typo must not create the wrong kind of link"""
        response = rest_api.post(f'{ROUTE_URL}/', json={'endpoints': [SERVER_PORT_ID, FRONT_PORT_ID]})

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_a_self_connection_is_refused(self, rest_api) -> None:
        """The one cardinality rule no index can hold"""
        response = _create(rest_api, [SERVER_PORT_ID, SERVER_PORT_ID])

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_a_missing_endpoint_is_refused(self, rest_api) -> None:
        """A connection may not point at a port that does not exist"""
        response = _create(rest_api, [SERVER_PORT_ID, MISSING_PORT_ID])

        assert response.status_code == HTTPStatus.BAD_REQUEST

    @pytest.mark.parametrize('endpoints', [[SERVER_PORT_ID], [SERVER_PORT_ID, FRONT_PORT_ID, SPARE_PORT_ID]])
    def test_anything_but_two_endpoints_is_refused(self, rest_api, endpoints: list[int]) -> None:
        """A connection joins exactly two ports"""
        assert _create(rest_api, endpoints).status_code == HTTPStatus.BAD_REQUEST

    def test_cable_info_on_an_internal_connection_is_refused(self, rest_api) -> None:
        """A panel's internal pairing has no cable"""
        response = _create(
            rest_api, [FRONT_PORT_ID, REAR_PORT_ID],
            connection_type=ConnectionType.INTERNAL.value, cable_name='Patch 1',
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_a_cable_ci_of_another_type_is_refused(self, rest_api) -> None:
        """
        An arbitrary object must not be stored and rendered as a cable

        This is why SpecialType.CABLE had to exist before a connection could be written at all.
        """
        response = _create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID], cable_ci_id=PLAIN_OBJECT_ID)

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_a_missing_cable_ci_is_refused(self, rest_api) -> None:
        """A dangling reference must not be created in the first place"""
        response = _create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID], cable_ci_id=MISSING_CONNECTION_ID)

        assert response.status_code == HTTPStatus.BAD_REQUEST


# -------------------------------------------------------------------------------------------------------------------- #
#                                        the cardinality rules, over HTTP                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCardinality:
    """A port holds one cable and one internal connection; a cable CI belongs to one connection."""

    def test_a_second_cable_on_the_same_port_is_refused_readably(self, rest_api) -> None:
        """
        The message names the occupied port, not a duplicate-key error

        A caller told only 'duplicate key' would have to guess which of the two ids it sent is the
        problem.
        """
        _create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID])

        response = _create(rest_api, [FRONT_PORT_ID, SWITCH_PORT_ID])

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert str(FRONT_PORT_ID) in response.get_json()['message']

    def test_a_port_may_hold_one_cable_and_one_internal_connection(self, rest_api) -> None:
        """Without this a patch panel would be unbuildable"""
        _create(rest_api, [FRONT_PORT_ID, REAR_PORT_ID], connection_type=ConnectionType.INTERNAL.value)

        response = _create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID])

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)

    def test_a_second_internal_connection_on_the_same_port_is_refused(self, rest_api) -> None:
        """A front port pairs with exactly one rear port"""
        _create(rest_api, [FRONT_PORT_ID, REAR_PORT_ID], connection_type=ConnectionType.INTERNAL.value)

        response = _create(
            rest_api, [FRONT_PORT_ID, SPARE_PORT_ID], connection_type=ConnectionType.INTERNAL.value,
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_an_already_connected_pair_reports_the_pair(self, rest_api) -> None:
        """A different mistake from 'this port is in use elsewhere', so it gets its own message"""
        _create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID])

        response = _create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID])

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'already connected' in response.get_json()['message']

    def test_the_opposite_order_is_the_same_pair(self, rest_api) -> None:
        """The sort is what makes the two spellings one link"""
        _create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID])

        response = _create(rest_api, [FRONT_PORT_ID, SERVER_PORT_ID])

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_a_second_connection_claiming_the_same_cable_ci_is_refused(self, rest_api) -> None:
        """Reusing one inventoried cable on two links is a data-entry error"""
        _create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID], cable_ci_id=CABLE_CI_ID)

        response = _create(rest_api, [SWITCH_PORT_ID, REAR_PORT_ID], cable_ci_id=CABLE_CI_ID)

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_a_stored_duplicate_is_caught_by_the_pre_check(self, rest_api, indexed) -> None:
        """
        The ordinary path: the read finds the existing row before the write is attempted

        Seeding the row directly rather than through the route, so the refusal comes from the
        pre-check and not from a create the route itself performed.
        """
        indexed.insert_one({
            PortConnectionKey.PUBLIC_ID.value: MISSING_CONNECTION_ID,
            PortConnectionKey.ENDPOINTS.value: sorted([SERVER_PORT_ID, FRONT_PORT_ID]),
            PortConnectionKey.CONNECTION_TYPE.value: ConnectionType.CABLE.value,
        })

        response = _create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID])

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_the_index_refuses_a_racing_duplicate_with_the_same_wording(
            self, rest_api, monkeypatch) -> None:
        """
        The arm that holds under concurrency, and the only way to reach it

        Every pre-check is a read followed by a write, so in a real race BOTH creates pass them and
        the index stops the loser at insert time. The seeded-row case above can not exercise this -
        its pre-check catches the duplicate first - so the failure is injected at the insert itself,
        which is exactly where a concurrent write would land. The message must still be the
        actionable one rather than a raw driver error.
        """
        monkeypatch.setattr(
            PortConnectionsManager, 'insert_item',
            _raiser(PortConnectionsManagerInsertError(
                "Duplicate key error in collection 'framework.portConnections': "
                "{'endpoints': 1} already exists (index on ['endpoints'])",
            )),
        )

        response = _create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID])

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'already has a cable connection' in response.get_json()['message']


# -------------------------------------------------------------------------------------------------------------------- #
#                                                        READ                                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class TestReadConnection:
    """GET /port_connections/<id> and /port_connections/port/<port_id>"""

    def test_reads_a_single_connection(self, rest_api) -> None:
        """The ordinary case"""
        new_id: int = _created_id(_create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID]))

        response = rest_api.get(f'{ROUTE_URL}/{new_id}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['result'][PortConnectionKey.PUBLIC_ID.value] == new_id

    def test_a_missing_connection_is_a_404(self, rest_api) -> None:
        """Addressing a row that does not exist"""
        assert rest_api.get(f'{ROUTE_URL}/{MISSING_CONNECTION_ID}').status_code == HTTPStatus.NOT_FOUND

    def test_reads_every_connection_of_a_port(self, rest_api) -> None:
        """
        A panel port legitimately has two: its cable and its internal pairing

        One indexed predicate finds it at either end, because the two ids share one array field.
        """
        _create(rest_api, [FRONT_PORT_ID, REAR_PORT_ID], connection_type=ConnectionType.INTERNAL.value)
        _create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID])

        response = rest_api.get(f'{ROUTE_URL}/port/{FRONT_PORT_ID}')

        assert response.status_code == HTTPStatus.OK
        assert len(response.get_json()) == 2

    def test_a_free_port_answers_with_an_empty_list(self, rest_api) -> None:
        """'Free' is a normal state, not a 404"""
        response = rest_api.get(f'{ROUTE_URL}/port/{SPARE_PORT_ID}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == []

    def test_a_missing_port_is_a_404(self, rest_api) -> None:
        """A different answer from 'this port is free', so a typo is distinguishable"""
        response = rest_api.get(f'{ROUTE_URL}/port/{MISSING_PORT_ID}')

        assert response.status_code == HTTPStatus.NOT_FOUND


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       UPDATE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestUpdateConnection:
    """PUT /port_connections/<id> - cable information only"""

    def test_updates_the_cable_information(self, rest_api) -> None:
        """The ordinary case"""
        new_id: int = _created_id(_create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID], cable_name='Old'))

        response = rest_api.put(f'{ROUTE_URL}/{new_id}', json={'cable_name': 'New', 'cable_length': '3 m'})

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)

        updated = rest_api.get(f'{ROUTE_URL}/{new_id}').get_json()['result']

        assert updated[PortConnectionKey.CABLE_NAME.value] == 'New'
        assert updated[PortConnectionKey.CABLE_LENGTH.value] == '3 m'

    def test_an_omitted_cable_ci_is_really_removed(self, rest_api, seeded) -> None:
        """
        The trap the manager's $unset exists for

        BaseManager.update wraps its payload in $set, so a key left out would keep its stored value -
        and cable_ci_id can not be nulled instead, because its index is filtered on the key's presence.
        Without the $unset a user could never take a cable CI off a connection.
        """
        new_id: int = _created_id(
            _create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID], cable_ci_id=CABLE_CI_ID),
        )

        rest_api.put(f'{ROUTE_URL}/{new_id}', json={'cable_name': 'No CI any more'})

        stored = seeded.find_one({PortConnectionKey.PUBLIC_ID.value: new_id})

        assert PortConnectionKey.CABLE_CI_ID.value not in stored

    def test_a_cable_ci_may_be_swapped(self, rest_api, seeded) -> None:
        """The other half: naming a different Cable replaces the reference"""
        new_id: int = _created_id(
            _create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID], cable_ci_id=CABLE_CI_ID),
        )

        rest_api.put(f'{ROUTE_URL}/{new_id}', json={'cable_ci_id': OTHER_CABLE_CI_ID})

        stored = seeded.find_one({PortConnectionKey.PUBLIC_ID.value: new_id})

        assert stored[PortConnectionKey.CABLE_CI_ID.value] == OTHER_CABLE_CI_ID

    def test_re_asserting_its_own_cable_ci_is_allowed(self, rest_api) -> None:
        """A client that round-trips a GET sends the whole document back"""
        new_id: int = _created_id(
            _create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID], cable_ci_id=CABLE_CI_ID),
        )

        response = rest_api.put(f'{ROUTE_URL}/{new_id}', json={'cable_ci_id': CABLE_CI_ID})

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)

    def test_claiming_another_connections_cable_ci_is_refused(self, rest_api) -> None:
        """One inventoried cable belongs to at most one connection"""
        _create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID], cable_ci_id=CABLE_CI_ID)
        second_id: int = _created_id(_create(rest_api, [SWITCH_PORT_ID, REAR_PORT_ID]))

        response = rest_api.put(f'{ROUTE_URL}/{second_id}', json={'cable_ci_id': CABLE_CI_ID})

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_changing_an_endpoint_is_refused(self, rest_api) -> None:
        """
        Refused rather than ignored, so a client can not discover its edit did nothing

        A re-cable is a delete plus a create.
        """
        new_id: int = _created_id(_create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID]))

        response = rest_api.put(f'{ROUTE_URL}/{new_id}', json={'endpoints': [SERVER_PORT_ID, SPARE_PORT_ID]})

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_repeating_the_endpoints_in_the_opposite_order_is_allowed(self, rest_api) -> None:
        """The link is undirected, so the spelling of the pair is not a change"""
        new_id: int = _created_id(_create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID]))

        response = rest_api.put(
            f'{ROUTE_URL}/{new_id}',
            json={'endpoints': [FRONT_PORT_ID, SERVER_PORT_ID], 'cable_name': 'Patch 1'},
        )

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)

    def test_changing_the_connection_type_is_refused(self, rest_api) -> None:
        """It would move the row between the two partial unique indexes"""
        new_id: int = _created_id(_create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID]))

        response = rest_api.put(
            f'{ROUTE_URL}/{new_id}', json={'connection_type': ConnectionType.INTERNAL.value},
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_cable_info_on_an_internal_connection_is_refused(self, rest_api) -> None:
        """
        The stored type decides, not the payload's

        A body that omits the immutable connection_type still has to be judged by what the connection
        actually IS.
        """
        new_id: int = _created_id(_create(
            rest_api, [FRONT_PORT_ID, REAR_PORT_ID], connection_type=ConnectionType.INTERNAL.value,
        ))

        response = rest_api.put(f'{ROUTE_URL}/{new_id}', json={'cable_name': 'Patch 1'})

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_a_missing_connection_is_a_404(self, rest_api) -> None:
        """Addressing a row that does not exist"""
        response = rest_api.put(f'{ROUTE_URL}/{MISSING_CONNECTION_ID}', json={'cable_name': 'x'})

        assert response.status_code == HTTPStatus.NOT_FOUND


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       DELETE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDeleteConnection:
    """DELETE /port_connections/<id>"""

    def test_deletes_the_connection(self, rest_api) -> None:
        """The ordinary case"""
        new_id: int = _created_id(_create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID]))

        assert rest_api.delete(f'{ROUTE_URL}/{new_id}').status_code in (
            HTTPStatus.OK, HTTPStatus.ACCEPTED, HTTPStatus.NO_CONTENT,
        )
        assert rest_api.get(f'{ROUTE_URL}/{new_id}').status_code == HTTPStatus.NOT_FOUND

    def test_resolving_one_connection_leaves_the_others_alone(self, rest_api) -> None:
        """
        The concept's rule, held by construction: a route touches exactly the row it addresses

        A patch-panel pair carries a front connection, a rear connection and an internal pairing, and
        each has to be resolvable on its own.
        """
        internal_id: int = _created_id(_create(
            rest_api, [FRONT_PORT_ID, REAR_PORT_ID], connection_type=ConnectionType.INTERNAL.value,
        ))
        front_id: int = _created_id(_create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID]))
        rear_id: int = _created_id(_create(rest_api, [SWITCH_PORT_ID, REAR_PORT_ID]))

        rest_api.delete(f'{ROUTE_URL}/{front_id}')

        assert rest_api.get(f'{ROUTE_URL}/{internal_id}').status_code == HTTPStatus.OK
        assert rest_api.get(f'{ROUTE_URL}/{rear_id}').status_code == HTTPStatus.OK

    def test_the_peer_port_is_free_again(self, rest_api) -> None:
        """
        Nothing about the peer is rewritten - `connected` is computed, so freeing it needs no write

        Proven by the peer accepting a new cable straight afterwards.
        """
        new_id: int = _created_id(_create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID]))
        rest_api.delete(f'{ROUTE_URL}/{new_id}')

        response = _create(rest_api, [SERVER_PORT_ID, SWITCH_PORT_ID])

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)

    def test_a_missing_connection_is_a_404(self, rest_api) -> None:
        """Addressing a row that does not exist"""
        assert rest_api.delete(f'{ROUTE_URL}/{MISSING_CONNECTION_ID}').status_code == HTTPStatus.NOT_FOUND


# -------------------------------------------------------------------------------------------------------------------- #
#                                     the cascade, driven over the /ports route                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestPortDeleteCascade:
    """DELETE /ports/<id> takes the port's connections with it"""

    def test_deleting_a_port_removes_its_connections(self, rest_api) -> None:
        """A port may not leave a link pointing at nothing"""
        cable_id: int = _created_id(_create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID]))
        internal_id: int = _created_id(_create(
            rest_api, [FRONT_PORT_ID, REAR_PORT_ID], connection_type=ConnectionType.INTERNAL.value,
        ))

        assert rest_api.delete(f'{PORTS_URL}/{FRONT_PORT_ID}').status_code in (
            HTTPStatus.OK, HTTPStatus.ACCEPTED, HTTPStatus.NO_CONTENT,
        )

        assert rest_api.get(f'{ROUTE_URL}/{cable_id}').status_code == HTTPStatus.NOT_FOUND
        assert rest_api.get(f'{ROUTE_URL}/{internal_id}').status_code == HTTPStatus.NOT_FOUND

    def test_deleting_a_port_leaves_other_connections_untouched(self, rest_api) -> None:
        """The scope is the deleted port, which is the same rule as resolving one connection"""
        kept_id: int = _created_id(_create(rest_api, [SWITCH_PORT_ID, REAR_PORT_ID]))
        _create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID])

        rest_api.delete(f'{PORTS_URL}/{FRONT_PORT_ID}')

        assert rest_api.get(f'{ROUTE_URL}/{kept_id}').status_code == HTTPStatus.OK

    def test_the_peer_of_a_deleted_port_becomes_free(self, rest_api) -> None:
        """The peer keeps no trace of the removed link, so it can be cabled again"""
        _create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID])

        rest_api.delete(f'{PORTS_URL}/{FRONT_PORT_ID}')

        assert rest_api.get(f'{ROUTE_URL}/port/{SERVER_PORT_ID}').get_json() == []


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   error mapping                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
class TestErrorMapping:
    """
    A database failure is a 400, anything unexpected a 500 - never the other way round

    A manager error surfacing as a 500 hides a recoverable problem; an unexpected error surfacing as a
    400 tells the caller their request was wrong when it was not. The create route has a third arm:
    an insert failure is a duplicate-key refusal and has to keep its readable 400.
    """

    def test_create_retrieval_of_the_created_connection_failing_is_404(
            self, rest_api, monkeypatch) -> None:
        """The insert worked but the read-back did not, so the response would be empty."""
        monkeypatch.setattr(PortConnectionsManager, 'get_item', lambda *_a, **_k: None)

        assert _create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID]).status_code == HTTPStatus.NOT_FOUND

    def test_create_unexpected_error_is_500(self, rest_api, monkeypatch) -> None:
        """Not a 400: nothing is wrong with the request."""
        monkeypatch.setattr(PortConnectionsManager, 'insert_item', _raiser(RuntimeError('boom')))

        assert _create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID]).status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_single_read_manager_error_is_400(self, rest_api, monkeypatch) -> None:
        """A failed read is reported as a bad request, not as a crash."""
        monkeypatch.setattr(
            PortConnectionsManager, 'get_item', _raiser(PortConnectionsManagerGetError('boom')),
        )

        assert rest_api.get(f'{ROUTE_URL}/1').status_code == HTTPStatus.BAD_REQUEST

    def test_single_read_unexpected_error_is_500(self, rest_api, monkeypatch) -> None:
        """Anything else is a server error."""
        monkeypatch.setattr(PortConnectionsManager, 'get_item', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/1').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_port_read_manager_error_is_400(self, rest_api, monkeypatch) -> None:
        """The per-port list route maps its own manager error."""
        monkeypatch.setattr(
            PortConnectionsManager, 'get_connections_of_port',
            _raiser(PortConnectionsManagerGetError('boom')),
        )

        assert rest_api.get(f'{ROUTE_URL}/port/{SERVER_PORT_ID}').status_code == HTTPStatus.BAD_REQUEST

    def test_port_read_unexpected_error_is_500(self, rest_api, monkeypatch) -> None:
        """Anything else is a server error."""
        monkeypatch.setattr(
            PortConnectionsManager, 'get_connections_of_port', _raiser(RuntimeError('boom')),
        )

        assert rest_api.get(f'{ROUTE_URL}/port/{SERVER_PORT_ID}').status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_update_manager_error_is_400(self, rest_api, monkeypatch) -> None:
        """A failed write is reported as a bad request."""
        new_id: int = _created_id(_create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID]))
        monkeypatch.setattr(
            PortConnectionsManager, 'replace_connection',
            _raiser(PortConnectionsManagerUpdateError('boom')),
        )

        assert rest_api.put(f'{ROUTE_URL}/{new_id}', json={'cable_name': 'x'}).status_code \
            == HTTPStatus.BAD_REQUEST

    def test_update_unexpected_error_is_500(self, rest_api, monkeypatch) -> None:
        """Anything else is a server error."""
        new_id: int = _created_id(_create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID]))
        monkeypatch.setattr(PortConnectionsManager, 'replace_connection', _raiser(RuntimeError('boom')))

        assert rest_api.put(f'{ROUTE_URL}/{new_id}', json={'cable_name': 'x'}).status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_delete_manager_error_is_400(self, rest_api, monkeypatch) -> None:
        """A failed delete is reported as a bad request."""
        new_id: int = _created_id(_create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID]))
        monkeypatch.setattr(
            PortConnectionsManager, 'delete_item', _raiser(PortConnectionsManagerDeleteError('boom')),
        )

        assert rest_api.delete(f'{ROUTE_URL}/{new_id}').status_code == HTTPStatus.BAD_REQUEST

    def test_delete_unexpected_error_is_500(self, rest_api, monkeypatch) -> None:
        """Anything else is a server error."""
        new_id: int = _created_id(_create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID]))
        monkeypatch.setattr(PortConnectionsManager, 'delete_item', _raiser(RuntimeError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{new_id}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR
