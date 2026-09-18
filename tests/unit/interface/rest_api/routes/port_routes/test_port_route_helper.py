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
Unit tests for the CmdbPort route guards

Pure tests: the managers are mocks and every helper is called inside a Flask request context, because
they abort. The guard that matters most is the owner-object ACL one - a port is stored outside its
owner's document, so nothing about it inherits the object's access control and each route has to ask
explicitly. That it goes through ``objects_manager.get_object`` (which runs verify_access) rather than
a bare read is asserted here
"""
from typing import Any
from unittest.mock import MagicMock

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.models.extendable_option_model import OptionType
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.port_interface_link_model import PortInterfaceLinkKey
from cmdb.models.port_model import PortKey, PortSide
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.interface.rest_api.routes.port_routes import port_interface_link_helper as link_helper_module
from cmdb.interface.rest_api.routes.port_routes.port_route_constants import PortRequestKey
from cmdb.interface.rest_api.routes.port_routes.port_route_constants import PORT_CONNECTED_KEY
from cmdb.interface.rest_api.routes.port_routes.port_interface_link_constants import (
    INTERFACE_ROW_KEY,
    PORT_INTERFACE_LINKS_KEY,
)
from cmdb.interface.rest_api.routes.port_routes.port_interface_link_helper import (
    enforce_interface_on_port_object,
    with_interface_links,
    read_assignable_candidate_objects,
    read_assignable_lookups,
    get_interface_row_or_abort,
)
from cmdb.interface.rest_api.routes.port_routes.port_route_helper import (
    build_port_candidate,
    with_connected_flag,
    enforce_port_name_available,
    enforce_select_values,
    enforce_type_uses_ports,
    get_accessible_owner_or_abort,
    get_port_or_abort,
    get_requested_name_or_abort,
    get_requested_side_or_abort,
    refuse_owner_change,
)
# -------------------------------------------------------------------------------------------------------------------- #
# Several tests take the 'ctx' fixture purely for its side effect - it opens the request context the
# helpers' abort() needs - and never touch what it yields
# pylint: disable=unused-argument
# -------------------------------------------------------------------------------------------------------------------- #

HTTP_BAD_REQUEST: int = 400
HTTP_NOT_FOUND: int = 404

OBJECT_ID: int = 6000
TYPE_ID: int = 6001
PORT_ID: int = 6002
OTHER_PORT_ID: int = 6003
PORT_NAME: str = 'Gi0/1'


@pytest.fixture(name='ctx')
def fixture_ctx():
    """A request context, so the helpers' abort() has somewhere to raise from."""
    app = Flask(__name__)

    with app.test_request_context('/ports/'):
        yield


def _port(**overrides: Any) -> dict[str, Any]:
    """A stored port document."""
    port: dict[str, Any] = {
        PortKey.PUBLIC_ID.value: PORT_ID,
        PortKey.OBJECT_ID.value: OBJECT_ID,
        PortKey.SIDE.value: PortSide.SINGLE.value,
        PortKey.NAME.value: PORT_NAME,
    }
    port.update(overrides)

    return port


def _ports_manager(port: dict[str, Any] | None = None, by_name: dict[str, Any] | None = None) -> MagicMock:
    """A PortsManager stand-in."""
    manager = MagicMock(name='ports_manager')
    manager.get_item.return_value = port
    manager.get_port_by_name.return_value = by_name

    return manager


def _objects_manager(owner: dict[str, Any] | None = None, error: Exception | None = None) -> MagicMock:
    """An ObjectsManager stand-in; `error` is what get_object raises (e.g. AccessDeniedError)."""
    manager = MagicMock(name='objects_manager')

    if error is not None:
        manager.get_object.side_effect = error
    else:
        manager.get_object.return_value = owner

    return manager


def _types_manager(type_doc: dict[str, Any] | None) -> MagicMock:
    """A TypesManager stand-in."""
    manager = MagicMock(name='types_manager')
    manager.get_type.return_value = type_doc

    return manager


def _options_manager(option: dict[str, Any] | None) -> MagicMock:
    """An ExtendableOptionsManager stand-in."""
    manager = MagicMock(name='extendable_options_manager')
    manager.get_one_by.return_value = option

    return manager


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  get_port_or_abort                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetPortOrAbort:
    """The single-port lookup."""

    def test_returns_the_stored_port(self, ctx) -> None:
        """The ordinary case"""
        assert get_port_or_abort(_ports_manager(_port()), PORT_ID)[PortKey.NAME.value] == PORT_NAME

    def test_aborts_404_for_a_missing_port(self, ctx) -> None:
        """A port that does not exist is a 404, not an empty 200"""
        with pytest.raises(HTTPException) as exc_info:
            get_port_or_abort(_ports_manager(None), PORT_ID)

        assert exc_info.value.code == HTTP_NOT_FOUND


