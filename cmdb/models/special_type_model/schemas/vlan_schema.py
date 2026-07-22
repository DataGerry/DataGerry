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
<<<<<<< HEAD
Definition of required sections and fields for the SpecialType SUBNET
"""
from typing import Any

from cmdb.models.special_type_model.special_type_enum import SpecialType
# -------------------------------------------------------------------------------------------------------------------- #

def get_vlan_schema(subnet_id: int) -> dict[str, Any]:
    """TODO: document"""
    return {
        'special_type': SpecialType.VLAN,
        'sections': [
            {
                'type': 'section',
                'name': 'dg_information',
                'label': 'Information',
                'fields': [
                    'dg_name'
                ]
            },
            {
                'type': 'section',
                'name': 'dg_vlan_details',
                'label': 'Vlan Details',
                'fields': [
                    'dg_subnet_ref',
                    'dg_vlan_type'
                ]
            },
        ],
        'fields': [
            {
                'type': 'text',
                'name': 'dg_name',
                'label': 'Name'
            },
            {
                'type': 'ref',
                'name': 'dg_subnet_ref',
                'label': 'Subnet',
                'ref_types': [subnet_id]
            },
            {
                'type': 'select',
                'name': 'dg_vlan_type',
                'label': 'Type',
                'options': [
                    {
                        'name': 'static',
                        'Label': 'Static'
                    },
                    {
                        'name': 'dynamic',
                        'Label': 'Dynamic'
                    }
                ]
            },
        ]
=======
Definition of required sections and fields for the SpecialType VLAN
"""
from typing import Any

from cmdb.models.type_model import FieldType, SectionType, FieldKey, SectionKey, TypeSchemaKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import VlanField, IpamSection
# -------------------------------------------------------------------------------------------------------------------- #

def get_vlan_schema() -> dict[str, Any]:
    """
    Builds the section/field blueprint for the VLAN SpecialType

    The 'dg-subnet-ref' field is returned with an empty 'ref_types'; the list is populated
    post-insert by handle_special_types once a SUBNET SpecialType exists

    Returns:
        dict[str, Any]: Blueprint with the VLAN sections, fields and 'special_type' marker
    """
    return {
        TypeSchemaKey.SPECIAL_TYPE: SpecialType.VLAN,
        TypeSchemaKey.SECTIONS: [
            {
                SectionKey.TYPE: SectionType.SECTION,
                SectionKey.NAME: IpamSection.INFORMATION,
                SectionKey.LABEL: 'Information',
                SectionKey.FIELDS: [
                    VlanField.NAME,
                ],
            },
            {
                SectionKey.TYPE: SectionType.SECTION,
                SectionKey.NAME: IpamSection.VLAN_DETAILS,
                SectionKey.LABEL: 'Vlan Details',
                SectionKey.FIELDS: [
                    VlanField.SUBNET_REF,
                    VlanField.TYPE,
                ],
            },
        ],
        TypeSchemaKey.FIELDS: [
            {
                FieldKey.TYPE: FieldType.TEXT,
                FieldKey.NAME: VlanField.NAME,
                FieldKey.LABEL: 'Name',
            },
            {
                FieldKey.TYPE: FieldType.REFERENCE,
                FieldKey.NAME: VlanField.SUBNET_REF,
                FieldKey.LABEL: 'Subnet',
                FieldKey.DESCRIPTION: "Reference to Subnet SpecialType",
                FieldKey.REF_TYPES: [],
            },
            {
                FieldKey.TYPE: FieldType.SELECT,
                FieldKey.NAME: VlanField.TYPE,
                FieldKey.LABEL: 'Type',
                FieldKey.OPTIONS: [
                    {
                        FieldKey.NAME: 'static',
                        FieldKey.LABEL: 'Static',
                    },
                    {
                        FieldKey.NAME: 'dynamic',
                        FieldKey.LABEL: 'Dynamic',
                    },
                ],
            },
        ],
>>>>>>> origin/version-3.2
    }
