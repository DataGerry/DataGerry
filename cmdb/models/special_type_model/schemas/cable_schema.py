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
Definition of required sections and fields for the SpecialType CABLE
"""
from typing import Any

from cmdb.models.type_model import FieldType, SectionType, FieldKey, SectionKey, TypeSchemaKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.cable_constants import CableField, CableSection
# -------------------------------------------------------------------------------------------------------------------- #

def build_cable_type_options(cable_type_values: list[str]) -> list[dict[str, Any]]:
    """
    Turns cable-type values into the inline 'options' list of an ordinary CmdbType select

    A stored CmdbType field has no 'option_type' key - the type schema does not list one, so
    ``Validator(..., purge_unknown=True)`` would drop it silently. The Cable CI therefore cannot point
    at the CABLE_TYPE CmdbExtendableOption list the way a connection's own cable_type does; it carries
    a snapshot of the values instead. Each value doubles as the option's name and its label, which is
    what makes a stored Cable object's value readable on its own

    Args:
        cable_type_values (list[str]): The cable-type values to offer, in the order they are shown

    Returns:
        list[dict[str, Any]]: The inline select options, empty when no value was given
    """
    return [
        {
            FieldKey.NAME: value,
            FieldKey.LABEL: value,
        }
        for value in cable_type_values
    ]


def get_cable_schema(cable_type_values: list[str]) -> dict[str, Any]:
    """
    Builds the section/field blueprint for the CABLE SpecialType

    A pure function like every other builder here: the CABLE_TYPE values are READ BY THE CALLER and
    passed in, so this layer stays free of the database and of mocks. An empty list is a legitimate
    input - a customer may have deleted every CABLE_TYPE option, and the type is then created with an
    empty select (schema-legal) rather than refused or silently back-filled from the predefined values.

    Like the Rack, the Cable needs no post-insert cross-wiring: it holds no reference fields, so
    handle_special_types has nothing to do for it. It has no location field either - nothing hangs off
    a cable - and no reference back to the connection that uses it

    Args:
        cable_type_values (list[str]): Every CABLE_TYPE option value that exists at creation time.
            Snapshotted into the select's inline options; the two lists drift from then on and the
            connection's own cable_type stays authoritative for a link

    Returns:
        dict[str, Any]: Blueprint with the CABLE section, fields and 'special_type' marker
    """
    return {
        TypeSchemaKey.SPECIAL_TYPE: SpecialType.CABLE,
        TypeSchemaKey.SECTIONS: [
            {
                SectionKey.TYPE: SectionType.SECTION,
                SectionKey.NAME: CableSection.INFORMATION,
                SectionKey.LABEL: 'Information',
                SectionKey.FIELDS: [
                    CableField.NAME,
                    CableField.TYPE,
                    CableField.LENGTH,
                    CableField.COLOR,
                    CableField.DESCRIPTION,
                ],
            },
        ],
        TypeSchemaKey.FIELDS: [
            {
                FieldKey.TYPE: FieldType.TEXT,
                FieldKey.NAME: CableField.NAME,
                FieldKey.LABEL: 'Cable name',
                FieldKey.REQUIRED: True,
            },
            {
                FieldKey.TYPE: FieldType.SELECT,
                FieldKey.NAME: CableField.TYPE,
                FieldKey.LABEL: 'Cable type',
                FieldKey.OPTIONS: build_cable_type_options(cable_type_values),
            },
            {
                # Text, not number: '5 m' and '2.5 m' are the notations customers use
                FieldKey.TYPE: FieldType.TEXT,
                FieldKey.NAME: CableField.LENGTH,
                FieldKey.LABEL: 'Length',
            },
            {
                FieldKey.TYPE: FieldType.TEXT,
                FieldKey.NAME: CableField.COLOR,
                FieldKey.LABEL: 'Color',
            },
            {
                FieldKey.TYPE: FieldType.TEXTAREA,
                FieldKey.NAME: CableField.DESCRIPTION,
                FieldKey.LABEL: 'Description',
            },
        ],
    }
