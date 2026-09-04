# DATAGERRY - OpenSource Enterprise CMDB
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
Unit tests for the CmdbPortConnection route guards

Pure tests: the managers are mocks and every helper is called inside a Flask request context, because
they abort.

Two things are worth pinning above the rest. First, that the cable-CI key is OMITTED rather than
nulled when a request names none - the unique index guaranteeing one CI per connection is filtered on
that key's presence, so a null would make the second CI-less connection in the installation a
duplicate. Second, that ``duplicate_key_abort`` reports the DATABASE's refusal with the same wording
the pre-checks use: the pre-checks are reads followed by writes and cannot survive a race, so the
message a losing request receives has to come from there
"""
from typing import Any
from unittest.mock import MagicMock

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.port_model import PortKey
from cmdb.models.port_connection_model import ConnectionType, PortConnectionKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model import TypeSchemaKey
from cmdb.interface.rest_api.routes.port_connection_routes.port_connection_route_constants import (
    ConnectionRequestKey,
    ConnectionRight,
)
from cmdb.interface.rest_api.routes.port_connection_routes.port_connection_route_helper import (
    build_cable_info,
    build_connection_candidate,
    duplicate_key_abort,
    enforce_cable_ci_free,
    enforce_connection_shape,
    enforce_endpoints_free,
    get_connection_or_abort,
    get_port_or_abort,
    get_requested_connection_type_or_abort,
    refuse_identity_change,
)
# -------------------------------------------------------------------------------------------------------------------- #
# Several tests take the 'ctx' fixture purely for its side effect - it opens the request context the
# helpers' abort() needs - and never touch what it yields
# pylint: disable=unused-argument
# -------------------------------------------------------------------------------------------------------------------- #

HTTP_BAD_REQUEST: int = 400
HTTP_NOT_FOUND: int = 404

CONNECTION_ID: int = 6100
OTHER_CONNECTION_ID: int = 6101
PORT_A: int = 6201
PORT_B: int = 6202
PORT_C: int = 6203
CABLE_CI_ID: int = 6301
CABLE_TYPE_ID: int = 6401


@pytest.fixture(name='ctx')
def fixture_ctx():
    """A request context, so the helpers' abort() has somewhere to raise from."""
    app = Flask(__name__)

    with app.test_request_context('/port_connections/'):
        yield


def _connection(**overrides: Any) -> dict[str, Any]:
    """A stored connection document."""
    connection: dict[str, Any] = {
        PortConnectionKey.PUBLIC_ID.value: CONNECTION_ID,
        PortConnectionKey.ENDPOINTS.value: [PORT_A, PORT_B],
        PortConnectionKey.CONNECTION_TYPE.value: ConnectionType.CABLE.value,
    }
    connection.update(overrides)

    return connection


def _connections_manager(
        connection: dict[str, Any] | None = None,
        by_type: dict[str, Any] | None = None,
        by_cable_ci: dict[str, Any] | None = None) -> MagicMock:
    """A PortConnectionsManager stand-in."""
    manager = MagicMock(name='port_connections_manager')
    manager.get_item.return_value = connection
    manager.get_connection_of_port_by_type.return_value = by_type
    manager.get_connection_by_cable_ci.return_value = by_cable_ci

    return manager


def _ports_manager(found: list[int] | None = None, port: dict[str, Any] | None = None) -> MagicMock:
    """A PortsManager stand-in whose find() answers with the given port ids."""
    manager = MagicMock(name='ports_manager')
    manager.find.return_value = [{PortKey.PUBLIC_ID.value: port_id} for port_id in (found or [])]
    manager.get_item.return_value = port

    return manager


def _cable_managers() -> tuple[MagicMock, MagicMock]:
    """ObjectsManager / TypesManager stand-ins that resolve a valid Cable CI."""
    objects_manager = MagicMock(name='objects_manager')
    objects_manager.get_object.return_value = {
        CmdbObjectKey.PUBLIC_ID.value: CABLE_CI_ID, CmdbObjectKey.TYPE_ID.value: 9,
    }

    types_manager = MagicMock(name='types_manager')
    types_manager.get_type.return_value = {TypeSchemaKey.SPECIAL_TYPE: SpecialType.CABLE.value}

    return objects_manager, types_manager


