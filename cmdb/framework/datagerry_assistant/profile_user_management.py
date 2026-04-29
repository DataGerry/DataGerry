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
This module manages the 'User Management'-Profile for the DataGerry assistant
"""
from logging import Logger, getLogger

from cmdb.manager.types_manager import TypesManager
from cmdb.manager.section_templates_manager import SectionTemplatesManager

from .profile_base import ProfileBase
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                             UserManagementProfile - CLASS                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class UserManagementProfile(ProfileBase):
    """
    This class cointains all types and logics for the 'User management'-Profile
    """
    def __init__(
            self,
            created_type_ids: dict,
            types_manager: TypesManager,
            section_templates_manager: SectionTemplatesManager):
        self.created_type_ids = created_type_ids
        super().__init__(created_type_ids, types_manager, section_templates_manager)


    def create_user_management_profile(self) -> dict:
        """
        Creates all types from the 'User Management'- Profile

        Returns:
            dict: The created type ids dict
        """
        user_management_profile_data: dict = {
            'company_id' : self.get_company_type(),
            'user_id': self.get_user_type()
        }

        for type_name, type_dict in user_management_profile_data.items():
            self.create_basic_type(type_name, type_dict)

        # depedent types
        self.create_basic_type('customer_user_id', self.get_customer_user_type(self.created_type_ids['company_id']))

        return self.created_type_ids

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  TYPE DATA - SECTION                                                 #
# -------------------------------------------------------------------------------------------------------------------- #

    def get_company_type(self) -> dict:
        """
        Returns the 'Company'-Type for the 'User management'-Profile
        """
        company_sections: list = [
            {
                "name": "section-24931",
                "label": "Information",
                "fields": [
                    {
                        "type": "text",
                        "name": "text-19742",
                        "label": "Name",
                        "is_summary": True
                    }
                ]
            },
            {
                "name": "section-91843",
                "label": "Address",
                "fields": [
                    {
                        "type": "text",
                        "name": "text-29607",
                        "label": "Street"
                    },
                    {
                        "type": "text",
                        "name": "text-11283",
                        "label": "House number"
                    },
                    {
                        "type": "text",
                        "name": "text-52606",
                        "label": "Location",
                        "is_summary": True
                    },
                    {
                        "type": "text",
                        "name": "text-36017",
                        "label": "Postal code"
                    }
                ]
            }
        ]

        company_type: dict = self.type_constructor.create_type_config(company_sections,
                                                                      'company',
                                                                      'Company',
                                                                      'fas fa-building')

        return company_type

# -------------------------------------------------------------------------------------------------------------------- #

    def get_user_type(self) -> dict:
        """
        Returns the 'User'-Type for the 'User management'-Profile
        """
        user_sections: list = [
            {
                "name": "section-92803",
                "label": "Information",
                "fields": [
                    {
                        "type": "text",
                        "name": "text-45910",
                        "label": "Name",
                        "is_summary": True
                    },
                ]
            },
            {
                "name": "section-23984",
                "label": "Personal data",
                "fields": [
                    {
                        "type": "text",
                        "name": "text-80103",
                        "label": "First name"
                    },
                    {
                        "type": "text",
                        "name": "text-75307",
                        "label": "Last name"
                    },
                    {
                        "type": "text",
                        "name": "text-93543",
                        "label": "Email",
                        "is_summary": True
                    },
                    {
                        "type": "text",
                        "name": "text-16313",
                        "label": "Phone number"
                    }
                ]
            }
        ]

        user_type: dict = self.type_constructor.create_type_config(user_sections,
                                                                   'user',
                                                                   'User',
                                                                   'fas fa-male')

        return user_type

# -------------------------------------------------------------------------------------------------------------------- #

    def get_customer_user_type(self, company_type_id: int) -> dict:
        """
        Returns the 'Customer User'-Type for the 'User management'-Profile
        
        Args:
            company_type_id (int): public_id of created 'Company'-Type
        """
        customer_user_sections: list = [
            {
                "name": "section-82897",
                "label": "Information",
                "fields": [
                    {
                        "type": "text",
                        "name": "text-39929",
                        "label": "Name",
                        "is_summary": True
                    },
                ]
            },
            {
                "name": "section-62012",
                "label": "Personal data",
                "fields": [
                    {
                        "type": "text",
                        "name": "text-91469",
                        "label": "First name"
                    },
                    {
                        "type": "text",
                        "name": "text-84039",
                        "label": "Last name"
                    },
                    {
                        "type": "text",
                        "name": "text-27614",
                        "label": "Email",
                        "is_summary": True
                    },
                    {
                        "type": "text",
                        "name": "text-44997",
                        "label": "Phone number"
                    },
                    {
                        "type": "ref",
                        "name": "ref-25151",
                        "label": "Company",
                        "is_summary": True,
                        "extras": {
                            "ref_types": [
                                company_type_id
                            ],
                            "summaries": []
                        }

                    }
                ]
            }
        ]

        customer_user_type: dict = self.type_constructor.create_type_config(customer_user_sections,
                                                                            'customer_user',
                                                                            'Customer User',
                                                                            'fas fa-user-tie')
        return customer_user_type
