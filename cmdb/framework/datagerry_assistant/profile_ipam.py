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
This module manages the IPAM - Profile for the DataGerry assistant
"""
from logging import Logger, getLogger

from cmdb.manager import TypesManager, SectionTemplatesManager

from .profile_base import ProfileBase
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  IPAMProfile - CLASS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class IPAMProfile(ProfileBase):
    """
    This class cointains all types and logics for the 'IPAM'-Profile
    """
    def __init__(
            self,
            created_type_ids: dict,
            types_manager: TypesManager,
            section_templates_manager: SectionTemplatesManager):
        self.created_type_ids = created_type_ids
        super().__init__(created_type_ids, types_manager, section_templates_manager)


    def create_ipam_profile(self) -> dict:
        """
        Creates all types from the 'IPAM'- Profile

        Returns:
            dict: The created type ids dict
        """
        ipam_profile_data: dict = {
            'network_id' : self.get_network_type()
        }

        for type_name, type_dict in ipam_profile_data.items():
            self.create_basic_type(type_name, type_dict)

        #dependent types
        self.create_basic_type('vlan_id', self.get_vlan_type(self.created_type_ids['network_id']))

        return self.created_type_ids

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  TYPE DATA - SECTION                                                 #
# -------------------------------------------------------------------------------------------------------------------- #

    def get_network_type(self) -> dict:
        """
        Returns the 'Network'-Type for the 'IPAM'-Profile
        """
        network_sections: list = [
            {
                "name": "section-94720",
                "label": "Information",
                "fields": [
                    {
                        "type": "text",
                        "name": "text-71148",
                        "label": "Name",
                        "is_summary": True
                    }
                ]
            },
            {
                "name": "section-99747",
                "label": "Network details",
                "fields": [
                    {
                        "type": "text",
                        "name": "text-66245",
                        "label": "Suffix",
                        "is_summary": True
                    },
                    {
                        "type": "text",
                        "name": "text-35330",
                        "label": "IP",
                        "is_summary": True
                    }
                ]
            }
        ]

        network_type: dict = self.type_constructor.create_type_config(network_sections,
                                                                      'network',
                                                                      'Network',
                                                                      'fas fa-network-wired')

        return network_type

# -------------------------------------------------------------------------------------------------------------------- #

    def get_vlan_type(self, network_type_id: int) -> dict:
        """
        Returns the 'VLAN'-Type for the 'IPAM'-Profile

        Args:
            network_type_id (int): public_id of created 'Network'-Type
        """
        vlan_sections: list = [
            {
                "name": "section-23481",
                "label": "Information",
                "fields": [
                    {
                        "type": "text",
                        "name": "text-45705",
                        "label": "Name",
                        "is_summary": True
                    }
                ]
            },
            {
                "name": "section-39385",
                "label": "VLAN data",
                "fields": [
                    {
                        "type": "text",
                        "name": "text-78263",
                        "label": "VLAN ID",
                        "is_summary": True
                    },
                    {
                        "type": "ref",
                        "name": "ref-43922",
                        "label": "Network",
                        "is_summary": True,
                        "extras": {
                            "ref_types": [
                                network_type_id
                            ],
                            "summaries": []
                        }
                    }
                ]
            }
        ]

        vlan_type: dict = self.type_constructor.create_type_config(vlan_sections,
                                                                    'vlan',
                                                                    'VLAN',
                                                                    'fas fa-wave-square')

        return vlan_type
