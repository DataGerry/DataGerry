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
Unit tests for cmdb.models.special_type_model.schemas.rack_schema

Pins the RACK blueprint: the field names (a field name is its immutable identifier, so these values
are a stored-data contract), which fields are required, the single-section layout and its field
order, and the location field that makes "assign a Rack to a Location" work. Also asserts the Rack
carries no reference fields, which is why it needs no post-insert cross-wiring
"""
from typing import Any

from cmdb.models.type_model import FieldType, SectionType, FieldKey, SectionKey, TypeSchemaKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.rack_constants import RackField, RackSection
from cmdb.models.special_type_model.schemas.rack_schema import get_rack_schema
# -------------------------------------------------------------------------------------------------------------------- #


def _fields_by_name(schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Indexes the schema's flat field definitions by their name"""
    return {field[FieldKey.NAME]: field for field in schema[TypeSchemaKey.FIELDS]}

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  identity / marker                                                   #
# -------------------------------------------------------------------------------------------------------------------- #

def test_rack_schema_is_marked_as_the_rack_special_type() -> None:
    """The blueprint carries the RACK marker, which is what claims the SpecialType on insert"""
    assert get_rack_schema()[TypeSchemaKey.SPECIAL_TYPE] == SpecialType.RACK


def test_rack_field_names_are_pinned() -> None:
    """
    A field's name is its immutable identifier

    Renaming one would orphan the stored value on every existing Rack object, so these strings are
    a data contract and this test is the tripwire.
    """
    assert RackField.NAME == 'dg-rack-name'
    assert RackField.NUMBER == 'dg-rack-number'
    assert RackField.HEIGHT == 'dg-rack-height'
    assert RackField.NOTES == 'dg-rack-notes'
    assert RackField.LOCATION == 'dg_location'

# -------------------------------------------------------------------------------------------------------------------- #
#                                                       fields                                                         #
# -------------------------------------------------------------------------------------------------------------------- #

def test_rack_name_is_a_required_text_field() -> None:
    """Rackname is required, so a Rack always has a human-readable identity"""
    name_field = _fields_by_name(get_rack_schema())[RackField.NAME]

    assert name_field[FieldKey.TYPE] == FieldType.TEXT
    assert name_field[FieldKey.LABEL] == 'Rackname'
    assert name_field[FieldKey.REQUIRED] is True


def test_rack_height_is_a_required_number_field() -> None:
    """Height is the U count and is required"""
    height_field = _fields_by_name(get_rack_schema())[RackField.HEIGHT]

    assert height_field[FieldKey.TYPE] == FieldType.NUMBER
    assert height_field[FieldKey.LABEL] == 'Height'
    assert height_field[FieldKey.REQUIRED] is True


def test_rack_number_and_notes_are_optional() -> None:
    """Racknumber and Notes carry no 'required' marker"""
    fields = _fields_by_name(get_rack_schema())

    assert FieldKey.REQUIRED not in fields[RackField.NUMBER]
    assert FieldKey.REQUIRED not in fields[RackField.NOTES]


def test_rack_notes_is_a_textarea() -> None:
    """Notes is multi-line free text, not a single-line text field"""
    assert _fields_by_name(get_rack_schema())[RackField.NOTES][FieldKey.TYPE] == FieldType.TEXTAREA


def test_rack_number_is_a_text_field() -> None:
    """Racknumber is a string, not a number - it may carry non-numeric identifiers"""
    assert _fields_by_name(get_rack_schema())[RackField.NUMBER][FieldKey.TYPE] == FieldType.TEXT


def test_rack_has_exactly_one_location_field() -> None:
    """
    A CmdbType has at most one location field, and the Rack's is what places it in the tree

    The location machinery matches on the field's TYPE, never on its name.
    """
    location_fields = [
        field for field in get_rack_schema()[TypeSchemaKey.FIELDS]
        if field[FieldKey.TYPE] == FieldType.LOCATION
    ]

    assert len(location_fields) == 1
    assert location_fields[0][FieldKey.NAME] == RackField.LOCATION


def test_rack_schema_declares_no_reference_fields() -> None:
    """
    No reference fields means handle_special_types has nothing to cross-wire for a Rack

    If a reference field is ever added, the post-insert wiring must be revisited.
    """
    reference_types = {FieldType.REFERENCE, FieldType.REF_SECTION}
    field_types = {field[FieldKey.TYPE] for field in get_rack_schema()[TypeSchemaKey.FIELDS]}

    assert not field_types & reference_types

# -------------------------------------------------------------------------------------------------------------------- #
#                                                      sections                                                        #
# -------------------------------------------------------------------------------------------------------------------- #

def test_rack_uses_a_single_section_holding_every_field_in_order() -> None:
    """All five fields live in one Information section, in the documented order"""
    schema = get_rack_schema()
    sections = schema[TypeSchemaKey.SECTIONS]

    assert len(sections) == 1
    assert sections[0][SectionKey.TYPE] == SectionType.SECTION
    assert sections[0][SectionKey.NAME] == RackSection.INFORMATION
    assert sections[0][SectionKey.LABEL] == 'Information'
    assert sections[0][SectionKey.FIELDS] == [
        RackField.NAME,
        RackField.NUMBER,
        RackField.HEIGHT,
        RackField.NOTES,
        RackField.LOCATION,
    ]


def test_every_section_field_has_a_definition() -> None:
    """No section may reference a field the blueprint does not define"""
    schema = get_rack_schema()
    defined = set(_fields_by_name(schema))

    for section in schema[TypeSchemaKey.SECTIONS]:
        assert set(section[SectionKey.FIELDS]) <= defined


def test_every_defined_field_is_placed_in_a_section() -> None:
    """A field defined but never placed would be invisible in the type"""
    schema = get_rack_schema()
    placed = {name for section in schema[TypeSchemaKey.SECTIONS] for name in section[SectionKey.FIELDS]}

    assert set(_fields_by_name(schema)) == placed
