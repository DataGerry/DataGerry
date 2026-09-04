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
Unit tests for cmdb.models.special_type_model.schemas.cable_schema

Pins the CABLE blueprint: the field names (a field name is its immutable identifier, so these values
are a stored-data contract), that only the cable name is required, the single-section layout and its
field order, and the field list matching the cable information a connection carries on its own -
Scenario A and Scenario B have to offer the same vocabulary.

The cable-type select is the interesting half. It carries INLINE options rather than pointing at the
CABLE_TYPE CmdbExtendableOption list, because a stored CmdbType field has no 'option_type' key to
point with, and the values are passed IN by the caller so this layer needs no database

Pure tests: no Mongo, no Flask
"""
from typing import Any

import pytest

from cmdb.models.type_model import FieldType, SectionType, FieldKey, SectionKey, TypeSchemaKey
from cmdb.models.port_connection_model import CABLE_FIELD_KEYS, PortConnectionKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.cable_constants import CableField, CableSection
from cmdb.models.special_type_model.schemas.cable_schema import build_cable_type_options, get_cable_schema
# -------------------------------------------------------------------------------------------------------------------- #

CABLE_TYPE_VALUES: list[str] = ['Cat6a', 'OM4', 'DAC']
CUSTOMER_VALUE: str = 'Cat8.1 (in-house)'


def _fields_by_name(schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Indexes the schema's flat field definitions by their name"""
    return {field[FieldKey.NAME]: field for field in schema[TypeSchemaKey.FIELDS]}


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  identity / marker                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_cable_schema_is_marked_as_the_cable_special_type() -> None:
    """The blueprint carries the CABLE marker, which is what claims the SpecialType on insert"""
    assert get_cable_schema(CABLE_TYPE_VALUES)[TypeSchemaKey.SPECIAL_TYPE] == SpecialType.CABLE


def test_cable_field_names_are_pinned() -> None:
    """
    A field's name is its immutable identifier

    Renaming one would orphan the stored value on every existing Cable object, so these strings are a
    data contract and this test is the tripwire.
    """
    assert CableField.NAME == 'dg-cable-name'
    assert CableField.TYPE == 'dg-cable-type'
    assert CableField.LENGTH == 'dg-cable-length'
    assert CableField.COLOR == 'dg-cable-color'
    assert CableField.DESCRIPTION == 'dg-cable-description'
    assert CableSection.INFORMATION == 'dg-cable-information'


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       fields                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
def test_cable_name_is_the_only_required_field() -> None:
    """
    A CI created from an inventory import often knows nothing but a name

    Requiring more would make such an import fail on rows that are perfectly usable.
    """
    fields = _fields_by_name(get_cable_schema(CABLE_TYPE_VALUES))

    assert fields[CableField.NAME][FieldKey.REQUIRED] is True
    assert [
        name for name, field in fields.items() if field.get(FieldKey.REQUIRED)
    ] == [CableField.NAME.value]


def test_cable_length_is_text_and_not_a_number() -> None:
    """'5 m' and '2.5 m' are the customer notations the concept keeps verbatim"""
    assert _fields_by_name(get_cable_schema([]))[CableField.LENGTH][FieldKey.TYPE] == FieldType.TEXT


def test_cable_color_is_free_text_for_v1() -> None:
    """Not a '#RRGGBB' value - a customer writes 'blue' or 'yellow/green'"""
    assert _fields_by_name(get_cable_schema([]))[CableField.COLOR][FieldKey.TYPE] == FieldType.TEXT


def test_cable_description_is_a_textarea() -> None:
    """A human fills this in, unlike the connection's own wire-level description field"""
    description = _fields_by_name(get_cable_schema([]))[CableField.DESCRIPTION]

    assert description[FieldKey.TYPE] == FieldType.TEXTAREA


def test_cable_schema_declares_no_reference_fields() -> None:
    """
    No reference fields means handle_special_types has nothing to cross-wire for a Cable

    Nothing points back at the connection either: cable_ci_id points one way only.
    """
    reference_types = {FieldType.REFERENCE, FieldType.REF_SECTION}
    field_types = {field[FieldKey.TYPE] for field in get_cable_schema([])[TypeSchemaKey.FIELDS]}

    assert not field_types & reference_types


def test_cable_schema_declares_no_location_field() -> None:
    """Unlike the Rack - nothing hangs off a cable, so it needs no place in the tree"""
    location_fields = [
        field for field in get_cable_schema([])[TypeSchemaKey.FIELDS]
        if field[FieldKey.TYPE] == FieldType.LOCATION
    ]

    assert location_fields == []


