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
This module manages the Client Management - Profile for the DataGerry assistant
"""
from logging import Logger, getLogger
from typing import Any

from .profile_base import ProfileBase
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)


class ClientManagementProfile(ProfileBase):
    """
    This class cointains all types and logics for the 'Client Management'-Profile
    """

    def create_profile(self) -> dict[str, int | None]:
        """
        Creates all types of the 'Client Management' profile (OS, Client, Printer, Monitor)

        Returns:
            dict[str, int | None]: The shared slot map of created type ids
        """
        # Each type is created (inserted) before the next is built, so a type's conditional reference
        # sections / reference fields can resolve the public_ids of types created earlier in this
        # profile (Client -> Operating System; Monitor -> Client)
        self.create_basic_type('operating_system_id', self.get_operating_system_type())
        self.create_basic_type('client_id', self.get_client_type())
        self.create_basic_type('printer_id', self.get_printer_type())
        self.create_basic_type('monitor_id', self.get_monitor_type(self.created_type_ids['client_id']))

        return self.created_type_ids

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  TYPE DATA - SECTION                                                 #
# -------------------------------------------------------------------------------------------------------------------- #

    def get_operating_system_type(self) -> dict[str, Any]:
        """
        Builds the 'Operating System' type for the 'Client Management' profile

        Returns:
            dict[str, Any]: The Operating System CmdbType config
        """
        operating_system_sections: list[dict[str, Any]] = [
            {
                "name": "section-72042",
                "label": "Information",
                "fields": [
                    {
                        "type": "text",
                        "name": "text-42835",
                        "label": "Name",
                        "is_summary": True
                    },
                ]
            },
            {
                "name": "section-64253",
                "label": "Version details",
                "fields": [
                    {
                        "type": "text",
                        "name": "text-25407",
                        "label": "Version",
                        "is_summary": True
                    },
                    {
                        "type": "text",
                        "name": "text-49533",
                        "label": "Variant",
                        "is_summary": True
                    }
                ]
            }
        ]

        operating_system_type: dict[str, Any] = self.type_constructor.create_type_config(
            operating_system_sections,
            'operating_system',
            'Operating System',
            'far fa-window-maximize'
        )

        return operating_system_type

# -------------------------------------------------------------------------------------------------------------------- #

    def get_client_type(self) -> dict[str, Any]:
        """
        Builds the 'Client' type for the 'Client Management' profile

        Includes the dg-modelspec and dg-network templates plus conditional reference sections to
        the Operating System and User / Customer User types (added only when those types exist).

        Returns:
            dict[str, Any]: The Client CmdbType config
        """
        client_sections: list[dict[str, Any]] = [
            {
                "name": "section-68471",
                "label": "Information",
                "fields": [
                    {
                        "type": "text",
                        "name": "text-98758",
                        "label": "Name",
                        "is_summary": True
                    }
                ]
            },
            self.type_constructor.get_predefined_template_data('dg-modelspec'),
            self.type_constructor.get_predefined_template_data('dg-network'),
            {
                "name": "section-11686",
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

        client_type: dict[str, Any] = self.type_constructor.create_type_config(
            client_sections,
            'client',
            'Client',
            'far fa-id-card'
        )

        conditional_sections: list[dict[str, Any]] = [
            self.type_constructor.create_conditional_ref_section(
                                        "ref-47570",
                                        "OS",
                                        "section-44174",
                                        "Operating system",
                                        [
                                            self.get_created_id("operating_system_id")
                                        ]),
            self.type_constructor.create_conditional_ref_section(
                                        "ref-58324",
                                        "User",
                                        "section-16359",
                                        "User assignment",
                                        [
                                            self.get_created_id("user_id"),
                                            self.get_created_id("customer_user_id")
                                        ])
        ]

        self.type_constructor.add_conditional_sections(conditional_sections)

        return client_type

# -------------------------------------------------------------------------------------------------------------------- #

    def get_monitor_type(self, client_type_id: int) -> dict[str, Any]:
        """
        Builds the 'Monitor' type for the 'Client Management' profile

        Args:
            client_type_id (int): public_id of the created 'Client' type, referenced by this type

        Returns:
            dict[str, Any]: The Monitor CmdbType config
        """
        monitor_sections: list[dict[str, Any]] = [
            {
                "name": "section-28964",
                "label": "Information",
                "fields": [
                    {
                        "type": "text",
                        "name": "text-39536",
                        "label": "Name",
                        "is_summary": True
                    }
                ]
            },
            self.type_constructor.get_predefined_template_data('dg-modelspec',['dg-modelspec-model']),
            {
                "name": "section-51050",
                "label": "Device assignment",
                "fields": [
                    {
                        "type": "ref",
                        "name": "ref-12314",
                        "label": "Device",
                        "extras":{
                            "ref_types": [
                                client_type_id
                            ],
                            "summaries": []
                        }
                    }
                ]
            },
            {
                "name": "section-39684",
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

        monitor_type: dict[str, Any] = self.type_constructor.create_type_config(
            monitor_sections,
            'monitor',
            'Monitor',
            'fas fa-desktop'
        )

        return monitor_type

# -------------------------------------------------------------------------------------------------------------------- #

    def get_printer_type(self) -> dict[str, Any]:
        """
        Builds the 'Printer' type for the 'Client Management' profile

        Returns:
            dict[str, Any]: The Printer CmdbType config
        """
        printer_sections: list[dict[str, Any]] = [
            {
                "name": "section-95376",
                "label": "Information",
                "fields": [
                    {
                        "type": "text",
                        "name": "text-78614",
                        "label": "Name",
                        "is_summary": True
                    }
                ]
            },
            self.type_constructor.get_predefined_template_data('dg-modelspec',['dg-modelspec-model']),
            self.type_constructor.get_predefined_template_data('dg-network'),
            {
                "name": "section-88306",
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

        printer_type: dict[str, Any] = self.type_constructor.create_type_config(
            printer_sections,
            'printer',
            'Printer',
            'fas fa-print'
        )

        return printer_type
