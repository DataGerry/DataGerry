# DataGerry - OpenSource Enterprise CMDB
# Copyright (C) 2025 becon GmbH
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
This module manages the 'Server Management'-Profile for the DataGerry assistant
"""
import logging

from cmdb.manager.types_manager import TypesManager
from cmdb.manager.section_templates_manager import SectionTemplatesManager

from .profile_base import ProfileBase
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)


class ServerManagementProfile(ProfileBase):
    """
    This class cointains all types and logics for the 'Server Management'-Profile
    """
    def __init__(
            self,
            created_type_ids: dict,
            types_manager: TypesManager,
            section_templates_manager: SectionTemplatesManager):
        self.created_type_ids = created_type_ids
        super().__init__(created_type_ids, types_manager, section_templates_manager)


    def create_server_management_profile(self) -> dict:
        """
        Creates all types from the 'Server Management'- Profile

        Returns:
            dict: The created type ids dict
        """
        # Do NOT change the order of data due dependency
        server_management_profile_data: dict = {
            'server_id' : self.get_server_type(),
            'appliance_id': self.get_appliance_type(),
        }

        for type_name, type_dict in server_management_profile_data.items():
            self.create_basic_type(type_name, type_dict)

        self.create_basic_type('virtual_server_id', self.get_virtual_server_type(self.created_type_ids['server_id']))

        return self.created_type_ids

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  TYPE DATA - SECTION                                                 #
# -------------------------------------------------------------------------------------------------------------------- #

    def get_server_type(self) -> dict:
        """
        Returns the 'Server'-Type for the 'Server Management'-Profile
        """
        server_sections: list = [
            {
                "name": "section-64307",
                "label": "Information",
                "fields": [
                    {
                        "type": "text",
                        "name": "text-23531",
                        "label": "Name",
                        "is_summary": True
                    },
                    {
                        "type": "select",
                        "name": "select-27409",
                        "label": "Type",
                        "extras":{
                            "options": [
                                {
                                    "name": "Example",
                                    "label": "Example"
                                }
                            ]
                        }

                    }
                ]
            },
            self.type_constructor.get_predefined_template_data('dg-modelspec'),
            self.type_constructor.get_predefined_template_data('dg-network'),
            self.type_constructor.get_predefined_template_data('dg-rackmounting'),
            {
                "name": "section-77142",
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

        server_type: dict = self.type_constructor.create_type_config(server_sections,
                                                                        'server',
                                                                        'Server',
                                                                        'fas fa-server')

        conditional_sections: list = [
            self.type_constructor.create_conditional_ref_section(
                                        "ref-38286",
                                        "OS",
                                        "section-54364",
                                        "Operating system",
                                        [
                                            self.get_created_id("operating_system_id")
                                        ]),
            self.type_constructor.create_conditional_ref_section(
                                        "ref-47089",
                                        "User",
                                        "section-69534",
                                        "User assignment",
                                        [
                                            self.get_created_id("user_id"),
                                            self.get_created_id("customer_user_id")
                                        ])
        ]

        self.type_constructor.add_conditional_sections(conditional_sections)

        return server_type

# -------------------------------------------------------------------------------------------------------------------- #

    def get_appliance_type(self) -> dict:
        """
        Returns the 'Appliance'-Type for the 'Server Management'-Profile
        """
        appliance_sections: list = [
            {
                "name": "section-63931",
                "label": "Information",
                "fields": [
                    {
                        "type": "text",
                        "name": "text-16979",
                        "label": "Name",
                        "is_summary": True
                    }
                ]
            },
            self.type_constructor.get_predefined_template_data('dg-modelspec'),
            self.type_constructor.get_predefined_template_data('dg-network'),
            self.type_constructor.get_predefined_template_data('dg-rackmounting'),
            {
                "name": "section-21475",
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

        appliance_type: dict = self.type_constructor.create_type_config(appliance_sections,
                                                                'appliance',
                                                                'Appliance',
                                                                'fas fa-wrench')

        conditional_sections: list = [
            self.type_constructor.create_conditional_ref_section(
                                        "ref-72670",
                                        "OS",
                                        "section-33112",
                                        "Operating system",
                                        [
                                            self.get_created_id("operating_system_id")
                                        ]),
            self.type_constructor.create_conditional_ref_section(
                                        "ref-98369",
                                        "User",
                                        "section-62843",
                                        "User assignment",
                                        [
                                            self.get_created_id("user_id"),
                                            self.get_created_id("customer_user_id")
                                        ])
        ]

        self.type_constructor.add_conditional_sections(conditional_sections)

        return appliance_type

# -------------------------------------------------------------------------------------------------------------------- #

    def get_virtual_server_type(self, server_type_id: int) -> dict:
        """
        Returns the 'Virtual Server'-Type for the 'Server Management'-Profile

        Args:
            server_type_id(int): public_id of 'Server'-Type
        """
        virtual_server_sections: list = [
            {
                "name": "section-60610",
                "label": "Information",
                "fields": [
                    {
                        "type": "text",
                        "name": "text-70141",
                        "label": "Name",
                        "is_summary": True
                    }
                ]
            },
            self.type_constructor.get_predefined_template_data('dg-network'),
            {
                "name": "section-28198",
                "label": "Virtual host",
                "fields": [
                    {
                        "type": "ref",
                        "name": "ref-65439",
                        "label": "Server",
                        "is_summary": True,
                        "extras":{
                            "ref_types": [
                                server_type_id
                            ],
                            "summaries": []
                        }
                    }
                ]
            }
        ]

        virtual_server_type: dict = self.type_constructor.create_type_config(virtual_server_sections,
                                                                            'virtual_server',
                                                                            'Virtual Server',
                                                                            'fas fa-cubes')

        conditional_sections: list = [
            self.type_constructor.create_conditional_ref_section(
                                        "ref-43625",
                                        "OS",
                                        "section-21793",
                                        "Operating system",
                                        [
                                            self.get_created_id("operating_system_id")
                                        ]),
            self.type_constructor.create_conditional_ref_section(
                                        "ref-63703",
                                        "User",
                                        "section-29427",
                                        "User assignment",
                                        [
                                            self.get_created_id("user_id"),
                                            self.get_created_id("customer_user_id")
                                        ])
        ]

        self.type_constructor.add_conditional_sections(conditional_sections)

        return virtual_server_type
