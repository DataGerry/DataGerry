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

from cmdb.models.type_model import FieldType, SectionType, FieldKey, SectionKey, TypeSchemaKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import SubnetField, IpAddressFamily, IpamSection
from cmdb.models.special_type_model.schemas.cidr_regex import CIDR_REGEX
# -------------------------------------------------------------------------------------------------------------------- #

def get_subnet_schema() -> dict[str, Any]:
    """
    Builds the section/field blueprint for the SUBNET SpecialType

    The 'dg-supernet-ref' reference field is returned with an empty 'ref_types'; the list
    is populated post-insert by handle_special_types once the SUPERNET SpecialType exists

    Returns:
        dict[str, Any]: Blueprint with the SUBNET sections, fields and 'special_type' marker
    """
    return {
        TypeSchemaKey.SPECIAL_TYPE: SpecialType.SUBNET,
        TypeSchemaKey.SECTIONS: [
            {
                SectionKey.TYPE: SectionType.SECTION,
                SectionKey.NAME: IpamSection.INFORMATION,
                SectionKey.LABEL: 'Information',
                SectionKey.FIELDS: [
                    SubnetField.NAME,
                ],
            },
            {
                SectionKey.TYPE: SectionType.SECTION,
                SectionKey.NAME: IpamSection.NETWORK_DETAILS,
                SectionKey.LABEL: 'Network Details',
                SectionKey.FIELDS: [
                    SubnetField.PARENT_SUPERNET,
                    SubnetField.TYPE,
                    SubnetField.NETWORK_RANGE,
                ],
            },
        ],
        TypeSchemaKey.FIELDS: [
            {
                FieldKey.TYPE: FieldType.TEXT,
                FieldKey.NAME: SubnetField.NAME,
                FieldKey.LABEL: 'Name',
            },
            {
                FieldKey.TYPE: FieldType.REFERENCE,
                FieldKey.NAME: SubnetField.PARENT_SUPERNET,
                FieldKey.LABEL: 'Supernet',
                FieldKey.DESCRIPTION: "Reference to Supernet SpecialType",
                FieldKey.REF_TYPES: [],
            },
            {
                # Required address-family selector; the validators cross-check it against the
                # network range's actual family (type_family_mismatch) and against the parent
                # supernet's family
                FieldKey.TYPE: FieldType.SELECT,
                FieldKey.NAME: SubnetField.TYPE,
                FieldKey.LABEL: 'Type',
                FieldKey.REQUIRED: True,
                FieldKey.OPTIONS: [
                    {
                        FieldKey.NAME: IpAddressFamily.IPV4,
                        FieldKey.LABEL: 'IPv4',
                    },
                    {
                        FieldKey.NAME: IpAddressFamily.IPV6,
                        FieldKey.LABEL: 'IPv6',
                    },
                ],
            },
            {
                FieldKey.TYPE: FieldType.TEXT,
                FieldKey.NAME: SubnetField.NETWORK_RANGE,
                FieldKey.LABEL: 'Network Range',
                FieldKey.REQUIRED: True,
                FieldKey.REGEX: CIDR_REGEX,
            },
        ],
    }
