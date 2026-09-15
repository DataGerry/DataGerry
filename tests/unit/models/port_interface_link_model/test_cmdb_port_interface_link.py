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
Unit tests for cmdb.models.port_interface_link_model and its Cerberus schema

Pins the three things other code depends on:

* the unique index keys on the identity tuple, and in particular that `relation_type` is NOT among
  them - it DESCRIBES the pair rather than identifying it, so including it would let the same port and
  the same interface row be linked once per relation type
* the fixed relation-type list, which the concept calls explicitly non-customizable
* that no IP and no MAC live on the link. The interface row stays the single source for those, which is
  the whole reason a port links to one instead of copying its values

Pure tests: no Mongo, no Flask
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.framework.constants import __COLLECTIONS__
from cmdb.models.port_interface_link_model import (
    CmdbPortInterfaceLink,
    InterfaceRelationType,
    PortInterfaceLinkKey,
    INTERFACE_REFERENCE_KEYS,
    INTERFACE_ROW_INDEX_NAME,
    LINK_IDENTITY_INDEX_NAME,
    LINK_IDENTITY_KEYS,
    PORT_ID_INDEX_NAME,
)
from cmdb.class_schema.port_interface_link_model import get_cmdb_port_interface_link_schema
from cmdb.errors.models.cmdb_port_interface_link import (
    CmdbPortInterfaceLinkInitError,
    CmdbPortInterfaceLinkInitFromDataError,
    CmdbPortInterfaceLinkToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LINK_ID: int = 8400
PORT_ID: int = 8401
INTERFACE_OBJECT_ID: int = 8402
SECTION_ID: str = 'dg-ipam-interface'
ROW_ID: int = 2


def _link_data(**overrides: Any) -> dict[str, Any]:
    """Builds a stored link document, overridable per test"""
    data: dict[str, Any] = {
        PortInterfaceLinkKey.PUBLIC_ID.value: LINK_ID,
        PortInterfaceLinkKey.PORT_ID.value: PORT_ID,
        PortInterfaceLinkKey.INTERFACE_OBJECT_ID.value: INTERFACE_OBJECT_ID,
        PortInterfaceLinkKey.INTERFACE_SECTION_ID.value: SECTION_ID,
        PortInterfaceLinkKey.INTERFACE_MULTI_DATA_ID.value: ROW_ID,
        PortInterfaceLinkKey.RELATION_TYPE.value: InterfaceRelationType.PHYSICAL.value,
        PortInterfaceLinkKey.AUTHOR_ID.value: 1,
        PortInterfaceLinkKey.CREATION_TIME.value: datetime.now(timezone.utc),
        PortInterfaceLinkKey.LAST_EDIT_TIME.value: None,
    }
    data.update(overrides)

    return data


def _indexes_by_name() -> dict[str, dict[str, Any]]:
    """Indexes the model's declared index definitions by their name"""
    return {index['name']: index for index in CmdbPortInterfaceLink.INDEX_KEYS}


# -------------------------------------------------------------------------------------------------------------------- #
#                                                     the indexes                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
class TestIndexes:
    """One link per port/interface pair, plus the two read directions."""

    def test_three_indexes_are_declared(self) -> None:
        """The identity guarantee and the two directions the links are read from"""
        assert set(_indexes_by_name()) == {
            LINK_IDENTITY_INDEX_NAME, PORT_ID_INDEX_NAME, INTERFACE_ROW_INDEX_NAME,
        }

    def test_the_identity_index_is_unique(self) -> None:
        """A port may be linked to the same interface row at most once"""
        assert _indexes_by_name()[LINK_IDENTITY_INDEX_NAME]['unique'] is True

    def test_the_identity_index_excludes_the_relation_type(self) -> None:
        """
        The rule this whole design turns on

        relation_type DESCRIBES the pair rather than identifying it. Including it in the key would let
        the same port and the same interface row be linked five times over - once per relation type -
        which is exactly what 'one link per pair' forbids.
        """
        keyed = [key for key, _ in _indexes_by_name()[LINK_IDENTITY_INDEX_NAME]['keys']]

        assert PortInterfaceLinkKey.RELATION_TYPE.value not in keyed
        assert keyed == [key.value for key in LINK_IDENTITY_KEYS]

    def test_the_identity_index_spans_the_port_and_the_whole_triple(self) -> None:
        """All four coordinates, so two different rows of one object are two different links"""
        assert set(LINK_IDENTITY_KEYS) == {PortInterfaceLinkKey.PORT_ID, *INTERFACE_REFERENCE_KEYS}

    def test_the_read_indexes_are_not_unique(self) -> None:
        """Both directions are one-to-many: a port has several links, an object several ports' links"""
        assert _indexes_by_name()[PORT_ID_INDEX_NAME]['unique'] is False
        assert _indexes_by_name()[INTERFACE_ROW_INDEX_NAME]['unique'] is False

    def test_collection_name_is_pinned(self) -> None:
        """The collection name is a stored-data contract"""
        assert CmdbPortInterfaceLink.COLLECTION == 'framework.portInterfaceLinks'

    def test_the_model_is_registered_for_collection_creation(self) -> None:
        """
        A model missing from __COLLECTIONS__ gets NO index built at all

        Its collection still appears, created implicitly by the first write, so the uniqueness above
        would silently not exist in production.
        """
        assert CmdbPortInterfaceLink in __COLLECTIONS__


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   serialisation                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
class TestSerialisation:
    """What is stored, and what is deliberately not."""

    def test_from_data_round_trips_through_to_json(self) -> None:
        """A stored document survives the model unchanged"""
        data = _link_data()

        assert CmdbPortInterfaceLink.to_json(CmdbPortInterfaceLink.from_data(data)) == data

    def test_no_ip_or_mac_is_stored(self) -> None:
        """
        The interface row stays the single source for those

        Copying them onto the link would create a second truth that goes stale the moment the
        interface is edited - which is the whole reason a port links to a row instead.
        """
        stored = CmdbPortInterfaceLink.to_json(CmdbPortInterfaceLink.from_data(_link_data()))

        assert not [key for key in stored if 'ip' in key.lower() or 'mac' in key.lower()]

    def test_from_data_defaults_the_creation_time(self) -> None:
        """A document written without one still gets an audit trail"""
        data = _link_data()
        del data[PortInterfaceLinkKey.CREATION_TIME.value]

        assert CmdbPortInterfaceLink.from_data(data).creation_time is not None

    def test_from_data_parses_string_timestamps(self) -> None:
        """A JSON client sends timestamps as strings - both of them"""
        link = CmdbPortInterfaceLink.from_data(_link_data(**{
            PortInterfaceLinkKey.CREATION_TIME.value: '2026-09-03T10:00:00+00:00',
            PortInterfaceLinkKey.LAST_EDIT_TIME.value: '2026-09-04T10:00:00+00:00',
        }))

        assert isinstance(link.creation_time, datetime)
        assert isinstance(link.last_edit_time, datetime)

    def test_an_unusable_audit_timestamp_raises(self) -> None:
        """It surfaces as the model's own error rather than silently becoming 'now'"""
        with pytest.raises(CmdbPortInterfaceLinkInitFromDataError):
            CmdbPortInterfaceLink.from_data(
                _link_data(**{PortInterfaceLinkKey.CREATION_TIME.value: 'not a timestamp'}),
            )

    def test_an_unusable_public_id_raises_the_models_init_error(self) -> None:
        """CmdbDAO refuses a broken public_id, and the model reports it as its own"""
        with pytest.raises(CmdbPortInterfaceLinkInitError):
            CmdbPortInterfaceLink(
                public_id='not-an-int', port_id=PORT_ID, interface_object_id=INTERFACE_OBJECT_ID,
                interface_section_id=SECTION_ID, interface_multi_data_id=ROW_ID,
                relation_type=InterfaceRelationType.PHYSICAL.value,
            )

    def test_a_broken_instance_raises_the_models_to_json_error(self) -> None:
        """Serialisation failures must not surface as a bare AttributeError"""
        link = CmdbPortInterfaceLink.from_data(_link_data())
        del link.relation_type

        with pytest.raises(CmdbPortInterfaceLinkToJsonError):
            CmdbPortInterfaceLink.to_json(link)

    def test_the_interface_reference_is_the_triple(self) -> None:
        """The one way 'which row is this' is asked, so a reader never assembles the keys itself"""
        link = CmdbPortInterfaceLink.from_data(_link_data())

        assert link.get_interface_reference() == (INTERFACE_OBJECT_ID, SECTION_ID, ROW_ID)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                     constants                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestConstants:
    """The document keys and the fixed relation-type list."""

    def test_document_keys_are_pinned(self) -> None:
        """These strings are a stored-data contract"""
        assert {key.name: key.value for key in PortInterfaceLinkKey} == {
            'PUBLIC_ID': 'public_id',
            'PORT_ID': 'port_id',
            'INTERFACE_OBJECT_ID': 'interface_object_id',
            'INTERFACE_SECTION_ID': 'interface_section_id',
            'INTERFACE_MULTI_DATA_ID': 'interface_multi_data_id',
            'RELATION_TYPE': 'relation_type',
            'AUTHOR_ID': 'author_id',
            'CREATION_TIME': 'creation_time',
            'LAST_EDIT_TIME': 'last_edit_time',
        }

    def test_the_relation_types_are_the_fixed_five(self) -> None:
        """
        Explicitly non-customizable, unlike the port's status / type / speed lists

        A customer-added sixth would carry no meaning for anything reading the link, so there is
        nothing here for them to configure - which is why this is an enum and not an OptionType.
        """
        assert {member.value for member in InterfaceRelationType} == {
            'PHYSICAL', 'BOND', 'VLAN', 'VIRTUAL', 'OTHER',
        }

    def test_the_interface_reference_is_three_coordinates(self) -> None:
        """The object, the section and the row - the section because a row id is unique only within one"""
        assert INTERFACE_REFERENCE_KEYS == (
            PortInterfaceLinkKey.INTERFACE_OBJECT_ID,
            PortInterfaceLinkKey.INTERFACE_SECTION_ID,
            PortInterfaceLinkKey.INTERFACE_MULTI_DATA_ID,
        )


# -------------------------------------------------------------------------------------------------------------------- #
#                                                      schema                                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class TestSchema:
    """What the Cerberus schema does and does not describe."""

    def test_the_schema_describes_every_document_key(self) -> None:
        """A key without a rule is a key nothing validates"""
        assert set(get_cmdb_port_interface_link_schema()) == {key.value for key in PortInterfaceLinkKey}

    def test_the_identity_and_the_relation_type_are_required(self) -> None:
        """None of them has a meaningful default - a link without them names nothing"""
        schema = get_cmdb_port_interface_link_schema()

        for key in (*LINK_IDENTITY_KEYS, PortInterfaceLinkKey.RELATION_TYPE):
            assert schema[key.value]['required'] is True

    def test_the_relation_type_is_constrained_to_the_enum(self) -> None:
        """An unknown value would describe the link as nothing anything can read"""
        rule = get_cmdb_port_interface_link_schema()[PortInterfaceLinkKey.RELATION_TYPE.value]

        assert sorted(rule['allowed']) == sorted(member.value for member in InterfaceRelationType)

    def test_the_row_id_is_an_integer_and_not_nullable(self) -> None:
        """
        The id IS the reference

        A link without one would point at nothing from the moment it was created, which the concept
        refuses outright.
        """
        rule = get_cmdb_port_interface_link_schema()[
            PortInterfaceLinkKey.INTERFACE_MULTI_DATA_ID.value
        ]

        assert rule['type'] == 'integer'
        assert 'nullable' not in rule

    def test_the_required_init_keys_match_the_required_schema_keys(self) -> None:
        """The two lists state the same rule, so they must not drift"""
        required_in_schema = {
            key for key, rule in get_cmdb_port_interface_link_schema().items() if rule.get('required')
        }

        assert set(CmdbPortInterfaceLink.REQUIRED_INIT_KEYS) == required_in_schema