# -------------------------------------------------------------------------------------------------------------------- #
#                                          get_accessible_owner_or_abort                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetAccessibleOwnerOrAbort:
    """The guard nothing else performs for a port."""

    def test_reads_the_owner_through_the_acl_aware_getter(self, ctx) -> None:
        """
        The ACL is applied by objects_manager.get_object, which runs verify_access

        A bare collection read would hand the ports of an invisible object over, so the helper must
        pass the user AND the permission - asserted here rather than assumed.
        """
        objects_manager = _objects_manager({'public_id': OBJECT_ID})
        user = MagicMock()

        owner = get_accessible_owner_or_abort(
            objects_manager, OBJECT_ID, user, AccessControlPermission.READ,
        )

        assert owner['public_id'] == OBJECT_ID
        objects_manager.get_object.assert_called_once_with(OBJECT_ID, user, AccessControlPermission.READ)

    def test_passes_the_requested_permission_through(self, ctx) -> None:
        """A write asks for UPDATE on the owner, a read for READ"""
        objects_manager = _objects_manager({'public_id': OBJECT_ID})

        get_accessible_owner_or_abort(objects_manager, OBJECT_ID, MagicMock(), AccessControlPermission.UPDATE)

        assert objects_manager.get_object.call_args.args[2] == AccessControlPermission.UPDATE

    def test_aborts_404_for_a_missing_owner(self, ctx) -> None:
        """A port cannot belong to an object that does not exist"""
        with pytest.raises(HTTPException) as exc_info:
            get_accessible_owner_or_abort(_objects_manager(None), OBJECT_ID, MagicMock(),
                                          AccessControlPermission.READ)

        assert exc_info.value.code == HTTP_NOT_FOUND

    @pytest.mark.parametrize('object_id', [None, 'x', 1.5], ids=['none', 'string', 'float'])
    def test_aborts_400_for_a_non_integer_owner_id(self, ctx, object_id: Any) -> None:
        """A body that names no usable owner is a bad request, and costs no query"""
        objects_manager = _objects_manager({'public_id': OBJECT_ID})

        with pytest.raises(HTTPException) as exc_info:
            get_accessible_owner_or_abort(objects_manager, object_id, MagicMock(),
                                          AccessControlPermission.READ)

        assert exc_info.value.code == HTTP_BAD_REQUEST
        objects_manager.get_object.assert_not_called()

    def test_lets_an_access_denied_error_propagate(self, ctx) -> None:
        """
        The routes map AccessDeniedError to 403; swallowing it here would turn it into a 404

        Those two answers say very different things about an object the caller may not see.
        """
        class _Denied(Exception):
            """Stands in for AccessDeniedError."""

        with pytest.raises(_Denied):
            get_accessible_owner_or_abort(_objects_manager(error=_Denied('nope')), OBJECT_ID,
                                          MagicMock(), AccessControlPermission.READ)


