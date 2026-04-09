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
This module manages the 'Network Infrastructure'-Profile for the DataGerry assistant
"""
from logging import Logger, getLogger

from cmdb.manager.types_manager import TypesManager
from cmdb.manager.section_templates_manager import SectionTemplatesManager

from .profile_base import ProfileBase
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                         NetworkInfrastructureProfile - CLASS                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class NetworkInfrastructureProfile(ProfileBase):
    """
    This class cointains all types and logics for the 'Network Infrastructure'-Profile
    """
    def __init__(
            self,
            created_type_ids: dict,
            types_manager: TypesManager,
            section_templates_manager: SectionTemplatesManager):
        self.created_type_ids = created_type_ids
        super().__init__(created_type_ids, types_manager, section_templates_manager)


    def create_network_infrastructure_profile(self) -> dict:
        """
        Creates all types from the 'Network Infrastructure'- Profile

        Returns:
            dict: The created type ids dict
        """
        # Do NOT change the order of data due dependency
        network_infrastructure_profile_data: dict = {
            'switch_id' : self.get_switch_type(),
            'router_id': self.get_router_type(),
            'patch_panel_id': self.get_patch_panel_type(),
            'wireless_access_point_id': self.get_wireless_access_point_type(),
        }

        for type_name, type_dict in network_infrastructure_profile_data.items():
            self.create_basic_type(type_name, type_dict)

        return self.created_type_ids

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  TYPE DATA - SECTION                                                 #
# -------------------------------------------------------------------------------------------------------------------- #

    def get_switch_type(self) -> dict:
        """
        Returns the 'Switch'-Type for the 'Network Infrastructure'-Profile
        """
        switch_sections: list = [
            {
                "name": "section-25269",
                "label": "Information",
                "fields": [
                    {
                        "type": "text",
                        "name": "text-60980",
                        "label": "Name",
                        "is_summary": True
                    }
                ]
            },
            self.type_constructor.get_predefined_template_data('dg-modelspec',['dg-modelspec-model']),
            self.type_constructor.get_predefined_template_data('dg-network'),
            self.type_constructor.get_predefined_template_data('dg-rackmounting', ['dg-rackmounting-position']),
            {
                "name": "section-78906",
                "label": "Location",
                "fields": [
                    {
                        "type": "location",
                        "name": "dg_location",
                        "label": "Location"
                    }
                ]
            }
        ]

        switch_type: dict = self.type_constructor.create_type_config(switch_sections,
                                                                    'switch',
                                                                    'Switch',
                                                                    'far fa-object-ungroup')

        conditional_sections: list = [
            self.type_constructor.create_conditional_ref_section(
                                        "ref-71899",
                                        "OS",
                                        "section-13463",
                                        "Operating system",
                                        [
                                            self.get_created_id("operating_system_id")
                                        ]),
            self.type_constructor.create_conditional_ref_section(
                                        "ref-41420",
                                        "User",
                                        "section-73669",
                                        "User assignment",
                                        [
                                            self.get_created_id("user_id"),
                                            self.get_created_id("customer_user_id")
                                        ])
        ]

        self.type_constructor.add_conditional_sections(conditional_sections)

        return switch_type

# -------------------------------------------------------------------------------------------------------------------- #

    def get_router_type(self):
        """
        Returns the 'Router'-Type for the 'Network Infrastructure'-Profile
        """
        router_sections: list = [
            {
                "name": "section-64712",
                "label": "Information",
                "fields": [
                    {
                        "type": "text",
                        "name": "text-60624",
                        "label": "Name",
                        "is_summary": True
                    }
                ]
            },
            self.type_constructor.get_predefined_template_data('dg-modelspec',['dg-modelspec-model']),
            self.type_constructor.get_predefined_template_data('dg-network'),
            self.type_constructor.get_predefined_template_data('dg-rackmounting', ['dg-rackmounting-position']),
            {
                "name": "section-98615",
                "label": "Location",
                "fields": [
                    {
                        "type": "location",
                        "name": "dg_location",
                        "label": "Location"
                    }
                ]
            },
        ]

        router_type: dict = self.type_constructor.create_type_config(router_sections,
                                                                    'router',
                                                                    'Router',
                                                                    'fas fa-route')

        conditional_sections: list = [
            self.type_constructor.create_conditional_ref_section(
                                        "ref-68233",
                                        "OS",
                                        "section-68634",
                                        "Operating system",
                                        [
                                            self.get_created_id("operating_system_id")
                                        ]),
            self.type_constructor.create_conditional_ref_section(
                                        "ref-58400",
                                        "User",
                                        "section-27633",
                                        "User assignment",
                                        [
                                            self.get_created_id("user_id"),
                                            self.get_created_id("customer_user_id")
                                        ])
        ]

        self.type_constructor.add_conditional_sections(conditional_sections)

        return router_type

# -------------------------------------------------------------------------------------------------------------------- #

    def get_patch_panel_type(self):
        """
        Returns the 'Patch Panel'-Type for the 'Network Infrastructure'-Profile
        """
        patch_panel_sections: list = [
            {
                "name": "section-51132",
                "label": "Information",
                "fields": [
                    {
                        "type": "text",
                        "name": "text-89632",
                        "label": "Name",
                        "is_summary": True
                    }
                ]
            },
            self.type_constructor.get_predefined_template_data('dg-modelspec',['dg-modelspec-model']),
            self.type_constructor.get_predefined_template_data('dg-rackmounting', ['dg-rackmounting-position']),
            {
                "name": "section-99357",
                "label": "Location",
                "fields": [
                    {
                        "type": "location",
                        "name": "dg_location",
                        "label": "Location"
                    }
                ]
            }
        ]

        patch_panel_type: dict = self.type_constructor.create_type_config(patch_panel_sections,
                                                            'patch_panel',
                                                            'Patch Panel',
                                                            'fas fa-bezier-curve')

        return patch_panel_type

# -------------------------------------------------------------------------------------------------------------------- #

    def get_wireless_access_point_type(self):
        """
        Returns the 'Wireless Access Point'-Type for the 'Network Infrastructure'-Profile
        """
        wap_sections: list = [
            {
                "name": "section-18971",
                "label": "Information",
                "fields": [
                    {
                        "type": "text",
                        "name": "text-83971",
                        "label": "Name",
                        "is_summary": True
                    }
                ]
            },
            self.type_constructor.get_predefined_template_data('dg-modelspec'),
            self.type_constructor.get_predefined_template_data('dg-network'),
            {
                "name": "section-30882",
                "label": "WIFI data",
                "fields": [
                    {
                        "type": "text",
                        "name": "text-97978",
                        "label": "SSID",
                        "is_summary": True
                    },
                    {
                        "type": "text",
                        "name": "text-60846",
                        "label": "Standard"
                    },
                    {
                        "type": "text",
                        "name": "text-17637",
                        "label": "Channel"
                    },
                    {
                        "type": "text",
                        "name": "text-46053",
                        "label": "Authentification"
                    },
                    {
                        "type": "text",
                        "name": "text-35494",
                        "label": "Encryption"
                    },
                ]
            },
            {
                "name": "section-67101",
                "label": "Location",
                "fields": [
                    {
                        "type": "location",
                        "name": "dg_location",
                        "label": "Location"
                    }
                ]
            }
        ]

        wap_type: dict = self.type_constructor.create_type_config(wap_sections,
                                                    'wireless_access_point',
                                                    'Wireless Access Point',
                                                    'fas fa-exchange-alt')

        conditional_sections: list = [
            self.type_constructor.create_conditional_ref_section(
                                        "ref-36834",
                                        "User",
                                        "section-89120",
                                        "User assignment",
                                        [
                                            self.get_created_id("user_id"),
                                            self.get_created_id("customer_user_id")
                                        ])
        ]

        self.type_constructor.add_conditional_sections(conditional_sections)

        return wap_type
