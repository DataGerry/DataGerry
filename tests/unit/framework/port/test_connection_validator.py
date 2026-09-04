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
Unit tests for cmdb.framework.port.connection_validator

Only the rules the DATABASE can not hold are tested here, because only those live in this module: no
self-connection, both ends name real ports, no cable information on an INTERNAL link, and a cable CI
that really is a Cable. The cardinality rules - no port in two cable connections, one internal
connection per port, one cable CI per connection - belong to the partial unique indexes and are proven
against a real MongoDB in tests/integration/framework/test_integration_port_connections.py.

The two functions that read the database take managers and are driven with mocks; the rest is pure
"""
from typing import Any

from unittest.mock import MagicMock

import pytest

from cmdb.framework.port.connection_constants import PortConnectionError
from cmdb.framework.port.connection_validator import (
    cable_ci_blockers,
    cable_field_blockers,
    coerce_connection_type,
    endpoint_blockers,
    missing_endpoint_blockers,
    shape_blockers,
    unknown_connection_type_blocker,
)
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.port_model import PortKey
from cmdb.models.port_connection_model import (
    ConnectionType,
    PortConnectionKey,
    CABLE_FIELD_KEYS,
)
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model import TypeSchemaKey
# -------------------------------------------------------------------------------------------------------------------- #

PORT_A: int = 3
PORT_B: int = 10
CABLE_CI_ID: int = 55
CABLE_TYPE_ID: int = 7


def _ports_manager(found: list[dict[str, Any]]) -> MagicMock:
    """A PortsManager stub whose find() answers with the given port documents"""
    manager = MagicMock(name='ports_manager')
    manager.find = MagicMock(return_value=found)

    return manager


def _port(public_id: int) -> dict[str, Any]:
    """A minimal stored port document - only the id the endpoint check reads"""
    return {PortKey.PUBLIC_ID.value: public_id}


def _managers(cable_ci: dict[str, Any] | None, type_doc: dict[str, Any] | None) -> tuple[MagicMock, MagicMock]:
    """An ObjectsManager / TypesManager stub pair answering with the given documents"""
    objects_manager = MagicMock(name='objects_manager')
    objects_manager.get_object = MagicMock(return_value=cable_ci)

    types_manager = MagicMock(name='types_manager')
    types_manager.get_type = MagicMock(return_value=type_doc)

    return objects_manager, types_manager


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 the connection type                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class TestConnectionType:
    """Which kind of link a request is creating."""

    @pytest.mark.parametrize('raw', [ConnectionType.CABLE.value, ConnectionType.INTERNAL.value])
    def test_a_known_type_is_read_back(self, raw: str) -> None:
        """The two the enum names, and nothing else"""
        assert coerce_connection_type(raw) == raw

    @pytest.mark.parametrize('raw', [None, '', 'cable', 'CABEL', 5, ConnectionType], ids=str)
    def test_an_unknown_type_is_not_defaulted(self, raw: Any) -> None:
        """
        Deliberately unlike the Rack row's kind, which defaults to MOUNT

        Guessing CABLE for a misspelled value would create the wrong kind of link - one that then
        falls under the wrong unique index and gets the wrong cardinality guarantee.
        """
        assert coerce_connection_type(raw) is None

    def test_an_unknown_type_is_refused_with_the_allowed_list(self) -> None:
        """The message has to tell the caller what it could have sent"""
        blocker = unknown_connection_type_blocker('CABEL')

        assert blocker is not None
        assert ConnectionType.CABLE.value in blocker
        assert ConnectionType.INTERNAL.value in blocker

    def test_a_known_type_is_not_blocked(self) -> None:
        """The ordinary case"""
        assert unknown_connection_type_blocker(ConnectionType.INTERNAL.value) is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                                     endpoints                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestEndpointBlockers:
    """The two rules judged without touching the database."""

    def test_two_different_ports_are_accepted(self) -> None:
        """The ordinary case"""
        assert endpoint_blockers([PORT_A, PORT_B]) == []

    def test_the_order_does_not_matter(self) -> None:
        """The link is undirected, so neither spelling may be preferred"""
        assert endpoint_blockers([PORT_B, PORT_A]) == []

    def test_a_self_connection_is_refused(self) -> None:
        """
        The one cardinality rule no index can hold

        [5, 5] dedupes to a single key inside one document and slips past a unique multikey index.
        """
        assert endpoint_blockers([5, 5]) == [PortConnectionError.SELF_CONNECTION.value]

    @pytest.mark.parametrize('endpoints', [None, [], [PORT_A], [PORT_A, PORT_B, 11], 'x'], ids=str)
    def test_anything_but_two_usable_ids_is_refused(self, endpoints: Any) -> None:
        """A connection joins exactly two ports, and no default could repair a wrong count"""
        assert len(endpoint_blockers(endpoints)) == 1

    def test_an_unusable_pair_is_not_also_reported_as_a_self_connection(self) -> None:
        """One fault, one message - naming it twice would make the payload look worse than it is"""
        assert endpoint_blockers(['x', 'x']) == [
            PortConnectionError.INVALID_ENDPOINTS.format(count=2)
        ]


class TestMissingEndpointBlockers:
    """Both ends have to name a port that really exists."""

    def test_both_ends_existing_is_accepted(self) -> None:
        """The ordinary case"""
        manager = _ports_manager([_port(PORT_A), _port(PORT_B)])

        assert missing_endpoint_blockers(manager, [PORT_A, PORT_B]) == []

    def test_both_ends_are_read_in_one_query(self) -> None:
        """One batched $in rather than one read per endpoint"""
        manager = _ports_manager([_port(PORT_A), _port(PORT_B)])

        missing_endpoint_blockers(manager, [PORT_B, PORT_A])

        assert manager.find.call_args.kwargs['criteria'] == {
            PortKey.PUBLIC_ID.value: {'$in': [PORT_A, PORT_B]},
        }

    def test_a_missing_end_is_named(self) -> None:
        """The caller has to learn WHICH end does not exist"""
        manager = _ports_manager([_port(PORT_A)])

        assert missing_endpoint_blockers(manager, [PORT_A, PORT_B]) == [
            PortConnectionError.ENDPOINT_NOT_FOUND.format(port_id=PORT_B)
        ]

    def test_two_missing_ends_are_both_named(self) -> None:
        """Every reason at once, so a caller fixes one payload"""
        manager = _ports_manager([])

        assert len(missing_endpoint_blockers(manager, [PORT_A, PORT_B])) == 2

    def test_an_unusable_pair_costs_no_query(self) -> None:
        """
        endpoint_blockers has already refused it

        Reporting it again here would give the caller one fault under two different messages, and the
        query could not be built anyway.
        """
        manager = _ports_manager([])

        assert missing_endpoint_blockers(manager, [PORT_A]) == []
        manager.find.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                            the per-type field rule                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCableFieldBlockers:
    """A panel's internal pairing has no cable."""

    @pytest.mark.parametrize('key', list(CABLE_FIELD_KEYS), ids=lambda key: key.value)
    def test_every_cable_field_is_refused_on_an_internal_connection(self, key) -> None:
        """
        Parametrized over the field list itself, so a newly added cable field is covered by this rule
        the moment it is declared
        """
        blockers = cable_field_blockers(ConnectionType.INTERNAL.value, {key.value: 'something'})

        assert blockers == [PortConnectionError.CABLE_FIELD_ON_INTERNAL.format(
            field=key.value, connection_type=ConnectionType.INTERNAL.value,
        )]

    def test_every_reason_is_reported_at_once(self) -> None:
        """A caller fixes one payload rather than discovering the rule one request at a time"""
        payload = {key.value: 'something' for key in CABLE_FIELD_KEYS}

        assert len(cable_field_blockers(ConnectionType.INTERNAL.value, payload)) == len(CABLE_FIELD_KEYS)

    def test_an_internal_connection_without_cable_info_is_accepted(self) -> None:
        """The ordinary case - the pairing IS the connection, nothing else describes it"""
        assert cable_field_blockers(ConnectionType.INTERNAL.value, {
            PortConnectionKey.ENDPOINTS.value: [PORT_A, PORT_B],
        }) == []

    def test_a_null_cable_field_is_not_treated_as_set(self) -> None:
        """A client echoing the whole document back sends nulls for what it does not use"""
        payload = {key.value: None for key in CABLE_FIELD_KEYS}

        assert cable_field_blockers(ConnectionType.INTERNAL.value, payload) == []

    def test_a_cable_connection_may_carry_every_cable_field(self) -> None:
        """The rule is about INTERNAL alone; a cable link is what the fields exist for"""
        payload = {key.value: 'something' for key in CABLE_FIELD_KEYS}

        assert cable_field_blockers(ConnectionType.CABLE.value, payload) == []


