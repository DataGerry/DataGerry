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
from datetime import datetime
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.object_model import CmdbObject
from cmdb.models.port_model import CmdbPort, PortKey, PortSide
from cmdb.models.port_connection_model import (
    CableSource,
    CableViewKey,
    CmdbPortConnection,
    ConnectionType,
    PortConnectionKey,
    CABLE_VIEW_KEY,
)
from cmdb.models.extendable_option_model import (
    CmdbExtendableOption,
    ExtendableOptionKey,
    OptionType,
)
from cmdb.class_schema.port_connection_model import get_cmdb_port_connection_write_schema
from cmdb.interface.rest_api.routes.port_connection_routes.port_connection_route_constants import (
    ConnectionRequestKey,
)
from cmdb.models.special_type_model.cable_constants import CableField
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model import CmdbType, FieldType, SectionType
from cmdb.manager import ObjectsManager, TypesManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.manager.port_connections_manager import PortConnectionsManager
from cmdb.manager.ports_manager import PortsManager
from cmdb.errors.manager.objects_manager import ObjectsManagerIterationError
from cmdb.errors.manager.ports_manager import PortsManagerGetError
from cmdb.errors.manager.types_manager import TypesManagerGetError
from cmdb.errors.security import AccessDeniedError
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
MISSING_OBJECT_ID: int = 9996

NAME_FIELD: str = 'dg-name'

UNASSIGNED_ROUTE: str = '/cables/unassigned/'
INACTIVE_CABLE_CI_ID: int = 9935
# Deliberately cased against their alphabetical order: MongoDB's binary collation would sort 'Zeta'
# before 'alpha', so the expected order proves the sort really folds case
CABLE_NAME_FIRST: str = 'alpha patch'
CABLE_NAME_SECOND: str = 'Zeta patch'
CABLE_NAME_INACTIVE: str = 'retired patch'

CABLE_TYPE_OPTION_ID: int = 9960
CABLE_TYPE_LABEL: str = 'CAT6'