# -------------------------------------------------------------------------------------------------------------------- #
#                                             enforce_type_uses_ports                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class TestEnforceTypeUsesPorts:
    """Step 1's flag, finally doing something."""

    def test_passes_for_a_port_bearing_type(self, ctx) -> None:
        """uses_ports true is the only value that allows a port"""
        enforce_type_uses_ports(_types_manager({TypeSchemaKey.USES_PORTS.value: True}),
                               {'public_id': OBJECT_ID, 'type_id': TYPE_ID})

    @pytest.mark.parametrize('flag', [False, None, 'true', 1], ids=['false', 'absent', 'string', 'int'])
    def test_aborts_400_unless_the_flag_is_really_true(self, ctx, flag: Any) -> None:
        """
        Compared with `is not True`, so a lenient spelling does not open the feature

        A stored `'true'` or `1` means the type was written by something that did not normalise the
        flag, and a port created on it would be invisible in the UI anyway.
        """
        type_doc = {} if flag is None else {TypeSchemaKey.USES_PORTS.value: flag}

        with pytest.raises(HTTPException) as exc_info:
            enforce_type_uses_ports(_types_manager(type_doc), {'public_id': OBJECT_ID, 'type_id': TYPE_ID})

        assert exc_info.value.code == HTTP_BAD_REQUEST

    def test_aborts_400_when_the_type_is_missing(self, ctx) -> None:
        """An object whose type vanished cannot be given ports"""
        with pytest.raises(HTTPException) as exc_info:
            enforce_type_uses_ports(_types_manager(None), {'public_id': OBJECT_ID, 'type_id': TYPE_ID})

        assert exc_info.value.code == HTTP_BAD_REQUEST

    def test_aborts_400_without_reading_a_non_integer_type_id(self, ctx) -> None:
        """A malformed object document costs no query"""
        types_manager = _types_manager({TypeSchemaKey.USES_PORTS.value: True})

        with pytest.raises(HTTPException):
            enforce_type_uses_ports(types_manager, {'public_id': OBJECT_ID, 'type_id': None})

        types_manager.get_type.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                           enforce_port_name_available                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TestEnforcePortNameAvailable:
    """The readable half of the uniqueness rule."""

    def test_passes_when_the_name_is_free(self, ctx) -> None:
        """Nothing stored under that name on this face"""
        enforce_port_name_available(_ports_manager(by_name=None), OBJECT_ID, PortSide.SINGLE.value, PORT_NAME)

    def test_aborts_400_when_the_name_is_taken(self, ctx) -> None:
        """The ordinary duplicate, refused with a message naming the port and the side"""
        manager = _ports_manager(by_name=_port(**{PortKey.PUBLIC_ID.value: OTHER_PORT_ID}))

        with pytest.raises(HTTPException) as exc_info:
            enforce_port_name_available(manager, OBJECT_ID, PortSide.SINGLE.value, PORT_NAME)

        assert exc_info.value.code == HTTP_BAD_REQUEST
        assert PORT_NAME in exc_info.value.description

    def test_a_port_does_not_clash_with_itself(self, ctx) -> None:
        """An update that keeps the name has to be allowed"""
        manager = _ports_manager(by_name=_port())

        enforce_port_name_available(manager, OBJECT_ID, PortSide.SINGLE.value, PORT_NAME, exclude_id=PORT_ID)

    def test_looks_the_name_up_on_the_given_face(self, ctx) -> None:
        """
        The lookup is per side, which is what lets a panel have a front 1 and a rear 1

        A lookup that ignored the side would refuse the second face of every patch panel.
        """
        manager = _ports_manager(by_name=None)

        enforce_port_name_available(manager, OBJECT_ID, PortSide.FRONT.value, PORT_NAME)

        manager.get_port_by_name.assert_called_once_with(OBJECT_ID, PortSide.FRONT.value, PORT_NAME)


# -------------------------------------------------------------------------------------------------------------------- #
#                                              enforce_select_values                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestEnforceSelectValues:
    """Every select value has to be an option of its own list."""

    def test_passes_when_no_select_value_is_given(self, ctx) -> None:
        """All three selects are optional, so an empty body costs no query"""
        manager = _options_manager(None)

        enforce_select_values(manager, {})

        manager.get_one_by.assert_not_called()

    def test_passes_for_an_option_of_the_right_list(self, ctx) -> None:
        """The ordinary case"""
        enforce_select_values(_options_manager({'public_id': 11}),
                             {PortRequestKey.STATUS.value: 11})

    def test_queries_the_option_type_the_field_draws_from(self, ctx) -> None:
        """
        Which list each field uses is declared once, by the port model

        Without the option_type in the query a PORT_TYPE id would pass as a speed and then be rendered
        as one.
        """
        manager = _options_manager({'public_id': 12})

        enforce_select_values(manager, {PortRequestKey.SPEED.value: 12})

        criteria = manager.get_one_by.call_args.args[0]
        assert criteria['option_type'] == OptionType.PORT_SPEED.value

    def test_aborts_400_for_an_unknown_option(self, ctx) -> None:
        """An id nothing answers to is refused rather than stored"""
        with pytest.raises(HTTPException) as exc_info:
            enforce_select_values(_options_manager(None), {PortRequestKey.PORT_TYPE.value: 999})

        assert exc_info.value.code == HTTP_BAD_REQUEST

    @pytest.mark.parametrize('value', ['11', 1.5, [11]], ids=['string', 'float', 'list'])
    def test_aborts_400_for_a_non_integer_value(self, ctx, value: Any) -> None:
        """The field stores a public_id, so anything else is refused without a query"""
        manager = _options_manager({'public_id': 11})

        with pytest.raises(HTTPException):
            enforce_select_values(manager, {PortRequestKey.STATUS.value: value})

        manager.get_one_by.assert_not_called()

    def test_checks_every_select_field(self, ctx) -> None:
        """Three fields, three lists - a body setting all three pays three lookups"""
        manager = _options_manager({'public_id': 1})

        enforce_select_values(manager, {
            PortRequestKey.STATUS.value: 1,
            PortRequestKey.PORT_TYPE.value: 2,
            PortRequestKey.SPEED.value: 3,
        })

        assert manager.get_one_by.call_count == 3


