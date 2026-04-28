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

from cmdb.models.type_model import FieldType, SectionType
from cmdb.models.special_type_model.special_type_enum import SpecialType
# -------------------------------------------------------------------------------------------------------------------- #

def get_vlan_schema(subnet_id: int | None) -> dict[str, Any]:
    """TODO: document"""
    ref_types: list[int] = []

    if subnet_id:
        ref_types = [subnet_id]

    return {
        'special_type': SpecialType.VLAN,
        'sections': [
            {
                'type': SectionType.SECTION,
                'name': 'dg_information',
                'label': 'Information',
                'fields': [
                    'dg_name'
                ]
            },
            {
                'type': SectionType.SECTION,
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
                'type': FieldType.TEXT,
                'name': 'dg_name',
                'label': 'Name'
            },
            {
                'type': FieldType.REFERENCE,
                'name': 'dg_subnet_ref',
                'label': 'Subnet',
                'ref_types': ref_types
            },
            {
                'type': FieldType.SELECT,
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
    }
