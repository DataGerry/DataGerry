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

from cmdb.models.special_type_model.special_type_enum import SpecialType
# -------------------------------------------------------------------------------------------------------------------- #

def get_vlan_schema() -> dict[str, Any]:
    """TODO: document"""
    return {
        'special_type': SpecialType.VLAN,
        'sections': [
            {
                'type': 'section',
                'name': 'information',
                'label': 'Information',
                'fields': [
                    'name'
                ]
            },
            {
                'type': 'section',
                'name': 'network',
                'label': 'Network Details',
                'fields': [
                    'gateway'
                ]
            },
        ],
        'fields': [
            {
                'type': 'text',
                'name': 'name',
                'label': 'Name'
            },
            {
                'type': 'text',
                'name': 'gateway',
                'label': 'Gateway'
            },
        ]
    }
