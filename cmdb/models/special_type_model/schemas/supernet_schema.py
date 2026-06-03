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
Definition of required sections and fields for the SpecialType SUPERNET
"""
from typing import Any

from cmdb.models.type_model import FieldType, SectionType, FieldKey, SectionKey, TypeSchemaKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import SupernetField, IpAddressFamily, IpamSection
from cmdb.models.special_type_model.schemas.cidr_regex import CIDR_REGEX
# -------------------------------------------------------------------------------------------------------------------- #

def get_supernet_schema() -> dict[str, Any]:
    """
    Builds the section/field blueprint for the SUPERNET SpecialType

    The 'dg-supernet-type' field is a required IPv4/IPv6 address-family selector and the
    'dg-network-range' field is required and validated as an IPv4 or IPv6 CIDR; subnet objects
    are later checked for same-family containment within this range

    Returns:
        dict[str, Any]: Blueprint with the SUPERNET sections, fields and 'special_type' marker
    """
    return {
        TypeSchemaKey.SPECIAL_TYPE: SpecialType.SUPERNET,
        TypeSchemaKey.SECTIONS: [
            {
                SectionKey.TYPE: SectionType.SECTION,
                SectionKey.NAME: IpamSection.INFORMATION,
                SectionKey.LABEL: 'Information',
                SectionKey.FIELDS: [
                    SupernetField.NAME,
                ],
            },
            {
                SectionKey.TYPE: SectionType.SECTION,
                SectionKey.NAME: IpamSection.NETWORK_DETAILS,
                SectionKey.LABEL: 'Network Details',
                SectionKey.FIELDS: [
                    SupernetField.TYPE,
                    SupernetField.NETWORK_RANGE,
                ],
            },
        ],
        TypeSchemaKey.FIELDS: [
            {
                FieldKey.TYPE: FieldType.TEXT,
                FieldKey.NAME: SupernetField.NAME,
                FieldKey.LABEL: 'Name',
            },
            {
                # Required address-family selector, mirroring the SUBNET type field; the validators
                # cross-check it against the network range's actual family
                FieldKey.TYPE: FieldType.SELECT,
                FieldKey.NAME: SupernetField.TYPE,
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
                FieldKey.NAME: SupernetField.NETWORK_RANGE,
                FieldKey.LABEL: 'Network Range',
                FieldKey.REQUIRED: True,
                FieldKey.REGEX: CIDR_REGEX,
            },
        ],
    }