# -------------------------------------------------------------------------------------------------------------------- #
#                                                      lookups                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestLookups:
    """Reading the addressed row, or answering 404."""

    def test_a_stored_connection_is_returned(self, ctx) -> None:
        """The ordinary case"""
        stored = _connection()

        assert get_connection_or_abort(_connections_manager(stored), CONNECTION_ID) is stored

    def test_a_missing_connection_is_a_404(self, ctx) -> None:
        """Addressing a row that does not exist is not a validation failure"""
        with pytest.raises(HTTPException) as raised:
            get_connection_or_abort(_connections_manager(None), CONNECTION_ID)

        assert raised.value.code == HTTP_NOT_FOUND

    def test_a_missing_port_is_a_404(self, ctx) -> None:
        """
        Asking for the connections of a port that does not exist is a 404, not an empty list

        An empty list means 'this port is free', which is a different answer - a client could not tell
        a free port from a typo in the id.
        """
        with pytest.raises(HTTPException) as raised:
            get_port_or_abort(_ports_manager(port=None), PORT_A)

        assert raised.value.code == HTTP_NOT_FOUND

    def test_an_existing_port_is_returned(self, ctx) -> None:
        """The ordinary case"""
        port = {PortKey.PUBLIC_ID.value: PORT_A}

        assert get_port_or_abort(_ports_manager(port=port), PORT_A) is port


# -------------------------------------------------------------------------------------------------------------------- #
#                                              the requested connection type                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class TestRequestedConnectionType:
    """Which kind of link a create is asking for."""

    @pytest.mark.parametrize('connection_type', [c.value for c in ConnectionType])
    def test_a_known_type_is_read_back(self, ctx, connection_type: str) -> None:
        """The two the enum names"""
        payload = {ConnectionRequestKey.CONNECTION_TYPE.value: connection_type}

        assert get_requested_connection_type_or_abort(payload) == connection_type

    @pytest.mark.parametrize('raw', [None, '', 'cable', 'CABEL', 5], ids=str)
    def test_a_missing_or_unknown_type_is_a_400(self, ctx, raw: Any) -> None:
        """
        Deliberately NOT defaulted

        Guessing CABLE for a typo would create the wrong kind of link - one that falls under the wrong
        unique index and gets the wrong cardinality guarantee.
        """
        with pytest.raises(HTTPException) as raised:
            get_requested_connection_type_or_abort({ConnectionRequestKey.CONNECTION_TYPE.value: raw})

        assert raised.value.code == HTTP_BAD_REQUEST


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  the shape guard                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestEnforceConnectionShape:
    """The pure rules plus the two that need a read, reported together."""

    def test_a_valid_cable_connection_passes(self, ctx) -> None:
        """The ordinary case"""
        objects_manager, types_manager = _cable_managers()

        enforce_connection_shape(
            _ports_manager([PORT_A, PORT_B]), objects_manager, types_manager,
            ConnectionType.CABLE.value,
            {ConnectionRequestKey.ENDPOINTS.value: [PORT_A, PORT_B]},
        )

    def test_a_self_connection_is_a_400(self, ctx) -> None:
        """The rule no index can hold, because [5, 5] dedupes inside one document"""
        objects_manager, types_manager = _cable_managers()

        with pytest.raises(HTTPException) as raised:
            enforce_connection_shape(
                _ports_manager([PORT_A]), objects_manager, types_manager,
                ConnectionType.CABLE.value,
                {ConnectionRequestKey.ENDPOINTS.value: [PORT_A, PORT_A]},
            )

        assert raised.value.code == HTTP_BAD_REQUEST
        assert 'itself' in raised.value.description

    def test_a_missing_endpoint_is_a_400(self, ctx) -> None:
        """A connection may not be created against a port that does not exist"""
        objects_manager, types_manager = _cable_managers()

        with pytest.raises(HTTPException) as raised:
            enforce_connection_shape(
                _ports_manager([PORT_A]), objects_manager, types_manager,
                ConnectionType.CABLE.value,
                {ConnectionRequestKey.ENDPOINTS.value: [PORT_A, PORT_B]},
            )

        assert str(PORT_B) in raised.value.description

    def test_cable_info_on_an_internal_connection_is_a_400(self, ctx) -> None:
        """A panel's internal pairing has no cable"""
        objects_manager, types_manager = _cable_managers()

        with pytest.raises(HTTPException) as raised:
            enforce_connection_shape(
                _ports_manager([PORT_A, PORT_B]), objects_manager, types_manager,
                ConnectionType.INTERNAL.value,
                {
                    ConnectionRequestKey.ENDPOINTS.value: [PORT_A, PORT_B],
                    ConnectionRequestKey.CABLE_NAME.value: 'Patch 1',
                },
            )

        assert ConnectionRequestKey.CABLE_NAME.value in raised.value.description

    def test_a_cable_ci_of_another_type_is_a_400(self, ctx) -> None:
        """An arbitrary object must not be stored and rendered as a cable"""
        objects_manager, types_manager = _cable_managers()
        types_manager.get_type.return_value = {TypeSchemaKey.SPECIAL_TYPE: SpecialType.RACK.value}

        with pytest.raises(HTTPException) as raised:
            enforce_connection_shape(
                _ports_manager([PORT_A, PORT_B]), objects_manager, types_manager,
                ConnectionType.CABLE.value,
                {
                    ConnectionRequestKey.ENDPOINTS.value: [PORT_A, PORT_B],
                    ConnectionRequestKey.CABLE_CI_ID.value: CABLE_CI_ID,
                },
            )

        assert 'not a Cable' in raised.value.description

    def test_every_reason_is_reported_in_one_message(self, ctx) -> None:
        """A caller fixes one payload rather than discovering the rules one request at a time"""
        objects_manager, types_manager = _cable_managers()
        objects_manager.get_object.return_value = None

        with pytest.raises(HTTPException) as raised:
            enforce_connection_shape(
                _ports_manager([]), objects_manager, types_manager,
                ConnectionType.INTERNAL.value,
                {
                    ConnectionRequestKey.ENDPOINTS.value: [PORT_A, PORT_B],
                    ConnectionRequestKey.CABLE_CI_ID.value: CABLE_CI_ID,
                },
            )

        assert raised.value.description.count('|') >= 2


