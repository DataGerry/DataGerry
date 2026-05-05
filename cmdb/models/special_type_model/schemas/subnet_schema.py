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
Definition of required sections and fields for the SpecialType SUBNET
"""
from typing import Any

from cmdb.models.type_model import FieldType, SectionType, FieldKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.schemas.cidr_regex import IPV4_CIDR_REGEX
# -------------------------------------------------------------------------------------------------------------------- #

def get_subnet_schema() -> dict[str, Any]:
    """
    Builds the section/field blueprint for the SUBNET SpecialType

    Reference fields ('dg-supernet-ref', 'dg-parent-subnet-ref') are returned with empty
    'ref_types'; the lists are populated post-insert by handle_special_types when the matching
    parent SpecialTypes exist

    Returns:
        dict[str, Any]: Blueprint with the SUBNET sections, fields and 'special_type' marker
    """
    return {
        FieldKey.SPECIAL_TYPE: SpecialType.SUBNET,
        FieldKey.SECTIONS: [
            {
                FieldKey.TYPE: SectionType.SECTION,
                FieldKey.NAME: 'dg-information',
                FieldKey.LABEL: 'Information',
                FieldKey.FIELDS: [
                    'dg-name',
                ],
            },
            {
                FieldKey.TYPE: SectionType.SECTION,
                FieldKey.NAME: 'dg-network-details',
                FieldKey.LABEL: 'Network Details',
                FieldKey.FIELDS: [
                    'dg-supernet-ref',
                    'dg-parent-subnet-ref',
                    'dg-network-range',
                ],
            },
        ],
        FieldKey.FIELDS: [
            {
                FieldKey.TYPE: FieldType.TEXT,
                FieldKey.NAME: 'dg-name',
                FieldKey.LABEL: 'Name',
            },
            {
                FieldKey.TYPE: FieldType.REFERENCE,
                FieldKey.NAME: 'dg-supernet-ref',
                FieldKey.LABEL: 'Supernet',
                FieldKey.DESCRIPTION: "Reference to Supernet SpecialType",
                FieldKey.REF_TYPES: [],
            },
            {
                FieldKey.TYPE: FieldType.REFERENCE,
                FieldKey.NAME: 'dg-parent-subnet-ref',
                FieldKey.LABEL: 'Parent Subnet',
                FieldKey.REF_TYPES: [],
            },
            {
                FieldKey.TYPE: FieldType.TEXT,
                FieldKey.NAME: 'dg-network-range',
                FieldKey.LABEL: 'Network Range',
                FieldKey.REQUIRED: True,
                FieldKey.REGEX: IPV4_CIDR_REGEX,
            },
        ],
    }
