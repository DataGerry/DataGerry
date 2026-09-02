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
Unit tests for cmdb.models.port_model and its Cerberus schema

Pins the three things about a port that other code depends on and that nothing else would notice
breaking:

* the unique index on (object_id, side, name) - the only real guarantee behind "a port name is unique
  per face", and the reason a patch panel's front 1 and rear 1 can coexist
* the stored default of 'side' - the unique index keys on it, so a null there would put an ordinary
  port in a namespace of its own, and panel-ness is derived from it
* PORT_TEMPLATE_FIELD_KEYS, which the virtual section template is derived from, so its content AND
  order are a contract

Pure tests: no Mongo, no Flask
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.framework.constants import __COLLECTIONS__
from cmdb.models.port_model import (
    CmdbPort,
    PortKey,
    PortSide,
    PORT_TEMPLATE_FIELD_KEYS,
    PORT_SELECT_FIELD_OPTION_TYPES,
)
from cmdb.models.extendable_option_model import OptionType
from cmdb.class_schema.port_model import get_cmdb_port_schema
from cmdb.errors.models.cmdb_port import (
    CmdbPortInitError,
    CmdbPortInitFromDataError,
    CmdbPortToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

OBJECT_ID: int = 800
PORT_ID: int = 900


def _port_data(**overrides: Any) -> dict[str, Any]:
    """Builds a stored port document, overridable per test"""
    data: dict[str, Any] = {
        PortKey.PUBLIC_ID.value: PORT_ID,
        PortKey.OBJECT_ID.value: OBJECT_ID,
        PortKey.NAME.value: 'Gi0/1',
        PortKey.SIDE.value: PortSide.SINGLE.value,
        PortKey.PORT_NUMBER.value: 1,
        PortKey.STATUS.value: 11,
        PortKey.PORT_TYPE.value: 12,
        PortKey.SPEED.value: 13,
        PortKey.DESCRIPTION.value: 'uplink',
        PortKey.AUTHOR_ID.value: 1,
    }
    data.update(overrides)

    return data

# -------------------------------------------------------------------------------------------------------------------- #
#                                                     indexes                                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class TestIndexes:
    """The index declarations, which are contracts rather than implementation details."""

    def test_the_name_index_is_unique_per_object_and_side(self) -> None:
        """
        A port name is unique within one face of one object, and this index is what enforces it

        'side' is part of the key on purpose: a patch panel has a front 1 AND a rear 1, so a unique
        (object_id, name) index would have made every panel unbuildable.
        """
        index = next(i for i in CmdbPort.INDEX_KEYS if i['name'] == 'object_side_name')

        assert [key for key, _ in index['keys']] == [
            PortKey.OBJECT_ID.value, PortKey.SIDE.value, PortKey.NAME.value,
        ]
        assert index['unique'] is True

    def test_the_name_index_is_not_partial(self) -> None:
        """Every port stores a side, so there is no missing-value case to carve out"""
        index = next(i for i in CmdbPort.INDEX_KEYS if i['name'] == 'object_side_name')

        assert 'partialFilterExpression' not in index

    def test_the_ordering_index_exists(self) -> None:
        """The ports of an object are read ordered by port number, served from one index"""
        index = next(i for i in CmdbPort.INDEX_KEYS if i['name'] == 'object_port_number')

        assert [key for key, _ in index['keys']] == [PortKey.OBJECT_ID.value, PortKey.PORT_NUMBER.value]
        assert index['unique'] is False

    def test_every_index_starts_with_the_object_id(self) -> None:
        """
        Which is why no standalone object_id index is declared

        An object_id-only query is served from either compound index's prefix, so a third index would
        be dead weight on every write. If a future index does not start with object_id, that reasoning
        stops holding and the standalone one has to come back.
        """
        assert all(index['keys'][0][0] == PortKey.OBJECT_ID.value for index in CmdbPort.INDEX_KEYS)

    def test_collection_name_is_pinned(self) -> None:
        """Connections, the cascade and the reference map all name this collection"""
        assert CmdbPort.COLLECTION == 'framework.ports'

    def test_the_model_is_registered_for_collection_creation(self) -> None:
        """
        Without this the collection is created implicitly and carries NO index

        CollectionValidator iterates __COLLECTIONS__ to create collections and build their declared
        indexes; a model missing from it silently loses its unique index on every installation.
        """
        assert CmdbPort in __COLLECTIONS__


# -------------------------------------------------------------------------------------------------------------------- #
#                                              from_data / to_json                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestSerialisation:
    """The round trip, and what a partial document reads as."""

    def test_from_data_round_trips_through_to_json(self) -> None:
        """Every stored key survives both directions unchanged"""
        data = _port_data()

        result = CmdbPort.to_json(CmdbPort.from_data(data))

        for key, value in data.items():
            assert result[key] == value

    def test_to_json_carries_every_document_key(self) -> None:
        """A key missing here would be dropped on every save"""
        result = CmdbPort.to_json(CmdbPort.from_data(_port_data()))

        assert set(result) == {key.value for key in PortKey}

    def test_connected_is_never_stored(self) -> None:
        """'connected' is computed from a port's connections on read, so it must not be a field"""
        result = CmdbPort.to_json(CmdbPort.from_data(_port_data()))

        assert 'connected' not in result

    def test_from_data_defaults_the_creation_time(self) -> None:
        """A document without a creation time is stamped rather than left null"""
        port = CmdbPort.from_data(_port_data(creation_time=None))

        assert isinstance(port.creation_time, datetime)

    def test_from_data_parses_string_timestamps(self) -> None:
        """A timestamp read back as a string becomes a datetime again"""
        port = CmdbPort.from_data(_port_data(
            creation_time='2026-09-01T10:00:00',
            last_edit_time='2026-09-02T11:30:00',
        ))

        assert port.creation_time == datetime(2026, 9, 1, 10, 0, 0)
        assert port.last_edit_time == datetime(2026, 9, 2, 11, 30, 0)

    def test_from_data_keeps_a_datetime_untouched(self) -> None:
        """An already-parsed timestamp is not re-parsed"""
        stamp = datetime(2026, 9, 1, 9, 0, 0, tzinfo=timezone.utc)

        assert CmdbPort.from_data(_port_data(creation_time=stamp)).creation_time == stamp

    def test_an_unusable_audit_timestamp_raises(self) -> None:
        """The audit stamps parse strictly - an unusable one is an error, not silently 'now'"""
        with pytest.raises(CmdbPortInitFromDataError):
            CmdbPort.from_data(_port_data(creation_time='not-a-date'))

    def test_an_unusable_public_id_raises_the_models_init_error(self) -> None:
        """A broken public_id surfaces as the model's own error type"""
        with pytest.raises(CmdbPortInitError):
            CmdbPort(public_id='not-an-int', object_id=OBJECT_ID, name='Gi0/1')

    def test_a_broken_instance_raises_the_models_to_json_error(self) -> None:
        """Serialising an instance whose attributes were removed is an error, not a partial dict"""
        port = CmdbPort.from_data(_port_data())
        del port.name

        with pytest.raises(CmdbPortToJsonError):
            CmdbPort.to_json(port)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       side                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class TestSide:
    """The field panel-ness is derived from."""

    def test_an_absent_side_reads_as_single(self) -> None:
        """A document written without the key is an ordinary port, not a port with no face"""
        data = _port_data()
        del data[PortKey.SIDE.value]

        assert CmdbPort.from_data(data).side == PortSide.SINGLE.value

    def test_a_null_side_reads_as_single(self) -> None:
        """The unique index keys on 'side', so a stored null would be its own namespace"""
        assert CmdbPort.from_data(_port_data(side=None)).side == PortSide.SINGLE.value

    def test_the_constructor_defaults_the_side(self) -> None:
        """The default lives on the model too, not only in from_data"""
        assert CmdbPort(public_id=PORT_ID, object_id=OBJECT_ID, name='Gi0/1').side == PortSide.SINGLE.value

    @pytest.mark.parametrize('side, expected', [
        (PortSide.FRONT.value, True),
        (PortSide.REAR.value, True),
        (PortSide.SINGLE.value, False),
    ], ids=['front', 'rear', 'single'])
    def test_is_panel_port(self, side: str, expected: bool) -> None:
        """A device is a patch panel exactly when its ports carry front/rear"""
        assert CmdbPort.from_data(_port_data(side=side)).is_panel_port() is expected

    @pytest.mark.parametrize('side', [None, '', 'middle'], ids=['none', 'empty', 'unknown'])
    def test_an_unknown_side_is_not_a_panel_side(self, side: Any) -> None:
        """An unreadable value is treated as an ordinary port rather than raising"""
        assert PortSide.is_panel_side(side) is False

    def test_the_panel_sides_are_the_two_faces(self) -> None:
        """SINGLE is deliberately not one of them"""
        assert PortSide.get_panel_sides() == frozenset({PortSide.FRONT, PortSide.REAR})


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    constants                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestConstants:
    """The document keys and the template field list."""

    def test_document_keys_are_pinned(self) -> None:
        """These names are stored in MongoDB, so they are a data contract"""
        assert {key.name: key.value for key in PortKey} == {
            'PUBLIC_ID': 'public_id',
            'OBJECT_ID': 'object_id',
            'SIDE': 'side',
            'NAME': 'name',
            'PORT_NUMBER': 'port_number',
            'STATUS': 'status',
            'PORT_TYPE': 'port_type',
            'SPEED': 'speed',
            'DESCRIPTION': 'description',
            'AUTHOR_ID': 'author_id',
            'CREATION_TIME': 'creation_time',
            'LAST_EDIT_TIME': 'last_edit_time',
        }

    def test_the_template_field_list_is_the_user_facing_fields_in_order(self) -> None:
        """
        The virtual section template is derived from this tuple, so content AND order are a contract

        It is exactly the user-facing half of the document: no server-owned key, and no 'connected'.
        """
        assert [key.value for key in PORT_TEMPLATE_FIELD_KEYS] == [
            'name', 'port_number', 'status', 'port_type', 'speed', 'description',
        ]

    def test_the_template_field_list_holds_no_server_owned_key(self) -> None:
        """A server-owned field appearing in the template would be editable in the UI"""
        server_owned = {
            PortKey.PUBLIC_ID, PortKey.OBJECT_ID, PortKey.SIDE,
            PortKey.AUTHOR_ID, PortKey.CREATION_TIME, PortKey.LAST_EDIT_TIME,
        }

        assert not server_owned & set(PORT_TEMPLATE_FIELD_KEYS)

    def test_the_select_fields_map_to_their_option_types(self) -> None:
        """Three of the six template fields are extendable-option selects"""
        assert PORT_SELECT_FIELD_OPTION_TYPES == {
            PortKey.STATUS: OptionType.PORT_STATUS,
            PortKey.PORT_TYPE: OptionType.PORT_TYPE,
            PortKey.SPEED: OptionType.PORT_SPEED,
        }

    def test_every_select_field_is_offered_by_the_template(self) -> None:
        """A select field the template does not show could never be filled in"""
        assert set(PORT_SELECT_FIELD_OPTION_TYPES) <= set(PORT_TEMPLATE_FIELD_KEYS)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                     schema                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class TestSchema:
    """The Cerberus schema consumed as CmdbPort.SCHEMA."""

    def test_the_schema_describes_every_document_key(self) -> None:
        """A key missing from the schema is rejected as unknown by the route validator"""
        assert set(get_cmdb_port_schema()) == {key.value for key in PortKey}

    def test_the_owner_and_the_name_are_required(self) -> None:
        """A port with no owner or no name is not a port"""
        schema = get_cmdb_port_schema()

        assert schema[PortKey.OBJECT_ID.value]['required'] is True
        assert schema[PortKey.NAME.value]['required'] is True

    def test_an_empty_name_is_refused(self) -> None:
        """The name is the port's identifier within its face, so '' is not usable"""
        assert get_cmdb_port_schema()[PortKey.NAME.value]['empty'] is False

    def test_the_side_defaults_to_single_and_is_constrained(self) -> None:
        """The schema is what writes the key when a payload omits it"""
        side = get_cmdb_port_schema()[PortKey.SIDE.value]

        assert side['default'] == PortSide.SINGLE.value
        assert sorted(side['allowed']) == sorted(s.value for s in PortSide)

    def test_the_required_init_keys_match_the_required_schema_keys(self) -> None:
        """Two declarations of the same rule must not disagree"""
        schema = get_cmdb_port_schema()
        required = {name for name, rule in schema.items() if rule.get('required')}

        assert set(CmdbPort.REQUIRED_INIT_KEYS) == required