def test_the_cable_fields_mirror_the_connections_own_cable_info() -> None:
    """
    Scenario A and Scenario B must offer the same vocabulary

    A user filling in cable info on a connection and a user creating a Cable CI answer the same five
    questions; 'cable_ci_id' is the only connection key with no counterpart, being the reference
    itself.
    """
    connection_cable_fields = [
        key.value for key in CABLE_FIELD_KEYS if key is not PortConnectionKey.CABLE_CI_ID
    ]
    blueprint_fields = [
        field[FieldKey.NAME].value for field in get_cable_schema([])[TypeSchemaKey.FIELDS]
    ]

    assert [name.removeprefix('dg-') for name in blueprint_fields] == [
        name.replace('_', '-') for name in connection_cable_fields
    ]


# -------------------------------------------------------------------------------------------------------------------- #
#                                             the cable-type select options                                            #
# -------------------------------------------------------------------------------------------------------------------- #
def test_the_cable_type_field_is_a_select() -> None:
    """The one field of the blueprint that offers a list rather than free text"""
    assert _fields_by_name(get_cable_schema([]))[CableField.TYPE][FieldKey.TYPE] == FieldType.SELECT


def test_the_options_mirror_the_values_they_were_given() -> None:
    """Each value doubles as name and label, which makes a stored value readable on its own"""
    options = _fields_by_name(get_cable_schema(CABLE_TYPE_VALUES))[CableField.TYPE][FieldKey.OPTIONS]

    assert options == [
        {FieldKey.NAME: 'Cat6a', FieldKey.LABEL: 'Cat6a'},
        {FieldKey.NAME: 'OM4', FieldKey.LABEL: 'OM4'},
        {FieldKey.NAME: 'DAC', FieldKey.LABEL: 'DAC'},
    ]


def test_a_customer_added_value_reaches_the_blueprint() -> None:
    """
    Every CABLE_TYPE option that exists is snapshotted, not just the predefined ones

    A customer who already extended the list gets their own values in the type they create.
    """
    options = _fields_by_name(
        get_cable_schema(CABLE_TYPE_VALUES + [CUSTOMER_VALUE]),
    )[CableField.TYPE][FieldKey.OPTIONS]

    assert {FieldKey.NAME: CUSTOMER_VALUE, FieldKey.LABEL: CUSTOMER_VALUE} in options


def test_an_empty_option_list_yields_an_empty_select() -> None:
    """
    A customer may have deleted every CABLE_TYPE option

    The type is then created with an empty select - which the CmdbType schema allows - rather than
    refused, or silently back-filled from the predefined values.
    """
    assert _fields_by_name(get_cable_schema([]))[CableField.TYPE][FieldKey.OPTIONS] == []


def test_the_select_carries_no_option_type_key() -> None:
    """
    The asymmetry the snapshot exists for

    On a CONNECTION the cable type is a CABLE_TYPE option public_id. On a stored CmdbType field there
    is no 'option_type' key at all - the type schema does not list it, so Validator(purge_unknown=True)
    would drop it silently - which is why the values are inlined here instead.
    """
    assert FieldKey.OPTION_TYPE not in _fields_by_name(get_cable_schema(CABLE_TYPE_VALUES))[CableField.TYPE]


@pytest.mark.parametrize('values', [[], ['Cat6'], CABLE_TYPE_VALUES], ids=str)
def test_the_option_builder_is_a_pure_mapping(values: list[str]) -> None:
    """One option per value, in the order they were given"""
    assert [option[FieldKey.NAME] for option in build_cable_type_options(values)] == values


# -------------------------------------------------------------------------------------------------------------------- #
#                                                      sections                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def test_cable_uses_a_single_section_holding_every_field_in_order() -> None:
    """All five fields live in one Information section, in the documented order"""
    sections = get_cable_schema(CABLE_TYPE_VALUES)[TypeSchemaKey.SECTIONS]

    assert len(sections) == 1
    assert sections[0][SectionKey.TYPE] == SectionType.SECTION
    assert sections[0][SectionKey.NAME] == CableSection.INFORMATION
    assert sections[0][SectionKey.LABEL] == 'Information'
    assert sections[0][SectionKey.FIELDS] == [
        CableField.NAME,
        CableField.TYPE,
        CableField.LENGTH,
        CableField.COLOR,
        CableField.DESCRIPTION,
    ]


def test_every_section_field_has_a_definition() -> None:
    """No section may reference a field the blueprint does not define"""
    schema = get_cable_schema(CABLE_TYPE_VALUES)
    defined = set(_fields_by_name(schema))

    for section in schema[TypeSchemaKey.SECTIONS]:
        assert set(section[SectionKey.FIELDS]) <= defined


def test_every_defined_field_is_placed_in_a_section() -> None:
    """A field defined but never placed would be invisible in the type"""
    schema = get_cable_schema(CABLE_TYPE_VALUES)
    placed = {name for section in schema[TypeSchemaKey.SECTIONS] for name in section[SectionKey.FIELDS]}

    assert set(_fields_by_name(schema)) == placed