ALL_TYPE_IDS: list[int] = [PORT_TYPE_ID, CABLE_TYPE_ID, PLAIN_TYPE_ID]
ALL_OBJECT_IDS: list[int] = [
    OWNER_OBJECT_ID, PEER_OBJECT_ID, CABLE_CI_ID, OTHER_CABLE_CI_ID, PLAIN_OBJECT_ID,
    INACTIVE_CABLE_CI_ID,
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


def _cable_ci_doc(public_id: int, cable_name: str, active: bool = True) -> dict[str, Any]:
    """A CABLE SpecialType CmdbObject carrying its dg-cable-name, the way a user would have filled it."""
    document: dict[str, Any] = _object_doc(public_id, CABLE_TYPE_ID)
    document['active'] = active
    document['fields'] = [
        {'name': CableField.NAME.value, 'value': cable_name, 'type': FieldType.TEXT.value},
        {'name': CableField.TYPE.value, 'value': CABLE_TYPE_LABEL, 'type': FieldType.TEXT.value},
    ]

    return document


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
        _cable_ci_doc(CABLE_CI_ID, CABLE_NAME_SECOND),
        _cable_ci_doc(OTHER_CABLE_CI_ID, CABLE_NAME_FIRST),
        _cable_ci_doc(INACTIVE_CABLE_CI_ID, CABLE_NAME_INACTIVE, active=False),
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


def _fill_cable_ci(database_manager: MongoDatabaseManager, database_name: str, **values: Any) -> None:
    """Gives the seeded Cable CI its dg-cable-* values, the way a user would have filled them in."""
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    objects.update_one(
        {'public_id': CABLE_CI_ID},
        {'$set': {'fields': [
            {'name': name, 'value': value, 'type': FieldType.TEXT.value}
            for name, value in values.items()
        ]}},
    )


@pytest.fixture(name='cable_type_option')
def fixture_cable_type_option(database_manager: MongoDatabaseManager, database_name: str):
    """A CABLE_TYPE CmdbExtendableOption, so an inline connection's cable_type has a label to resolve."""
    options = database_manager.get_collection(CmdbExtendableOption.COLLECTION, database_name)

    options.delete_many({ExtendableOptionKey.PUBLIC_ID.value: CABLE_TYPE_OPTION_ID})
    options.insert_one({
        ExtendableOptionKey.PUBLIC_ID.value: CABLE_TYPE_OPTION_ID,
        ExtendableOptionKey.VALUE.value: CABLE_TYPE_LABEL,
        ExtendableOptionKey.OPTION_TYPE.value: OptionType.CABLE_TYPE.value,
        ExtendableOptionKey.PREDEFINED.value: False,
    })

    yield CABLE_TYPE_OPTION_ID

    options.delete_many({ExtendableOptionKey.PUBLIC_ID.value: CABLE_TYPE_OPTION_ID})


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

        # The write is answered with the same resolved shape a following read returns: the flat cable
        # keys are gone and the values live in the 'cable' block
        assert PortConnectionKey.CABLE_NAME.value not in created
        assert created[CABLE_VIEW_KEY][CableViewKey.SOURCE.value] == CableSource.INLINE.value
        assert created[CABLE_VIEW_KEY][CableViewKey.NAME.value] == 'Patch 1'
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


class TestReadConnectionsOfObject:
    """GET /port_connections/object/<object_id> - the whole cabling of one device in one request"""

    def test_reads_every_connection_of_every_port_of_the_object(self, rest_api) -> None:
        """
        What an object view needs: the panel's internal pairing AND the cable leaving it

        Reading this per port cost one request per port; this is two indexed reads whatever the port
        count is.
        """
        _create(rest_api, [FRONT_PORT_ID, REAR_PORT_ID], connection_type=ConnectionType.INTERNAL.value)
        _create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID])

        response = rest_api.get(f'{ROUTE_URL}/object/{OWNER_OBJECT_ID}')

        assert response.status_code == HTTPStatus.OK
        assert len(response.get_json()) == 2

    def test_an_internal_connection_between_two_own_ports_appears_once(self, rest_api) -> None:
        """
        Both endpoints of a panel's internal pairing are ports of this object

        It is one document and the '$in' matches it once, so the answer must not list it twice - the
        thing a naive per-port loop plus concatenation would get wrong.
        """
        _create(rest_api, [FRONT_PORT_ID, REAR_PORT_ID], connection_type=ConnectionType.INTERNAL.value)

        body = rest_api.get(f'{ROUTE_URL}/object/{OWNER_OBJECT_ID}').get_json()

        assert len(body) == 1
        assert sorted(body[0][PortConnectionKey.ENDPOINTS.value]) == sorted([FRONT_PORT_ID, REAR_PORT_ID])

    def test_the_peer_side_is_included_whichever_end_the_object_owns(self, rest_api) -> None:
        """A cable is found from both of its ends, because the endpoints share one array field."""
        _create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID])

        from_owner = rest_api.get(f'{ROUTE_URL}/object/{OWNER_OBJECT_ID}').get_json()
        from_peer = rest_api.get(f'{ROUTE_URL}/object/{PEER_OBJECT_ID}').get_json()

        assert len(from_owner) == 1
        assert from_owner == from_peer

    def test_an_object_whose_ports_are_all_free_answers_with_an_empty_list(self, rest_api) -> None:
        """'Nothing is cabled here' is a normal state, not a 404."""
        response = rest_api.get(f'{ROUTE_URL}/object/{OWNER_OBJECT_ID}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == []

    def test_an_object_without_ports_answers_with_an_empty_list(self, rest_api) -> None:
        """An object of a type that does not use ports is empty rather than an error."""
        response = rest_api.get(f'{ROUTE_URL}/object/{PLAIN_OBJECT_ID}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == []

    def test_a_missing_object_is_a_404(self, rest_api) -> None:
        """A different answer from 'this device is not cabled', so a typo is distinguishable."""
        response = rest_api.get(f'{ROUTE_URL}/object/{MISSING_OBJECT_ID}')

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_the_answer_matches_the_per_port_reads_it_replaces(self, rest_api) -> None:
        """
        The route is a batching of the per-port reads and must agree with them

        Pinned because the two use different manager methods - one '$in' against one equality - and a
        divergence would show as a panel that disagrees with itself.
        """
        _create(rest_api, [FRONT_PORT_ID, REAR_PORT_ID], connection_type=ConnectionType.INTERNAL.value)
        _create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID])

        per_object = rest_api.get(f'{ROUTE_URL}/object/{OWNER_OBJECT_ID}').get_json()

        per_port: list[dict[str, Any]] = []

        for port_id in (FRONT_PORT_ID, REAR_PORT_ID):
            per_port.extend(rest_api.get(f'{ROUTE_URL}/port/{port_id}').get_json())

        expected_ids = {connection[PortConnectionKey.PUBLIC_ID.value] for connection in per_port}

        assert {connection[PortConnectionKey.PUBLIC_ID.value] for connection in per_object} == expected_ids


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

        assert updated[CABLE_VIEW_KEY][CableViewKey.NAME.value] == 'New'
        assert updated[CABLE_VIEW_KEY][CableViewKey.LENGTH.value] == '3 m'

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


    def test_object_read_ports_manager_error_is_400(self, rest_api, monkeypatch) -> None:
        """
        The object route reads twice, and each read has its own arm

        A failure fetching the object's PORTS is reported as a bad request naming the object, not as
        the connection read's message - the two are different problems.
        """
        monkeypatch.setattr(PortsManager, 'get_ports_of_object', _raiser(PortsManagerGetError('boom')))

        response = rest_api.get(f'{ROUTE_URL}/object/{OWNER_OBJECT_ID}')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'Ports' in response.get_json()['message']

    def test_object_read_connections_manager_error_is_400(self, rest_api, monkeypatch) -> None:
        """The second read's own arm."""
        monkeypatch.setattr(
            PortConnectionsManager, 'get_connections_of_ports',
            _raiser(PortConnectionsManagerGetError('boom')),
        )

        response = rest_api.get(f'{ROUTE_URL}/object/{OWNER_OBJECT_ID}')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'Port connections' in response.get_json()['message']

    def test_object_read_denied_by_the_object_acl_is_403(self, rest_api, monkeypatch) -> None:
        """
        The route is keyed by an object, so the object's own READ permission governs it

        Exactly as /ports/object/<id> does - what Q13 leaves unchecked is the PEER end of a
        connection, not the device being asked about.
        """
        monkeypatch.setattr(PortsManager, 'get_ports_of_object', _raiser(AccessDeniedError('nope')))

        assert rest_api.get(f'{ROUTE_URL}/object/{OWNER_OBJECT_ID}').status_code == HTTPStatus.FORBIDDEN

    def test_object_read_unexpected_error_is_500(self, rest_api, monkeypatch) -> None:
        """Not a 400: nothing is wrong with the request."""
        monkeypatch.setattr(PortsManager, 'get_ports_of_object', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/object/{OWNER_OBJECT_ID}').status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR


# -------------------------------------------------------------------------------------------------------------------- #
#                                              THE RESOLVED CABLE BLOCK                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCableIsDescribedOnce:
    """
    A cable lives in ONE place, and a client reads it in one shape

    The write half refuses the inline fields alongside a Cable CI, so the five values can not be
    duplicated between the link and the asset that IS the cable and then drift apart. The read half
    resolves whichever of the two the connection uses into a single 'cable' block.
    """

    def test_inline_fields_alongside_a_cable_ci_are_refused(self, rest_api) -> None:
        """The duplication the design forbids, refused at the door"""
        response = _create(
            rest_api, [SERVER_PORT_ID, FRONT_PORT_ID],
            cable_ci_id=CABLE_CI_ID, cable_name='Patch 1',
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert PortConnectionKey.CABLE_NAME.value in response.get_json()['message']
        assert str(CABLE_CI_ID) in response.get_json()['message']

    def test_every_duplicated_field_is_named_in_one_message(self, rest_api) -> None:
        """One response, one fixed payload - not a rule discovered per request"""
        response = _create(
            rest_api, [SERVER_PORT_ID, FRONT_PORT_ID],
            cable_ci_id=CABLE_CI_ID, cable_name='Patch 1', cable_color='blue',
        )

        message: str = response.get_json()['message']

        assert PortConnectionKey.CABLE_NAME.value in message
        assert PortConnectionKey.CABLE_COLOR.value in message

    def test_a_cable_ci_alone_is_accepted(self, rest_api) -> None:
        """Scenario B: the CI owns the values and the connection only points at it"""
        response = _create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID], cable_ci_id=CABLE_CI_ID)

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)

    def test_an_update_refuses_the_duplication_too(self, rest_api) -> None:
        """Both write routes hold the rule; only one of them would be a hole in it"""
        new_id: int = _created_id(_create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID], cable_name='Patch 1'))

        response = rest_api.put(
            f'{ROUTE_URL}/{new_id}',
            json={'cable_ci_id': CABLE_CI_ID, 'cable_name': 'Patch 1'},
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_a_link_can_be_handed_over_to_a_cable_ci_in_one_write(self, rest_api) -> None:
        """
        Switching between the two ways of describing a cable is an ordinary update

        The inline values go, the reference arrives, and the block now reads from the CI.
        """
        new_id: int = _created_id(_create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID], cable_name='Patch 1'))

        response = rest_api.put(f'{ROUTE_URL}/{new_id}', json={'cable_ci_id': CABLE_CI_ID})

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)

        block = rest_api.get(f'{ROUTE_URL}/{new_id}').get_json()['result'][CABLE_VIEW_KEY]

        assert block[CableViewKey.SOURCE.value] == CableSource.CI.value
        assert block[CableViewKey.CABLE_CI_ID.value] == CABLE_CI_ID

    def test_the_block_carries_the_cable_cis_own_values(
            self, rest_api, database_manager, database_name) -> None:
        """The point of linking a CI: the asset owns the values and the link shows them"""
        _fill_cable_ci(database_manager, database_name, **{
            CableField.NAME.value: 'CAB-000471',
            CableField.TYPE.value: CABLE_TYPE_LABEL,
            CableField.LENGTH.value: '3 m',
            CableField.COLOR.value: 'blue',
            CableField.DESCRIPTION.value: 'Rack 12 -> Rack 14',
        })
        new_id: int = _created_id(_create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID], cable_ci_id=CABLE_CI_ID))

        block = rest_api.get(f'{ROUTE_URL}/{new_id}').get_json()['result'][CABLE_VIEW_KEY]

        assert block[CableViewKey.SOURCE.value] == CableSource.CI.value
        assert block[CableViewKey.NAME.value] == 'CAB-000471'
        assert block[CableViewKey.TYPE.value] == CABLE_TYPE_LABEL
        assert block[CableViewKey.TYPE_ID.value] is None
        assert block[CableViewKey.LENGTH.value] == '3 m'
        assert block[CableViewKey.COLOR.value] == 'blue'
        assert block[CableViewKey.DESCRIPTION.value] == 'Rack 12 -> Rack 14'

    def test_an_inline_cable_type_is_reported_as_its_label(self, rest_api, cable_type_option) -> None:
        """
        The stored value is a CABLE_TYPE option id; a client should not have to resolve it

        Both keys are filled here, unlike the CI case: the id exists, so it is reported alongside the
        label the edit form needs.
        """
        new_id: int = _created_id(_create(
            rest_api, [SERVER_PORT_ID, FRONT_PORT_ID], cable_name='Patch 1', cable_type=cable_type_option,
        ))

        block = rest_api.get(f'{ROUTE_URL}/{new_id}').get_json()['result'][CABLE_VIEW_KEY]

        assert block[CableViewKey.SOURCE.value] == CableSource.INLINE.value
        assert block[CableViewKey.TYPE.value] == CABLE_TYPE_LABEL
        assert block[CableViewKey.TYPE_ID.value] == cable_type_option

    def test_a_deleted_cable_ci_is_reported_and_the_link_survives(
            self, rest_api, database_manager, database_name) -> None:
        """
        The soft reference of step 10: reported, never cascaded

        The two ports are still patched together, so the connection stays - only the asset record
        describing its cable is gone.
        """
        new_id: int = _created_id(_create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID], cable_ci_id=CABLE_CI_ID))

        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        objects.delete_one({'public_id': CABLE_CI_ID})

        response = rest_api.get(f'{ROUTE_URL}/{new_id}')

        assert response.status_code == HTTPStatus.OK

        block = response.get_json()['result'][CABLE_VIEW_KEY]

        assert block[CableViewKey.CABLE_CI_ID.value] == CABLE_CI_ID
        assert block[CableViewKey.RESOLVED.value] is False
        assert block[CableViewKey.NAME.value] is None

    def test_an_internal_connection_has_no_cable_block(self, rest_api) -> None:
        """A panel's front-to-rear pairing is not a piece of cabling, and says so once"""
        new_id: int = _created_id(_create(
            rest_api, [FRONT_PORT_ID, REAR_PORT_ID], connection_type=ConnectionType.INTERNAL.value,
        ))

        assert rest_api.get(f'{ROUTE_URL}/{new_id}').get_json()['result'][CABLE_VIEW_KEY] is None

    def test_every_read_route_answers_in_the_same_shape(
            self, rest_api, database_manager, database_name) -> None:
        """
        The single read, the per-port read and the per-object read are one contract

        A client that renders a device's cabling must not have to branch on which route produced it.
        """
        _fill_cable_ci(database_manager, database_name, **{CableField.NAME.value: 'CAB-000471'})
        new_id: int = _created_id(_create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID], cable_ci_id=CABLE_CI_ID))

        single = rest_api.get(f'{ROUTE_URL}/{new_id}').get_json()['result']
        per_port = rest_api.get(f'{ROUTE_URL}/port/{FRONT_PORT_ID}').get_json()[0]
        per_object = rest_api.get(f'{ROUTE_URL}/object/{OWNER_OBJECT_ID}').get_json()[0]

        for connection in (single, per_port, per_object):
            assert PortConnectionKey.CABLE_NAME.value not in connection
            assert PortConnectionKey.CABLE_CI_ID.value not in connection
            assert connection[CABLE_VIEW_KEY][CableViewKey.NAME.value] == 'CAB-000471'