# -------------------------------------------------------------------------------------------------------------------- #
#                                        the readable cardinality pre-checks                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class TestEnforceEndpointsFree:
    """Not the guarantee - the readable form of it."""

    def test_two_free_ports_pass(self, ctx) -> None:
        """The ordinary case"""
        enforce_endpoints_free(_connections_manager(), ConnectionType.CABLE.value, [PORT_A, PORT_B])

    def test_an_occupied_endpoint_is_a_400_naming_the_port(self, ctx) -> None:
        """
        The caller has to learn WHICH of the two ports is the problem

        A bare 'duplicate key' would leave it guessing between the two ids it just sent.
        """
        manager = _connections_manager(by_type=_connection(**{
            PortConnectionKey.ENDPOINTS.value: [PORT_A, PORT_C],
        }))

        with pytest.raises(HTTPException) as raised:
            enforce_endpoints_free(manager, ConnectionType.CABLE.value, [PORT_A, PORT_B])

        assert str(PORT_A) in raised.value.description
        assert 'cable connection' in raised.value.description

    def test_an_already_connected_pair_reports_the_pair(self, ctx) -> None:
        """
        A different mistake from 'this port is in use elsewhere', so it gets its own message

        Telling a user their two ports are already connected is actionable; telling them one port is
        occupied when it is occupied BY THE OTHER ONE is confusing.
        """
        manager = _connections_manager(by_type=_connection())

        with pytest.raises(HTTPException) as raised:
            enforce_endpoints_free(manager, ConnectionType.CABLE.value, [PORT_A, PORT_B])

        assert 'already connected' in raised.value.description

    def test_the_internal_refusal_has_its_own_wording(self, ctx) -> None:
        """A panel Port pairs with exactly one counterpart, which is not a cabling problem"""
        manager = _connections_manager(by_type=_connection(**{
            PortConnectionKey.ENDPOINTS.value: [PORT_A, PORT_C],
            PortConnectionKey.CONNECTION_TYPE.value: ConnectionType.INTERNAL.value,
        }))

        with pytest.raises(HTTPException) as raised:
            enforce_endpoints_free(manager, ConnectionType.INTERNAL.value, [PORT_A, PORT_B])

        assert 'internal connection' in raised.value.description

    def test_both_ends_are_checked(self, ctx) -> None:
        """A port occupied at the SECOND position must be refused too"""
        manager = _connections_manager()
        manager.get_connection_of_port_by_type.side_effect = lambda port_id, _type: (
            _connection(**{PortConnectionKey.ENDPOINTS.value: [PORT_B, PORT_C]})
            if port_id == PORT_B else None
        )

        with pytest.raises(HTTPException) as raised:
            enforce_endpoints_free(manager, ConnectionType.CABLE.value, [PORT_A, PORT_B])

        assert str(PORT_B) in raised.value.description


