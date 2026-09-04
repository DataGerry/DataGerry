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
Unit tests for cmdb.models.port_connection_model and its Cerberus schema

Pins the four things about a connection that other code depends on and that nothing else would notice
breaking:

* the FOUR declared indexes. The two partial unique ones on 'endpoints' are the feature's only hard
  guarantee, and their partial filters are what stops the multikey-unique trap - a plain unique index
  on that array would forbid a port from appearing in two connections at all, making every patch panel
  unbuildable
* the SORT invariant applied in the constructor, so an instance can not carry an unsorted pair
* that to_json OMITS 'cable_ci_id' instead of writing null - the fourth index is filtered on that
  key's presence, so a stored null would make the second CI-less connection a duplicate
* the cable-field list, which the per-type field rule is derived from

Pure tests: no Mongo, no Flask
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.framework.constants import __COLLECTIONS__
from cmdb.models.port_connection_model import (
    CmdbPortConnection,
    ConnectionType,
    PortConnectionKey,
    CABLE_CI_INDEX_NAME,
    CABLE_FIELD_KEYS,
    ENDPOINT_COUNT,
    ENDPOINTS_CABLE_INDEX_NAME,
    ENDPOINTS_INDEX_NAME,
    ENDPOINTS_INTERNAL_INDEX_NAME,
)
from cmdb.class_schema.port_connection_model import get_cmdb_port_connection_schema
from cmdb.errors.models.cmdb_port_connection import (
    CmdbPortConnectionInitError,
    CmdbPortConnectionInitFromDataError,
    CmdbPortConnectionToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

CONNECTION_ID: int = 900
PORT_A: int = 3
PORT_B: int = 10
CABLE_CI_ID: int = 55


def _connection_data(**overrides: Any) -> dict[str, Any]:
    """Builds a stored connection document, overridable per test"""
    data: dict[str, Any] = {
        PortConnectionKey.PUBLIC_ID.value: CONNECTION_ID,
        PortConnectionKey.ENDPOINTS.value: [PORT_A, PORT_B],
        PortConnectionKey.CONNECTION_TYPE.value: ConnectionType.CABLE.value,
        PortConnectionKey.CABLE_NAME.value: 'Patch 1',
        PortConnectionKey.CABLE_TYPE.value: 12,
        PortConnectionKey.CABLE_LENGTH.value: '2.5 m',
        PortConnectionKey.CABLE_COLOR.value: 'blue',
        PortConnectionKey.CABLE_DESCRIPTION.value: 'Runs through the floor duct',
        PortConnectionKey.AUTHOR_ID.value: 1,
        PortConnectionKey.CREATION_TIME.value: datetime.now(timezone.utc),
        PortConnectionKey.LAST_EDIT_TIME.value: None,
    }
    data.update(overrides)

    return data


def _indexes_by_name() -> dict[str, dict[str, Any]]:
    """Indexes the model's declared index definitions by their name"""
    return {index['name']: index for index in CmdbPortConnection.INDEX_KEYS}


# -------------------------------------------------------------------------------------------------------------------- #
#                                     the indexes - the feature's only guarantee                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestIndexes:
    """The declarations everything else in the feature leans on."""

    def test_four_indexes_are_declared(self) -> None:
        """Two cardinality guarantees on endpoints, one plain read index, one on the cable CI"""
        assert set(_indexes_by_name()) == {
            ENDPOINTS_CABLE_INDEX_NAME,
            ENDPOINTS_INTERNAL_INDEX_NAME,
            ENDPOINTS_INDEX_NAME,
            CABLE_CI_INDEX_NAME,
        }

    @pytest.mark.parametrize('index_name,connection_type', [
        (ENDPOINTS_CABLE_INDEX_NAME, ConnectionType.CABLE),
        (ENDPOINTS_INTERNAL_INDEX_NAME, ConnectionType.INTERNAL),
    ], ids=str)
    def test_the_cardinality_indexes_are_unique_and_scoped_to_one_type(
            self, index_name: str, connection_type: ConnectionType) -> None:
        """
        Unique AND partial, and the partial filter is the whole point

        Unique makes the multikey index refuse a port that already appears in another document of the
        same scope; partial keeps that refusal inside one connection_type, so a panel port may hold a
        cable and an internal pairing at once.
        """
        index = _indexes_by_name()[index_name]

        assert index['unique'] is True
        assert index['partialFilterExpression'] == {
            PortConnectionKey.CONNECTION_TYPE.value: connection_type.value,
        }

    def test_no_unique_index_on_endpoints_spans_the_whole_collection(self) -> None:
        """
        The trap this design exists to avoid

        A unique index over an array is multikey-unique: no two documents may share any element. Left
        unfiltered that would mean no port could ever appear in two connections, and every patch-panel
        port would be unbuildable.
        """
        unfiltered_unique = [
            index for index in CmdbPortConnection.INDEX_KEYS
            if index['keys'][0][0] == PortConnectionKey.ENDPOINTS.value
            and index.get('unique')
            and 'partialFilterExpression' not in index
        ]

        assert unfiltered_unique == []

    def test_the_plain_endpoints_index_is_not_unique(self) -> None:
        """It serves 'all connections of port X' and the batched $in the computed flag runs"""
        index = _indexes_by_name()[ENDPOINTS_INDEX_NAME]

        assert index['unique'] is False
        assert 'partialFilterExpression' not in index

    def test_the_cable_ci_index_is_unique_and_filtered_on_presence(self) -> None:
        """
        One inventoried cable belongs to at most one connection

        Filtered on the key's PRESENCE, not on a value: the many connections that name no CI omit the
        key entirely and would otherwise all collide with each other as the same missing value.
        """
        index = _indexes_by_name()[CABLE_CI_INDEX_NAME]

        assert index['unique'] is True
        assert index['partialFilterExpression'] == {
            PortConnectionKey.CABLE_CI_ID.value: {'$exists': True}
        }

    def test_collection_name_is_pinned(self) -> None:
        """The collection name is a stored-data contract"""
        assert CmdbPortConnection.COLLECTION == 'framework.portConnections'

    def test_the_model_is_registered_for_collection_creation(self) -> None:
        """
        A model missing from __COLLECTIONS__ gets NO index built at all

        Its collection still appears, created implicitly by the first write and carrying only '_id_',
        so every guarantee above would silently not exist in production.
        """
        assert CmdbPortConnection in __COLLECTIONS__


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  the sort invariant                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class TestEndpointsAreCanonical:
    """An instance can not carry an unsorted pair."""

    def test_the_constructor_sorts_the_endpoints(self) -> None:
        """The sort happens on the way in, not as an assertion afterwards"""
        connection = CmdbPortConnection(public_id=CONNECTION_ID, endpoints=[PORT_B, PORT_A],
                                        connection_type=ConnectionType.CABLE.value)

        assert connection.endpoints == [PORT_A, PORT_B]

    def test_from_data_sorts_a_stored_pair_too(self) -> None:
        """A document written before the sort existed still reads back canonically"""
        connection = CmdbPortConnection.from_data(
            _connection_data(**{PortConnectionKey.ENDPOINTS.value: [PORT_B, PORT_A]}),
        )

        assert connection.endpoints == [PORT_A, PORT_B]

    def test_both_spellings_serialise_to_the_same_pair(self) -> None:
        """
        Which is what lets one index refuse a duplicate pair

        Two clients naming the same link in opposite order must produce the same stored document.
        """
        one = CmdbPortConnection(public_id=CONNECTION_ID, endpoints=[PORT_A, PORT_B],
                                 connection_type=ConnectionType.CABLE.value)
        other = CmdbPortConnection(public_id=CONNECTION_ID, endpoints=[PORT_B, PORT_A],
                                   connection_type=ConnectionType.CABLE.value)

        assert CmdbPortConnection.to_json(one)[PortConnectionKey.ENDPOINTS.value] == \
               CmdbPortConnection.to_json(other)[PortConnectionKey.ENDPOINTS.value]

    def test_an_unusable_pair_is_passed_through_rather_than_repaired(self) -> None:
        """
        The validator refuses it with a readable message; the model must not hide it

        Silently replacing it would store a connection nobody asked for, and reading a historical row
        must not raise either.
        """
        connection = CmdbPortConnection(public_id=CONNECTION_ID, endpoints=[PORT_A],
                                        connection_type=ConnectionType.CABLE.value)

        assert connection.endpoints == [PORT_A]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   serialisation                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
class TestSerialisation:
    """What is stored, and what is deliberately not."""

    def test_from_data_round_trips_through_to_json(self) -> None:
        """A stored document survives the model unchanged"""
        data = _connection_data()

        assert CmdbPortConnection.to_json(CmdbPortConnection.from_data(data)) == data

    def test_to_json_omits_an_absent_cable_ci(self) -> None:
        """
        ABSENT, never null - the unique index is filtered on this key's presence

        Writing null would put every CI-less connection into that index, and the second insert in the
        whole installation would be refused as a duplicate.
        """
        document = CmdbPortConnection.to_json(CmdbPortConnection.from_data(_connection_data()))

        assert PortConnectionKey.CABLE_CI_ID.value not in document

    def test_to_json_carries_a_named_cable_ci(self) -> None:
        """The other half of the same rule: a real reference is written"""
        document = CmdbPortConnection.to_json(CmdbPortConnection.from_data(
            _connection_data(**{PortConnectionKey.CABLE_CI_ID.value: CABLE_CI_ID}),
        ))

        assert document[PortConnectionKey.CABLE_CI_ID.value] == CABLE_CI_ID

    def test_from_data_defaults_the_creation_time(self) -> None:
        """A document written without one still gets an audit trail"""
        data = _connection_data()
        del data[PortConnectionKey.CREATION_TIME.value]

        assert CmdbPortConnection.from_data(data).creation_time is not None

    def test_from_data_parses_string_timestamps(self) -> None:
        """A JSON client sends timestamps as strings"""
        connection = CmdbPortConnection.from_data(_connection_data(**{
            PortConnectionKey.CREATION_TIME.value: '2026-09-02T10:00:00+00:00',
            PortConnectionKey.LAST_EDIT_TIME.value: '2026-09-03T10:00:00+00:00',
        }))

        assert isinstance(connection.creation_time, datetime)
        assert isinstance(connection.last_edit_time, datetime)

    def test_an_unusable_audit_timestamp_raises(self) -> None:
        """It surfaces as the model's own error rather than silently becoming 'now'"""
        with pytest.raises(CmdbPortConnectionInitFromDataError):
            CmdbPortConnection.from_data(
                _connection_data(**{PortConnectionKey.CREATION_TIME.value: 'not a timestamp'}),
            )

    def test_an_unusable_public_id_raises_the_models_init_error(self) -> None:
        """CmdbDAO refuses a missing public_id, and the model reports it as its own"""
        with pytest.raises(CmdbPortConnectionInitError):
            CmdbPortConnection(public_id='not-an-int', endpoints=[PORT_A, PORT_B],
                               connection_type=ConnectionType.CABLE.value)

    def test_a_broken_instance_raises_the_models_to_json_error(self) -> None:
        """Serialisation failures must not surface as a bare AttributeError"""
        connection = CmdbPortConnection.from_data(_connection_data())
        del connection.connection_type

        with pytest.raises(CmdbPortConnectionToJsonError):
            CmdbPortConnection.to_json(connection)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 reading a connection                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TestReadingAConnection:
    """The two questions every consumer asks of a stored link."""

    def test_is_internal_recognises_the_panel_pairing(self) -> None:
        """The one connection type carrying no cable information"""
        connection = CmdbPortConnection(public_id=CONNECTION_ID, endpoints=[PORT_A, PORT_B],
                                        connection_type=ConnectionType.INTERNAL.value)

        assert connection.is_internal() is True

    def test_a_cable_connection_is_not_internal(self) -> None:
        """The ordinary case"""
        assert CmdbPortConnection.from_data(_connection_data()).is_internal() is False

    @pytest.mark.parametrize('port_id,expected', [(PORT_A, PORT_B), (PORT_B, PORT_A)])
    def test_the_peer_is_found_from_either_end(self, port_id: int, expected: int) -> None:
        """
        Neither position in the sorted pair means anything

        A peer lookup that assumed the first id was the source would answer wrongly for half of all
        connections, and the halves would depend only on the ids the user happened to pick.
        """
        assert CmdbPortConnection.from_data(_connection_data()).get_peer_of(port_id) == expected

    def test_a_port_that_is_not_an_endpoint_has_no_peer(self) -> None:
        """The caller can tell 'not connected here' from 'connected to something'"""
        assert CmdbPortConnection.from_data(_connection_data()).get_peer_of(999) is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                                     constants                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestConstants:
    """The document keys and the derived cable-field list."""

    def test_document_keys_are_pinned(self) -> None:
        """These strings are a stored-data contract"""
        assert {key.name: key.value for key in PortConnectionKey} == {
            'PUBLIC_ID': 'public_id',
            'ENDPOINTS': 'endpoints',
            'CONNECTION_TYPE': 'connection_type',
            'CABLE_NAME': 'cable_name',
            'CABLE_TYPE': 'cable_type',
            'CABLE_LENGTH': 'cable_length',
            'CABLE_COLOR': 'cable_color',
            'CABLE_DESCRIPTION': 'cable_description',
            'CABLE_CI_ID': 'cable_ci_id',
            'AUTHOR_ID': 'author_id',
            'CREATION_TIME': 'creation_time',
            'LAST_EDIT_TIME': 'last_edit_time',
        }

    def test_the_connection_types_are_exactly_two(self) -> None:
        """
        A fixed list, deliberately not a CmdbExtendableOption

        The two partial unique indexes are filtered on these very values, so a third, customer-added
        type would fall outside both and get no cardinality guarantee at all.
        """
        assert {member.value for member in ConnectionType} == {'CABLE', 'INTERNAL'}

    def test_the_cable_field_list_is_every_cable_key(self) -> None:
        """The per-type field rule is derived from this tuple, so its content is the rule"""
        assert CABLE_FIELD_KEYS == (
            PortConnectionKey.CABLE_NAME,
            PortConnectionKey.CABLE_TYPE,
            PortConnectionKey.CABLE_LENGTH,
            PortConnectionKey.CABLE_COLOR,
            PortConnectionKey.CABLE_DESCRIPTION,
            PortConnectionKey.CABLE_CI_ID,
        )

    def test_the_cable_field_list_holds_no_server_owned_key(self) -> None:
        """A rule that refused 'public_id' or an audit field would refuse every internal write"""
        server_owned = {
            PortConnectionKey.PUBLIC_ID,
            PortConnectionKey.ENDPOINTS,
            PortConnectionKey.CONNECTION_TYPE,
            PortConnectionKey.AUTHOR_ID,
            PortConnectionKey.CREATION_TIME,
            PortConnectionKey.LAST_EDIT_TIME,
        }

        assert not set(CABLE_FIELD_KEYS) & server_owned

    def test_a_connection_joins_exactly_two_ports(self) -> None:
        """Named because both the schema and the endpoint validator assert it"""
        assert ENDPOINT_COUNT == 2


# -------------------------------------------------------------------------------------------------------------------- #
#                                                      schema                                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class TestSchema:
    """What the Cerberus schema does and does not describe."""

    def test_the_schema_describes_every_document_key(self) -> None:
        """A key without a rule is a key nothing validates"""
        assert set(get_cmdb_port_connection_schema()) == {key.value for key in PortConnectionKey}

    def test_the_endpoints_and_the_type_are_required(self) -> None:
        """Neither has a meaningful default - a connection without them is not a connection"""
        schema = get_cmdb_port_connection_schema()

        assert schema[PortConnectionKey.ENDPOINTS.value]['required'] is True
        assert schema[PortConnectionKey.CONNECTION_TYPE.value]['required'] is True

    def test_the_endpoints_are_exactly_two_integers(self) -> None:
        """The shape rule; that they differ and exist is the validator's, not the schema's"""
        rule = get_cmdb_port_connection_schema()[PortConnectionKey.ENDPOINTS.value]

        assert rule['type'] == 'list'
        assert rule['minlength'] == ENDPOINT_COUNT
        assert rule['maxlength'] == ENDPOINT_COUNT
        assert rule['schema'] == {'type': 'integer'}

    def test_the_connection_type_is_constrained_to_the_enum(self) -> None:
        """An unknown value would land outside both partial indexes"""
        rule = get_cmdb_port_connection_schema()[PortConnectionKey.CONNECTION_TYPE.value]

        assert sorted(rule['allowed']) == sorted(member.value for member in ConnectionType)

    def test_the_cable_length_is_text(self) -> None:
        """'5 m' and '2.5 m' are the notations the concept keeps verbatim"""
        assert get_cmdb_port_connection_schema()[
            PortConnectionKey.CABLE_LENGTH.value]['type'] == 'string'

    def test_the_cable_ci_reference_is_not_nullable(self) -> None:
        """
        It is absent or a real id, never null

        A nullable rule here would invite the exact write that breaks the presence-filtered index.
        """
        rule = get_cmdb_port_connection_schema()[PortConnectionKey.CABLE_CI_ID.value]

        assert rule['required'] is False
        assert 'nullable' not in rule

    def test_the_required_init_keys_match_the_required_schema_keys(self) -> None:
        """The two lists state the same rule, so they must not drift"""
        required_in_schema = {
            key for key, rule in get_cmdb_port_connection_schema().items() if rule.get('required')
        }

        assert set(CmdbPortConnection.REQUIRED_INIT_KEYS) == required_in_schema