# -------------------------------------------------------------------------------------------------------------------- #
#                                              THE WRITE BODY'S SCHEMA                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TestWriteSchema:
    """
    What the routes accept as a body at all

    Both write routes validate against the write schema before any handler runs. Until 2026-09-08 they
    did not: the document schema existed but nothing enforced it, so a value of the wrong type was
    stored as-is under a key the schema declares a string.
    """

    def test_a_number_where_a_cable_field_declares_text_is_refused(self, rest_api) -> None:
        """
        The gap the schema closes

        cable_length is text on purpose - '5 m', '2.5 m' - and a bare 5 used to be stored verbatim.
        """
        response = _create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID], cable_length=5)

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_a_non_integer_cable_ci_id_is_refused(self, rest_api) -> None:
        """The reference is a public_id, and a string could never resolve to one"""
        response = _create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID], cable_ci_id='nine')

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_the_update_body_is_validated_too(self, rest_api) -> None:
        """One validated route and one unvalidated one would just move the hole"""
        new_id: int = _created_id(_create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID]))

        response = rest_api.put(f'{ROUTE_URL}/{new_id}', json={'cable_color': 42})

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_a_server_owned_key_in_the_body_never_reaches_the_handler(self, rest_api, seeded) -> None:
        """
        Purged rather than ignored

        The write schema does not declare the audit fields, and the validator purges what it does not
        declare - so a body claiming another author cannot even be read by the route.
        """
        response = rest_api.post(f'{ROUTE_URL}/', json={
            **_payload([SERVER_PORT_ID, FRONT_PORT_ID], cable_name='Patch 1'),
            'author_id': 4242,
            'creation_time': 'whenever',
        })

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)

        stored = seeded.find_one({PortConnectionKey.PUBLIC_ID.value: _created_id(response)})

        assert stored[PortConnectionKey.AUTHOR_ID.value] != 4242
        assert isinstance(stored[PortConnectionKey.CREATION_TIME.value], datetime)

    def test_an_unusable_endpoint_list_still_gets_its_own_message(self, rest_api) -> None:
        """
        endpoints stays UNTYPED in the write schema on purpose

        A type rule would refuse it first with the decorator's generic wording, replacing the message
        that names the actual rule.
        """
        response = _create(rest_api, [SERVER_PORT_ID])

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'endpoints' in response.get_json()['message'].lower()

    def test_an_unknown_connection_type_still_gets_its_own_message(self, rest_api) -> None:
        """Same reason: the validator lists the allowed types, a type rule could not"""
        response = _create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID], connection_type='WIRELESS')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'WIRELESS' in response.get_json()['message']

    def test_the_write_schema_accepts_exactly_the_documented_request_keys(self) -> None:
        """
        The schema and ConnectionRequestKey are two statements of the same list

        They live in different layers - the schema may not import the route constants - so nothing but
        this assertion keeps them from drifting.
        """
        assert set(get_cmdb_port_connection_write_schema()) == {
            key.value for key in ConnectionRequestKey
        }