# -------------------------------------------------------------------------------------------------------------------- #
#                                      name / side / immutability / candidate                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class TestRequestedNameAndSide:
    """What a body may say about the two identifying fields."""

    def test_returns_the_name(self, ctx) -> None:
        """The ordinary case"""
        assert get_requested_name_or_abort({PortRequestKey.NAME.value: PORT_NAME}) == PORT_NAME

    @pytest.mark.parametrize('name', [None, '', '   ', 7], ids=['absent', 'empty', 'blank', 'int'])
    def test_aborts_400_without_a_usable_name(self, ctx, name: Any) -> None:
        """The name is the port's identifier within its face, so a blank one is not usable"""
        with pytest.raises(HTTPException) as exc_info:
            get_requested_name_or_abort({} if name is None else {PortRequestKey.NAME.value: name})

        assert exc_info.value.code == HTTP_BAD_REQUEST

    def test_an_absent_side_reads_as_single(self, ctx) -> None:
        """Every client except the patch-panel assistant sends no side at all"""
        assert get_requested_side_or_abort({}) == PortSide.SINGLE.value

    @pytest.mark.parametrize('side', [PortSide.FRONT.value, PortSide.REAR.value])
    def test_a_panel_side_is_accepted(self, ctx, side: str) -> None:
        """The creation assistant is what sets front/rear"""
        assert get_requested_side_or_abort({PortRequestKey.SIDE.value: side}) == side

    def test_aborts_400_for_an_unknown_side(self, ctx) -> None:
        """The unique index keys on the side, so a free-text value would be its own name space"""
        with pytest.raises(HTTPException) as exc_info:
            get_requested_side_or_abort({PortRequestKey.SIDE.value: 'middle'})

        assert exc_info.value.code == HTTP_BAD_REQUEST


class TestRefuseOwnerChange:
    """The two immutable fields."""

    def test_passes_when_the_payload_repeats_the_stored_values(self, ctx) -> None:
        """
        The routes take the whole port, so a client round-tripping a GET must not be punished

        Refusing an unchanged value would make the obvious client behaviour impossible.
        """
        refuse_owner_change(_port(), {
            PortRequestKey.OBJECT_ID.value: OBJECT_ID,
            PortRequestKey.SIDE.value: PortSide.SINGLE.value,
        })

    def test_passes_when_the_payload_omits_them(self, ctx) -> None:
        """A body that says nothing about them changes nothing"""
        refuse_owner_change(_port(), {})

    def test_aborts_400_on_a_different_owner(self, ctx) -> None:
        """Moving a port to another object would need that object's ACL and type flag checked"""
        with pytest.raises(HTTPException) as exc_info:
            refuse_owner_change(_port(), {PortRequestKey.OBJECT_ID.value: 9999})

        assert exc_info.value.code == HTTP_BAD_REQUEST

    def test_aborts_400_on_a_different_side(self, ctx) -> None:
        """
        Refused rather than ignored, so the caller learns the edit did nothing

        Moving the side moves the port into another face's name space, where its name may be taken -
        the unique index would then refuse the write with a duplicate-key error instead.
        """
        with pytest.raises(HTTPException) as exc_info:
            refuse_owner_change(_port(), {PortRequestKey.SIDE.value: PortSide.REAR.value})

        assert exc_info.value.code == HTTP_BAD_REQUEST


class TestBuildPortCandidate:
    """The document a write stores."""

    def test_carries_the_user_facing_fields(self, ctx) -> None:
        """Everything a request owns, and the owner and side the caller resolved"""
        candidate = build_port_candidate(OBJECT_ID, PortSide.FRONT.value, PORT_NAME, {
            PortRequestKey.PORT_NUMBER.value: 3,
            PortRequestKey.STATUS.value: 11,
            PortRequestKey.PORT_TYPE.value: 12,
            PortRequestKey.SPEED.value: 13,
            PortRequestKey.DESCRIPTION.value: 'uplink',
        })

        assert candidate == {
            PortKey.OBJECT_ID.value: OBJECT_ID,
            PortKey.SIDE.value: PortSide.FRONT.value,
            PortKey.NAME.value: PORT_NAME,
            PortKey.PORT_NUMBER.value: 3,
            PortKey.STATUS.value: 11,
            PortKey.PORT_TYPE.value: 12,
            PortKey.SPEED.value: 13,
            PortKey.DESCRIPTION.value: 'uplink',
        }

    def test_ignores_the_server_owned_keys_in_the_payload(self, ctx) -> None:
        """
        A payload public_id or audit stamp must never reach the document

        The caller fills those in from the URL, the stored port or the request user.
        """
        candidate = build_port_candidate(OBJECT_ID, PortSide.SINGLE.value, PORT_NAME, {
            PortKey.PUBLIC_ID.value: 4242,
            PortKey.AUTHOR_ID.value: 99,
            PortKey.CREATION_TIME.value: 'yesterday',
            PortKey.LAST_EDIT_TIME.value: 'tomorrow',
        })

        assert PortKey.PUBLIC_ID.value not in candidate
        assert PortKey.AUTHOR_ID.value not in candidate
        assert PortKey.CREATION_TIME.value not in candidate
        assert PortKey.LAST_EDIT_TIME.value not in candidate

    def test_optional_fields_default_to_none(self, ctx) -> None:
        """A minimal body still produces a complete document"""
        candidate = build_port_candidate(OBJECT_ID, PortSide.SINGLE.value, PORT_NAME, {})

        assert candidate[PortKey.PORT_NUMBER.value] is None
        assert candidate[PortKey.DESCRIPTION.value] is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                             the derived connected flag                                               #
