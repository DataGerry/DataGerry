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

CIDR_REGEX = r'^(?:(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]\d?|0)(?:\.(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]\d?|0)){3})/(?:3[0-2]|[12]?\d)$'

# -------------------------------------------------------------------------------------------------------------------- #
def get_subnet_schema(supernet_id: int) -> dict[str, Any]:
    """TODO: document"""
    return {
        'special_type': SpecialType.SUBNET,
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
                'name': 'dg_network_details',
                'label': 'Network Details',
                'fields': [
                    'dg_supernet_ref',
                    'dg_network_range'
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
                'name': 'dg_supernet_ref',
                'label': 'Supernet',
                'ref_types': [supernet_id]
            },
            {
                'type': 'text',
                'name': 'dg_network_range',
                'label': 'Network Range',
                'regex': CIDR_REGEX
            },
        ]
    }