class TestEnforceCableCiFree:
    """One inventoried cable belongs to at most one connection."""

    def test_an_unused_cable_ci_passes(self, ctx) -> None:
        """The ordinary case"""
        enforce_cable_ci_free(_connections_manager(), CABLE_CI_ID)

    def test_no_cable_ci_costs_no_read(self, ctx) -> None:
        """Scenario A - cable info with no CI at all - is the common case"""
        manager = _connections_manager()

        enforce_cable_ci_free(manager, None)

        manager.get_connection_by_cable_ci.assert_not_called()

    def test_a_claimed_cable_ci_is_a_400_naming_the_holder(self, ctx) -> None:
        """The user has to be able to find the link already using that cable"""
        manager = _connections_manager(by_cable_ci=_connection(**{
            PortConnectionKey.PUBLIC_ID.value: OTHER_CONNECTION_ID,
        }))

        with pytest.raises(HTTPException) as raised:
            enforce_cable_ci_free(manager, CABLE_CI_ID)

        assert str(OTHER_CONNECTION_ID) in raised.value.description

    def test_a_connection_may_re_assert_its_own_cable_ci(self, ctx) -> None:
        """
        These routes take the whole connection

        A client that round-trips a GET must not be punished for sending the field back unchanged.
        """
        manager = _connections_manager(by_cable_ci=_connection())

        enforce_cable_ci_free(manager, CABLE_CI_ID, exclude_id=CONNECTION_ID)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  the immutability                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestRefuseIdentityChange:
    """What a connection joins can not be edited."""

    def test_a_payload_without_the_identity_fields_passes(self, ctx) -> None:
        """An update naming only cable information is the ordinary case"""
        refuse_identity_change(_connection(), {ConnectionRequestKey.CABLE_NAME.value: 'Patch 1'})

    def test_repeating_the_stored_values_is_allowed(self, ctx) -> None:
        """A client round-tripping a GET sends the whole document back"""
        refuse_identity_change(_connection(), {
            ConnectionRequestKey.ENDPOINTS.value: [PORT_A, PORT_B],
            ConnectionRequestKey.CONNECTION_TYPE.value: ConnectionType.CABLE.value,
        })

    def test_the_opposite_order_is_the_same_pair(self, ctx) -> None:
        """
        The link is undirected, so the spelling of the pair must not read as a change

        A client that received [3, 10] and sends back [10, 3] named the same two ports.
        """
        refuse_identity_change(_connection(), {
            ConnectionRequestKey.ENDPOINTS.value: [PORT_B, PORT_A],
        })

    def test_changing_an_endpoint_is_a_400(self, ctx) -> None:
        """
        Refused rather than ignored, so a client can not discover its edit did nothing

        Moving an endpoint would drop the connection onto a port whose cardinality slot was never
        checked for it - a re-cable is a delete plus a create.
        """
        with pytest.raises(HTTPException) as raised:
            refuse_identity_change(_connection(), {
                ConnectionRequestKey.ENDPOINTS.value: [PORT_A, PORT_C],
            })

        assert raised.value.code == HTTP_BAD_REQUEST
        assert ConnectionRequestKey.ENDPOINTS.value in raised.value.description

    def test_changing_the_connection_type_is_a_400(self, ctx) -> None:
        """It would move the row between the two partial unique indexes"""
        with pytest.raises(HTTPException) as raised:
            refuse_identity_change(_connection(), {
                ConnectionRequestKey.CONNECTION_TYPE.value: ConnectionType.INTERNAL.value,
            })

        assert ConnectionRequestKey.CONNECTION_TYPE.value in raised.value.description


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 building the row                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBuildingTheDocument:
    """What a write actually stores."""

    def test_every_cable_field_is_carried(self) -> None:
        """The cable info a connection holds when it inventories no CI"""
        cable_info = build_cable_info({
            ConnectionRequestKey.CABLE_NAME.value: 'Patch 1',
            ConnectionRequestKey.CABLE_TYPE.value: CABLE_TYPE_ID,
            ConnectionRequestKey.CABLE_LENGTH.value: '2.5 m',
            ConnectionRequestKey.CABLE_COLOR.value: 'blue',
            ConnectionRequestKey.CABLE_DESCRIPTION.value: 'Floor duct',
        })

        assert cable_info == {
            PortConnectionKey.CABLE_NAME.value: 'Patch 1',
            PortConnectionKey.CABLE_TYPE.value: CABLE_TYPE_ID,
            PortConnectionKey.CABLE_LENGTH.value: '2.5 m',
            PortConnectionKey.CABLE_COLOR.value: 'blue',
            PortConnectionKey.CABLE_DESCRIPTION.value: 'Floor duct',
        }

    def test_an_absent_cable_ci_key_is_omitted_not_nulled(self) -> None:
        """
        The trap this whole design works around

        The unique index on 'cable_ci_id' is filtered on the key's PRESENCE, so writing null would put
        every CI-less connection into it and the second one would be refused as a duplicate.
        """
        assert PortConnectionKey.CABLE_CI_ID.value not in build_cable_info({})

    def test_an_explicit_null_cable_ci_is_omitted_too(self) -> None:
        """A client echoing the whole document back sends null for what it does not use"""
        cable_info = build_cable_info({ConnectionRequestKey.CABLE_CI_ID.value: None})

        assert PortConnectionKey.CABLE_CI_ID.value not in cable_info

    def test_a_named_cable_ci_is_carried(self) -> None:
        """The other half of the same rule"""
        cable_info = build_cable_info({ConnectionRequestKey.CABLE_CI_ID.value: CABLE_CI_ID})

        assert cable_info[PortConnectionKey.CABLE_CI_ID.value] == CABLE_CI_ID

    def test_the_candidate_carries_the_endpoints_and_the_type(self) -> None:
        """The identity and the audit fields are the caller's, never the payload's"""
        candidate = build_connection_candidate(
            [PORT_A, PORT_B], ConnectionType.CABLE.value,
            {ConnectionRequestKey.CABLE_NAME.value: 'Patch 1'},
        )

        assert candidate[PortConnectionKey.ENDPOINTS.value] == [PORT_A, PORT_B]
        assert candidate[PortConnectionKey.CONNECTION_TYPE.value] == ConnectionType.CABLE.value
        assert PortConnectionKey.PUBLIC_ID.value not in candidate
        assert PortConnectionKey.AUTHOR_ID.value not in candidate