# -------------------------------------------------------------------------------------------------------------------- #
CONNECTED_PORT_ID: int = 6100
PEER_PORT_ID: int = 6101


def _connections_manager(connections: list[dict[str, Any]] | None = None) -> MagicMock:
    """A PortConnectionsManager stand-in answering with the given connections."""
    manager = MagicMock(name='port_connections_manager')
    manager.get_connections_of_ports.return_value = connections or []

    return manager


class TestWithConnectedFlag:
    """The read side of `connected` - derived per response, never stored."""

    def test_the_whole_page_is_resolved_in_one_query(self) -> None:
        """
        One batched $in, not one query per port

        A 48-port switch would otherwise cost 48 reads to answer a question a single indexed predicate
        answers - and the plain multikey index on `endpoints` exists for exactly this.
        """
        manager = _connections_manager()

        with_connected_flag(manager, [_port(), _port(**{PortKey.PUBLIC_ID.value: OTHER_PORT_ID})])

        manager.get_connections_of_ports.assert_called_once_with([PORT_ID, OTHER_PORT_ID])

    def test_a_connected_port_is_flagged(self) -> None:
        """The flag the ports panel renders as 'Connected'"""
        manager = _connections_manager([{'endpoints': [PORT_ID, PEER_PORT_ID]}])

        ports = with_connected_flag(manager, [_port()])

        assert ports[0][PORT_CONNECTED_KEY] is True

    def test_a_free_port_is_flagged_false(self) -> None:
        """'Free' is a normal state and gets an explicit false, never a missing key"""
        ports = with_connected_flag(_connections_manager(), [_port()])

        assert ports[0][PORT_CONNECTED_KEY] is False

    def test_an_empty_page_asks_for_nothing(self) -> None:
        """
        An object with no ports is the common case on every object view that does not use them

        The helper hands an empty id list down; `get_connections_of_ports` short-circuits it without
        touching the database (asserted in test_port_connections_manager), so the guard lives in one
        place rather than being restated here.
        """
        manager = _connections_manager()

        assert with_connected_flag(manager, []) == []
        manager.get_connections_of_ports.assert_called_once_with([])

    def test_a_port_without_a_usable_id_is_left_out_of_the_query(self) -> None:
        """A drifted row must not put a null into the $in"""
        manager = _connections_manager()

        with_connected_flag(manager, [_port(**{PortKey.PUBLIC_ID.value: None}), _port()])

        assert manager.get_connections_of_ports.call_args.args[0] == [PORT_ID]


# -------------------------------------------------------------------------------------------------------------------- #
#                                       the interface-link write guards                                                #
# -------------------------------------------------------------------------------------------------------------------- #
INTERFACE_OBJECT_ID: int = 6300
ROW_ID: int = 4


class TestGetInterfaceRowOrAbort:
    """Resolving the row a create names, before the link is written."""

    @pytest.mark.parametrize('object_id', [None, 'not-an-id', 1.5], ids=str)
    def test_a_non_integer_object_id_is_a_404_without_a_read(self, ctx, object_id: Any) -> None:
        """
        A body can carry anything, so the id is checked before it reaches the manager

        Reading with a non-integer would either raise or silently match nothing, and the caller would
        be told the row is missing rather than that their id is not an id.
        """
        objects_manager = MagicMock(name='objects_manager')

        with pytest.raises(HTTPException) as raised:
            get_interface_row_or_abort(objects_manager, object_id, 'dg-ipam-interface', ROW_ID)

        assert raised.value.code == HTTP_NOT_FOUND
        objects_manager.get_object.assert_not_called()

    def test_a_missing_object_is_a_404(self, ctx) -> None:
        """Nothing to link to"""
        objects_manager = MagicMock(name='objects_manager')
        objects_manager.get_object.return_value = None

        with pytest.raises(HTTPException) as raised:
            get_interface_row_or_abort(objects_manager, INTERFACE_OBJECT_ID, 'dg-ipam-interface', ROW_ID)

        assert raised.value.code == HTTP_NOT_FOUND

    def test_a_missing_row_is_a_400(self, ctx) -> None:
        """
        Creating an already-dangling link is refused - unlike one that goes dangling later

        400 rather than 404 because the OBJECT is there; it is the request that names a row it does
        not hold.
        """
        objects_manager = MagicMock(name='objects_manager')
        objects_manager.get_object.return_value = {'public_id': INTERFACE_OBJECT_ID}

        with pytest.raises(HTTPException) as raised:
            get_interface_row_or_abort(objects_manager, INTERFACE_OBJECT_ID, 'dg-ipam-interface', ROW_ID)

        assert raised.value.code == HTTP_BAD_REQUEST

    def test_an_existing_row_is_returned(self, ctx) -> None:
        """The ordinary case"""
        row = {'multi_data_id': ROW_ID, 'data': []}
        objects_manager = MagicMock(name='objects_manager')
        objects_manager.get_object.return_value = {
            'public_id': INTERFACE_OBJECT_ID,
            'multi_data_sections': [{'section_id': 'dg-ipam-interface', 'values': [row]}],
        }

        assert get_interface_row_or_abort(
            objects_manager, INTERFACE_OBJECT_ID, 'dg-ipam-interface', ROW_ID,
        ) is row


