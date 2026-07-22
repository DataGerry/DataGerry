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
<<<<<<< HEAD

from cmdb.manager.types_manager import TypesManager
from cmdb.manager.section_templates_manager import SectionTemplatesManager
=======
from typing import Any
>>>>>>> origin/version-3.2

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
    def create_profile(self) -> dict[str, int | None]:
        """
        Creates all types of the 'User Management' profile (Company, User, Customer User)

        Returns:
            dict[str, int | None]: The shared slot map of created type ids
        """
        # Each type is created (inserted) before the next is built, so a type's reference fields can
        # resolve the public_ids of types created earlier in this profile (Customer User -> Company)
        self.create_basic_type('company_id', self.get_company_type())
        self.create_basic_type('user_id', self.get_user_type())
        self.create_basic_type('customer_user_id', self.get_customer_user_type(self.created_type_ids['company_id']))

        return self.created_type_ids

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  TYPE DATA - SECTION                                                 #
# -------------------------------------------------------------------------------------------------------------------- #

    def get_company_type(self) -> dict[str, Any]:
        """
        Builds the 'Company' type for the 'User Management' profile

        Returns:
            dict[str, Any]: The Company CmdbType config
        """
        company_sections: list[dict[str, Any]] = [
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

        company_type: dict[str, Any] = self.type_constructor.create_type_config(
            company_sections,
            'company',
            'Company',
            'fas fa-building'
        )

        return company_type

# -------------------------------------------------------------------------------------------------------------------- #

    def get_user_type(self) -> dict[str, Any]:
        """
        Builds the 'User' type for the 'User Management' profile

        Returns:
            dict[str, Any]: The User CmdbType config
        """
        user_sections: list[dict[str, Any]] = [
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

        user_type: dict[str, Any] = self.type_constructor.create_type_config(
            user_sections,
            'user',
            'User',
            'fas fa-male'
        )

        return user_type

# -------------------------------------------------------------------------------------------------------------------- #

    def get_customer_user_type(self, company_type_id: int) -> dict[str, Any]:
        """
        Builds the 'Customer User' type for the 'User Management' profile

        Args:
            company_type_id (int): public_id of the created 'Company' type, referenced by this type

        Returns:
            dict[str, Any]: The Customer User CmdbType config
        """
        customer_user_sections: list[dict[str, Any]] = [
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

        customer_user_type: dict[str, Any] = self.type_constructor.create_type_config(
            customer_user_sections,
            'customer_user',
            'Customer User',
            'fas fa-user-tie'
        )

        return customer_user_type