# -------------------------------------------------------------------------------------------------------------------- #
#                                          the database's own refusal                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDuplicateKeyAbort:
    """The arm that actually holds under concurrency."""

    def test_an_endpoints_duplicate_reports_the_cable_wording(self, ctx) -> None:
        """The message a losing concurrent create receives has to be the actionable one"""
        error = Exception("Duplicate key error ... (index on ['endpoints'])")

        with pytest.raises(HTTPException) as raised:
            duplicate_key_abort(error, ConnectionType.CABLE.value, [PORT_A, PORT_B])

        assert 'cable connection' in raised.value.description

    def test_an_endpoints_duplicate_reports_the_internal_wording(self, ctx) -> None:
        """
        The two endpoint indexes share a key PATTERN, so the driver cannot tell them apart

        The route knows which connection_type it was writing, which is what picks the message.
        """
        error = Exception("Duplicate key error ... (index on ['endpoints'])")

        with pytest.raises(HTTPException) as raised:
            duplicate_key_abort(error, ConnectionType.INTERNAL.value, [PORT_A, PORT_B])

        assert 'internal connection' in raised.value.description

    def test_a_cable_ci_duplicate_reports_the_cable_ci_rule(self, ctx) -> None:
        """A different index, a different mistake"""
        error = Exception("Duplicate key error ... (index on ['cable_ci_id'])")

        with pytest.raises(HTTPException) as raised:
            duplicate_key_abort(error, ConnectionType.CABLE.value, [PORT_A, PORT_B])

        assert 'Cable belongs to at most one connection' in raised.value.description

    def test_an_unrecognised_duplicate_falls_back_rather_than_guessing(self, ctx) -> None:
        """
        Stating all three rules beats naming the wrong one

        The driver's message format is not a contract, so a change to it must degrade into a usable
        answer rather than a confident lie.
        """
        with pytest.raises(HTTPException) as raised:
            duplicate_key_abort(Exception('something else entirely'), ConnectionType.CABLE.value, None)

        assert raised.value.code == HTTP_BAD_REQUEST
        assert 'at most one cable' in raised.value.description

    def test_it_always_aborts(self, ctx) -> None:
        """Declared NoReturn, so the create route's except arm can not fall through to a None response"""
        with pytest.raises(HTTPException):
            duplicate_key_abort(Exception('x'), ConnectionType.CABLE.value, [PORT_A, PORT_B])


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    the rights                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def test_the_four_rights_are_pinned() -> None:
    """
    Right identifiers are a stored-data contract - user groups reference them by name

    They are deliberately their own family rather than the port rights: a connection spans two
    objects, so granting somebody the right to document an object's ports is not the same as granting
    them the right to cable it to another object's.
    """
    assert {right.name: right.value for right in ConnectionRight} == {
        'VIEW': 'base.framework.connection.view',
        'ADD': 'base.framework.connection.add',
        'EDIT': 'base.framework.connection.edit',
        'DELETE': 'base.framework.connection.delete',
    }