# -------------------------------------------------------------------------------------------------------------------- #
#                                            the picker's candidate reads                                              #
# -------------------------------------------------------------------------------------------------------------------- #
CAPABLE_TYPE_ID: int = 7701
OWNER_OBJECT_ID: int = 7801
FOREIGN_OBJECT_ID: int = 7802
GUARDED_PORT_ID: int = 7901


class TestReadAssignableCandidateObjects:
    """
    Which CmdbObjects the picker is allowed to offer rows from

    Exactly one, always: a port may only be linked to its own object's interfaces, so the earlier wide
    scope (every interface-bearing object, ACL-filtered by type) is gone rather than defaulted off.
    """

    def test_it_reads_only_the_ports_own_object(self) -> None:
        """One document read - the object whose ACL the caller already passed to reach the route"""
        owner = {'public_id': OWNER_OBJECT_ID}
        objects_manager = MagicMock(name='objects_manager')
        objects_manager.get_object.return_value = owner

        candidates = read_assignable_candidate_objects(objects_manager, OWNER_OBJECT_ID)

        assert candidates == [owner]
        objects_manager.get_object.assert_called_once_with(OWNER_OBJECT_ID, as_dict=True)

    def test_it_never_queries_the_object_collection(self) -> None:
        """
        There is no candidate SET any more, so there is nothing to filter

        A find_objects call here would mean some other object could still be reached.
        """
        objects_manager = MagicMock(name='objects_manager')
        objects_manager.get_object.return_value = {'public_id': OWNER_OBJECT_ID}

        read_assignable_candidate_objects(objects_manager, OWNER_OBJECT_ID)

        objects_manager.find_objects.assert_not_called()

    def test_a_missing_owner_offers_nothing(self) -> None:
        """A port whose object is gone has nothing to offer, which is not an error here"""
        objects_manager = MagicMock(name='objects_manager')
        objects_manager.get_object.return_value = None

        assert read_assignable_candidate_objects(objects_manager, OWNER_OBJECT_ID) == []


class TestEnforceInterfaceOnPortObject:
    """
    A port may only be linked to its own object's interfaces

    The picker only ever offers that object, but the picker is a convenience - this is the rule, and
    it is what a hand-written POST meets.
    """

    @staticmethod
    def _port() -> dict:
        """The CmdbPort the link is being created on."""
        return {PortKey.PUBLIC_ID.value: GUARDED_PORT_ID, PortKey.OBJECT_ID.value: OWNER_OBJECT_ID}

    @staticmethod
    def _candidate(interface_object_id) -> dict:
        """The link document being built."""
        return {PortInterfaceLinkKey.INTERFACE_OBJECT_ID.value: interface_object_id}

    def test_the_ports_own_object_passes(self, ctx) -> None:
        """The only shape the picker can produce."""
        del ctx

        assert enforce_interface_on_port_object(
            self._port(), self._candidate(OWNER_OBJECT_ID),
        ) is None

    def test_another_object_is_refused(self, ctx) -> None:
        """Refused for being a different device, whether or not the row exists on it."""
        del ctx

        with pytest.raises(HTTPException) as caught:
            enforce_interface_on_port_object(self._port(), self._candidate(FOREIGN_OBJECT_ID))

        assert caught.value.code == 400

    def test_the_refusal_names_both_objects(self, ctx) -> None:
        """A client has to see which object it should have asked for."""
        del ctx

        with pytest.raises(HTTPException) as caught:
            enforce_interface_on_port_object(self._port(), self._candidate(FOREIGN_OBJECT_ID))

        assert str(OWNER_OBJECT_ID) in caught.value.description
        assert str(FOREIGN_OBJECT_ID) in caught.value.description

    @pytest.mark.parametrize('interface_object_id', [None, 'not-an-id'])
    def test_an_unusable_object_id_is_refused(self, ctx, interface_object_id) -> None:
        """
        A missing or malformed id is not the port's object either

        It is refused here rather than reaching the row read, so the message says which object was
        expected instead of reporting a missing one.
        """
        del ctx

        with pytest.raises(HTTPException) as caught:
            enforce_interface_on_port_object(self._port(), self._candidate(interface_object_id))

        assert caught.value.code == 400


