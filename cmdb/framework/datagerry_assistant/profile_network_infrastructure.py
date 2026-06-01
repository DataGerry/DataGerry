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
from typing import Any

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
    def create_profile(self) -> dict[str, int | None]:
        """
        Creates all types of the 'Network Infrastructure' profile (Switch, Router, Patch Panel, WAP)

        Returns:
            dict[str, int | None]: The shared slot map of created type ids
        """
        # Each type is created (inserted) before the next is built, so a type's conditional reference
        # sections can resolve the public_ids of types created earlier in this (and prior) profiles
        self.create_basic_type('switch_id', self.get_switch_type())
        self.create_basic_type('router_id', self.get_router_type())
        self.create_basic_type('patch_panel_id', self.get_patch_panel_type())
        self.create_basic_type('wireless_access_point_id', self.get_wireless_access_point_type())

        return self.created_type_ids

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  TYPE DATA - SECTION                                                 #
# -------------------------------------------------------------------------------------------------------------------- #

    def get_switch_type(self) -> dict[str, Any]:
        """
        Builds the 'Switch' type for the 'Network Infrastructure' profile

        Includes the dg-modelspec, dg-network and dg-rackmounting templates plus conditional
        reference sections to the Operating System and User / Customer User types.

        Returns:
            dict[str, Any]: The Switch CmdbType config
        """
        switch_sections: list[dict[str, Any]] = [
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

        switch_type: dict[str, Any] = self.type_constructor.create_type_config(
            switch_sections,
            'switch',
            'Switch',
            'far fa-object-ungroup'
        )

        conditional_sections: list[dict[str, Any]] = [
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

    def get_router_type(self) -> dict[str, Any]:
        """
        Builds the 'Router' type for the 'Network Infrastructure' profile

        Includes the dg-modelspec, dg-network and dg-rackmounting templates plus conditional
        reference sections to the Operating System and User / Customer User types.

        Returns:
            dict[str, Any]: The Router CmdbType config
        """
        router_sections: list[dict[str, Any]] = [
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

        router_type: dict[str, Any] = self.type_constructor.create_type_config(
            router_sections,
            'router',
            'Router',
            'fas fa-route'
        )

        conditional_sections: list[dict[str, Any]] = [
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

    def get_patch_panel_type(self) -> dict[str, Any]:
        """
        Builds the 'Patch Panel' type for the 'Network Infrastructure' profile

        Includes the dg-modelspec and dg-rackmounting templates. Unlike the other network types it
        has no conditional reference sections.

        Returns:
            dict[str, Any]: The Patch Panel CmdbType config
        """
        patch_panel_sections: list[dict[str, Any]] = [
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

        patch_panel_type: dict[str, Any] = self.type_constructor.create_type_config(
            patch_panel_sections,
            'patch_panel',
            'Patch Panel',
            'fas fa-bezier-curve'
        )

        return patch_panel_type

# -------------------------------------------------------------------------------------------------------------------- #

    def get_wireless_access_point_type(self) -> dict[str, Any]:
        """
        Builds the 'Wireless Access Point' type for the 'Network Infrastructure' profile

        Includes the dg-modelspec and dg-network templates plus a conditional reference section to
        the User / Customer User types (no Operating System reference, unlike the other devices).

        Returns:
            dict[str, Any]: The Wireless Access Point CmdbType config
        """
        wap_sections: list[dict[str, Any]] = [
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

        wap_type: dict[str, Any] = self.type_constructor.create_type_config(
            wap_sections,
            'wireless_access_point',
            'Wireless Access Point',
            'fas fa-exchange-alt'
        )

        conditional_sections: list[dict[str, Any]] = [
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