# -------------------------------------------------------------------------------------------------------------------- #
#                                                     cable CI                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCableCiBlockers:
    """A cable CI reference has to name an inventoried cable."""

    def test_no_reference_is_accepted(self) -> None:
        """Scenario A: cable info alone, with no CI at all, is the common case"""
        objects_manager, types_manager = _managers(None, None)

        assert cable_ci_blockers(objects_manager, types_manager, None) == []
        objects_manager.get_object.assert_not_called()

    def test_a_cable_object_is_accepted(self) -> None:
        """Scenario B: the object exists and its type carries the CABLE marker"""
        objects_manager, types_manager = _managers(
            {CmdbObjectKey.PUBLIC_ID.value: CABLE_CI_ID, CmdbObjectKey.TYPE_ID.value: 4},
            {TypeSchemaKey.SPECIAL_TYPE: SpecialType.CABLE.value},
        )

        assert cable_ci_blockers(objects_manager, types_manager, CABLE_CI_ID) == []

    def test_a_missing_object_is_refused(self) -> None:
        """A dangling reference must not be created in the first place"""
        objects_manager, types_manager = _managers(None, None)

        assert cable_ci_blockers(objects_manager, types_manager, CABLE_CI_ID) == [
            PortConnectionError.CABLE_CI_NOT_FOUND.format(cable_ci_id=CABLE_CI_ID)
        ]

    def test_an_object_of_another_type_is_refused(self) -> None:
        """
        Without this an arbitrary object would be stored and rendered as a cable

        This is the reason SpecialType.CABLE had to exist before the connection could be written at
        all - the reference cannot be validated against a member that does not exist.
        """
        objects_manager, types_manager = _managers(
            {CmdbObjectKey.PUBLIC_ID.value: CABLE_CI_ID, CmdbObjectKey.TYPE_ID.value: 4},
            {TypeSchemaKey.SPECIAL_TYPE: SpecialType.RACK.value},
        )

        assert cable_ci_blockers(objects_manager, types_manager, CABLE_CI_ID) == [
            PortConnectionError.CABLE_CI_NOT_A_CABLE.format(cable_ci_id=CABLE_CI_ID)
        ]

    def test_an_ordinary_type_without_any_marker_is_refused(self) -> None:
        """Most types carry no 'special_type' key at all"""
        objects_manager, types_manager = _managers(
            {CmdbObjectKey.PUBLIC_ID.value: CABLE_CI_ID, CmdbObjectKey.TYPE_ID.value: 4},
            {'name': 'server'},
        )

        assert len(cable_ci_blockers(objects_manager, types_manager, CABLE_CI_ID)) == 1

    def test_a_vanished_type_is_refused_rather_than_raising(self) -> None:
        """An object whose type was deleted must produce a message, not a 500"""
        objects_manager, types_manager = _managers(
            {CmdbObjectKey.PUBLIC_ID.value: CABLE_CI_ID, CmdbObjectKey.TYPE_ID.value: 4}, None,
        )

        assert len(cable_ci_blockers(objects_manager, types_manager, CABLE_CI_ID)) == 1


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    the aggregate                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestShapeBlockers:
    """The pure half of the write guard, in one call."""

    def test_a_valid_cable_connection_is_accepted(self) -> None:
        """The ordinary case"""
        assert shape_blockers(ConnectionType.CABLE.value, {
            PortConnectionKey.ENDPOINTS.value: [PORT_A, PORT_B],
            PortConnectionKey.CABLE_TYPE.value: CABLE_TYPE_ID,
        }) == []

    def test_it_reports_the_endpoint_and_the_field_reasons_together(self) -> None:
        """Both halves run, so a caller sees every problem in one response"""
        blockers = shape_blockers(ConnectionType.INTERNAL.value, {
            PortConnectionKey.ENDPOINTS.value: [5, 5],
            PortConnectionKey.CABLE_NAME.value: 'Patch 1',
        })

        assert PortConnectionError.SELF_CONNECTION.value in blockers
        assert len(blockers) == 2

    def test_it_touches_no_manager(self) -> None:
        """
        The two reads stay separate calls

        A caller that has already resolved the ports or the cable CI does not pay for it twice, and
        a dry-run pre-check can run the pure half on its own.
        """
        assert shape_blockers(ConnectionType.CABLE.value, {
            PortConnectionKey.ENDPOINTS.value: [PORT_A, PORT_B],
        }) == []