class TestReadAssignableLookups:
    """The two bulk lookups a page of rows displays."""

    def test_no_candidates_asks_nothing(self) -> None:
        """An empty page must not cost two queries"""
        objects_manager = MagicMock(name='objects_manager')
        types_manager = MagicMock(name='types_manager')

        assert read_assignable_lookups(objects_manager, types_manager, []) == ({}, {})
        objects_manager.get_summary_lines_lookup.assert_not_called()
        types_manager.get_types_lookup.assert_not_called()

    def test_the_documents_in_hand_are_reused(self) -> None:
        """The summary lines are composed from the documents already read, not from a second load"""
        objects_manager = MagicMock(name='objects_manager')
        objects_manager.get_summary_lines_lookup.return_value = {OWNER_OBJECT_ID: 'Switch / edge-01'}
        types_manager = MagicMock(name='types_manager')
        types_manager.get_types_lookup.return_value = {CAPABLE_TYPE_ID: MagicMock(label='Switch')}
        candidates = [{'public_id': OWNER_OBJECT_ID, 'type_id': CAPABLE_TYPE_ID}]

        type_labels, summary_lines = read_assignable_lookups(objects_manager, types_manager, candidates)

        assert (type_labels, summary_lines) == ({CAPABLE_TYPE_ID: 'Switch'},
                                                {OWNER_OBJECT_ID: 'Switch / edge-01'})
        assert objects_manager.get_summary_lines_lookup.call_args.kwargs['object_docs'] is candidates


# -------------------------------------------------------------------------------------------------------------------- #
#                                       the interface links of a port read                                            #
# -------------------------------------------------------------------------------------------------------------------- #
LINK_SECTION_ID: str = 'dg-ipam-interface'
LINK_ROW_ID: int = 7
OTHER_ROW_ID: int = 8


def _link(port_id: int, row_id: int, interface_object_id: int = OBJECT_ID, **overrides: Any) -> dict[str, Any]:
    """A stored port <-> interface link document."""
    link: dict[str, Any] = {
        PortInterfaceLinkKey.PUBLIC_ID.value: 900 + row_id,
        PortInterfaceLinkKey.PORT_ID.value: port_id,
        PortInterfaceLinkKey.INTERFACE_OBJECT_ID.value: interface_object_id,
        PortInterfaceLinkKey.INTERFACE_SECTION_ID.value: LINK_SECTION_ID,
        PortInterfaceLinkKey.INTERFACE_MULTI_DATA_ID.value: row_id,
    }
    link.update(overrides)

    return link


def _owner_with_rows(*row_ids: int) -> dict[str, Any]:
    """The owner CmdbObject carrying the interface rows the links address."""
    return {
        CmdbObjectKey.PUBLIC_ID.value: OBJECT_ID,
        CmdbObjectKey.MULTI_DATA_SECTIONS.value: [{
            'section_id': LINK_SECTION_ID,
            'values': [
                {'multi_data_id': row_id, 'data': [{'name': 'dg-ipam-interface-ip', 'value': f'10.0.0.{row_id}'}]}
                for row_id in row_ids
            ],
        }],
    }


def _links_manager(links: list[dict[str, Any]]) -> MagicMock:
    """A PortInterfaceLinksManager stand-in."""
    manager = MagicMock(name='port_interface_links_manager')
    manager.get_links_of_ports.return_value = links

    return manager