# -------------------------------------------------------------------------------------------------------------------- #
#                                    GET /port_connections/cables/unassigned/                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class TestUnassignedCablePicker:
    """
    The picker behind a connection's ``cable_ci_id``

    Two rules and three parameters: only CABLE-marked objects, never a cable another connection
    already claims, ``?connection_id=`` to keep the edited connection's own cable, ``?search=`` on the
    cable name, and the standard pager - whose `sort` this route defaults to the cable name.
    """

    @staticmethod
    def _get(rest_api, query: str = ''):
        """GETs the picker, optionally with a query string."""
        return rest_api.get(f'{ROUTE_URL}{UNASSIGNED_ROUTE}{query}')

    @staticmethod
    def _ids(response) -> list[int]:
        """The public_ids of one page, in the order the route returned them."""
        return [row['public_id'] for row in response.get_json()['results']]

    def test_lists_every_unclaimed_cable_with_the_pager_envelope(self, rest_api) -> None:
        """A GetMultiResponse: the rows, the total and the echoed parameters"""
        response = self._get(rest_api)

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert set(self._ids(response)) == {CABLE_CI_ID, OTHER_CABLE_CI_ID, INACTIVE_CABLE_CI_ID}
        assert body['total'] == 3
        assert body['parameters']['sort'] == 'fields.dg-cable-name'

    def test_only_cable_types_are_offered(self, rest_api) -> None:
        """An object of an ordinary type is not a cable, whatever it is called"""
        assert PLAIN_OBJECT_ID not in self._ids(self._get(rest_api))

    def test_a_row_carries_the_cable_name_and_its_type(self, rest_api) -> None:
        """The picker draws the name; the CmdbType label is what tells two cable types apart"""
        row = next(
            row for row in self._get(rest_api).get_json()['results']
            if row['public_id'] == OTHER_CABLE_CI_ID
        )

        assert row['name'] == CABLE_NAME_FIRST
        assert row['cable_type'] == CABLE_TYPE_LABEL
        assert row['type_id'] == CABLE_TYPE_ID
        assert row['type_label'] == f'Connection Type {CABLE_TYPE_ID}'
        assert row['active'] is True

    def test_rows_are_ordered_by_cable_name_by_default(self, rest_api) -> None:
        """Name-ascending and case-folded: binary collation would put 'Zeta patch' first"""
        assert self._ids(self._get(rest_api)) == [
            OTHER_CABLE_CI_ID, INACTIVE_CABLE_CI_ID, CABLE_CI_ID,
        ]

    def test_an_explicit_sort_is_honoured(self, rest_api) -> None:
        """The default applies only when the caller sent no ?sort= of its own"""
        response = self._get(rest_api, '?sort=public_id&order=1')

        assert response.get_json()['parameters']['sort'] == 'public_id'
        assert self._ids(response) == [CABLE_CI_ID, OTHER_CABLE_CI_ID, INACTIVE_CABLE_CI_ID]

    def test_a_claimed_cable_is_not_offered(self, rest_api) -> None:
        """Cabling a connection to a CI takes it out of the picker"""
        _create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID], cable_ci_id=CABLE_CI_ID)

        response = self._get(rest_api)

        assert CABLE_CI_ID not in self._ids(response)
        assert response.get_json()['total'] == 2

    def test_resolving_the_connection_offers_the_cable_again(self, rest_api) -> None:
        """The cable is free the moment the connection is gone - nothing else is written"""
        created = _create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID], cable_ci_id=CABLE_CI_ID)
        rest_api.delete(f'{ROUTE_URL}/{_created_id(created)}')

        assert CABLE_CI_ID in self._ids(self._get(rest_api))

    def test_connection_id_keeps_the_edited_connections_own_cable(self, rest_api) -> None:
        """What an edit form needs: its current value is in the list it renders"""
        created = _create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID], cable_ci_id=CABLE_CI_ID)
        connection_id: int = _created_id(created)

        ids = self._ids(self._get(rest_api, f'?connection_id={connection_id}'))

        assert CABLE_CI_ID in ids
        assert OTHER_CABLE_CI_ID in ids

    def test_connection_id_hides_the_cables_of_other_connections(self, rest_api) -> None:
        """Only the addressed connection's own cable comes back, not every claimed one"""
        first = _create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID], cable_ci_id=CABLE_CI_ID)
        _create(rest_api, [SWITCH_PORT_ID, REAR_PORT_ID], cable_ci_id=OTHER_CABLE_CI_ID)

        ids = self._ids(self._get(rest_api, f'?connection_id={_created_id(first)}'))

        assert CABLE_CI_ID in ids
        assert OTHER_CABLE_CI_ID not in ids

    def test_unknown_connection_id_returns_404(self, rest_api) -> None:
        """A question about a connection that does not exist is answered, not ignored"""
        assert self._get(rest_api, '?connection_id=987654').status_code == HTTPStatus.NOT_FOUND

    def test_search_matches_the_cable_name_case_insensitively(self, rest_api) -> None:
        """The picker's search box: a literal substring of the name, in any case"""
        response = self._get(rest_api, '?search=ALPHA')

        assert self._ids(response) == [OTHER_CABLE_CI_ID]
        assert response.get_json()['total'] == 1

    def test_search_without_a_match_answers_an_empty_page(self, rest_api) -> None:
        """An empty result, not an error"""
        response = self._get(rest_api, '?search=nothing-like-this')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['results'] == []
        assert response.get_json()['total'] == 0

    def test_the_page_size_and_page_are_honoured(self, rest_api) -> None:
        """Pagination is the standard pager: total counts every candidate, results one page"""
        first_page = self._get(rest_api, '?limit=1&page=1')
        second_page = self._get(rest_api, '?limit=1&page=2')

        assert first_page.get_json()['total'] == 3
        assert self._ids(first_page) == [OTHER_CABLE_CI_ID]
        assert self._ids(second_page) == [INACTIVE_CABLE_CI_ID]

    def test_a_caller_filter_narrows_the_candidates(self, rest_api) -> None:
        """The rules are appended behind ?filter=, so a filter can only narrow the list"""
        response = self._get(rest_api, f'?filter={{"public_id": {OTHER_CABLE_CI_ID}}}')

        assert self._ids(response) == [OTHER_CABLE_CI_ID]

    def test_a_caller_filter_can_not_widen_past_the_rules(self, rest_api) -> None:
        """Naming a claimed cable in the filter does not bring it back"""
        _create(rest_api, [SERVER_PORT_ID, FRONT_PORT_ID], cable_ci_id=CABLE_CI_ID)

        response = self._get(rest_api, f'?filter={{"public_id": {CABLE_CI_ID}}}')

        assert response.get_json()['results'] == []

    def test_inactive_cables_are_hidden_when_the_cookie_asks_for_active_objects(self, rest_api) -> None:
        """The picker honours the active-objects setting exactly as the object list does"""
        ids = self._ids(self._get(rest_api, '?onlyActiveObjCookie=true'))

        assert INACTIVE_CABLE_CI_ID not in ids
        assert set(ids) == {CABLE_CI_ID, OTHER_CABLE_CI_ID}

    def test_head_answers_without_a_body(self, rest_api) -> None:
        """HEAD is the pager's count-only form"""
        response = rest_api.head(f'{ROUTE_URL}{UNASSIGNED_ROUTE}')

        assert response.status_code == HTTPStatus.OK
        assert not response.get_data()


class TestUnassignedCablePickerErrorTails:
    """Each read behind the picker maps to its own refusal rather than one blanket 500."""

    @pytest.mark.parametrize('manager, method, error, expected', [
        (PortConnectionsManager, 'get_assigned_cable_ci_ids',
         PortConnectionsManagerGetError('boom'), HTTPStatus.BAD_REQUEST),
        (TypesManager, 'get_type_ids_of_special_type',
         TypesManagerGetError('boom'), HTTPStatus.BAD_REQUEST),
        (ObjectsManager, 'iterate_query',
         ObjectsManagerIterationError('boom'), HTTPStatus.BAD_REQUEST),
        (ObjectsManager, 'iterate_query', RuntimeError('boom'), HTTPStatus.INTERNAL_SERVER_ERROR),
    ], ids=['claimed-cables', 'cable-types', 'candidates', 'unexpected'])
    def test_a_failing_read_maps_to_its_own_status(
            self, rest_api, monkeypatch, manager: Any, method: str, error: Exception, expected: int,
    ) -> None:
        """The three reads are told apart, and anything else is a 500"""
        monkeypatch.setattr(manager, method, _raiser(error))

        assert rest_api.get(f'{ROUTE_URL}{UNASSIGNED_ROUTE}').status_code == expected