class TestWithInterfaceLinks:
    """
    Both port reads answer with each port's interface links attached

    The ports panel shows a port's addresses next to the port, so the alternative is one follow-up
    request per port - 48 of them for a switch.
    """

    def test_each_port_gets_its_own_links(self) -> None:
        """Grouped by port_id, not handed to every port of the page"""
        links_manager = _links_manager([
            _link(PORT_ID, LINK_ROW_ID), _link(OTHER_PORT_ID, OTHER_ROW_ID),
        ])
        ports = [_port(), _port(**{PortKey.PUBLIC_ID.value: OTHER_PORT_ID})]

        with_interface_links(links_manager, MagicMock(), ports, _owner_with_rows(LINK_ROW_ID, OTHER_ROW_ID))

        assert [link[PortInterfaceLinkKey.INTERFACE_MULTI_DATA_ID.value]
                for link in ports[0][PORT_INTERFACE_LINKS_KEY]] == [LINK_ROW_ID]
        assert [link[PortInterfaceLinkKey.INTERFACE_MULTI_DATA_ID.value]
                for link in ports[1][PORT_INTERFACE_LINKS_KEY]] == [OTHER_ROW_ID]

    def test_a_port_with_several_links_keeps_them_all(self) -> None:
        """A bond member or a stack of VLAN sub-interfaces is the N:M case the feature exists for"""
        links_manager = _links_manager([_link(PORT_ID, LINK_ROW_ID), _link(PORT_ID, OTHER_ROW_ID)])
        ports = [_port()]

        with_interface_links(links_manager, MagicMock(), ports, _owner_with_rows(LINK_ROW_ID, OTHER_ROW_ID))

        assert len(ports[0][PORT_INTERFACE_LINKS_KEY]) == 2

    def test_a_port_without_links_carries_an_empty_list(self) -> None:
        """
        Never a missing key

        "Linked to nothing" is the common state, and a client must not have to tell it apart from
        "the server did not answer that question".
        """
        ports = [_port()]

        with_interface_links(_links_manager([]), MagicMock(), ports, _owner_with_rows())

        assert ports[0][PORT_INTERFACE_LINKS_KEY] == []

    def test_the_live_row_is_attached(self) -> None:
        """The panel shows the addresses, so the row travels with the link"""
        ports = [_port()]

        with_interface_links(_links_manager([_link(PORT_ID, LINK_ROW_ID)]), MagicMock(), ports,
                             _owner_with_rows(LINK_ROW_ID))

        row = ports[0][PORT_INTERFACE_LINKS_KEY][0][INTERFACE_ROW_KEY]

        assert row['multi_data_id'] == LINK_ROW_ID

    def test_a_dangling_link_is_listed_without_its_row(self) -> None:
        """
        Shown, never hidden

        The interface half of a link is soft: an MDS row id is not durable, so a link whose row is
        gone is tolerated and reported. Dropping it from the list would hide the only record of what
        the customer meant.
        """
        ports = [_port()]

        with_interface_links(_links_manager([_link(PORT_ID, LINK_ROW_ID)]), MagicMock(), ports,
                             _owner_with_rows(OTHER_ROW_ID))

        link = ports[0][PORT_INTERFACE_LINKS_KEY][0]

        assert INTERFACE_ROW_KEY not in link
        assert link[PortInterfaceLinkKey.INTERFACE_MULTI_DATA_ID.value] == LINK_ROW_ID

    def test_the_whole_page_costs_one_query(self) -> None:
        """One batched `$in` for every port on the page, the same shape the connected flag uses"""
        links_manager = _links_manager([])
        ports = [_port(), _port(**{PortKey.PUBLIC_ID.value: OTHER_PORT_ID})]

        with_interface_links(links_manager, MagicMock(), ports, _owner_with_rows())

        links_manager.get_links_of_ports.assert_called_once_with([PORT_ID, OTHER_PORT_ID])

    def test_the_owner_in_hand_costs_no_object_read(self) -> None:
        """
        The saving that makes this free

        An interface must live on the port's own object, and the route already read that object for
        the ACL check - so resolving the rows must not read it again.
        """
        objects_manager = MagicMock(name='objects_manager')

        with_interface_links(_links_manager([_link(PORT_ID, LINK_ROW_ID)]), objects_manager, [_port()],
                             _owner_with_rows(LINK_ROW_ID))

        objects_manager.get_object.assert_not_called()

    def test_without_the_owner_the_object_is_read_once(self) -> None:
        """The parameter is an optimisation, not a requirement: the helper still resolves without it"""
        objects_manager = MagicMock(name='objects_manager')
        objects_manager.get_object.return_value = _owner_with_rows(LINK_ROW_ID)

        ports = [_port()]
        with_interface_links(_links_manager([_link(PORT_ID, LINK_ROW_ID), _link(PORT_ID, OTHER_ROW_ID)]),
                             objects_manager, ports)

        objects_manager.get_object.assert_called_once_with(OBJECT_ID)
        assert INTERFACE_ROW_KEY in ports[0][PORT_INTERFACE_LINKS_KEY][0]

    def test_an_empty_page_asks_nothing_of_the_links(self) -> None:
        """An object with no ports is the common case on every object view that does not use them"""
        links_manager = _links_manager([])

        assert with_interface_links(links_manager, MagicMock(), [], _owner_with_rows()) == []
        links_manager.get_links_of_ports.assert_called_once_with([])
