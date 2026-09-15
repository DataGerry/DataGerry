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
This module manages the 'Location'-Profile for the DataGerry assistant
"""
from logging import Logger, getLogger
from typing import Any

from .profile_base import ProfileBase
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                LocationProfile - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class LocationProfile(ProfileBase):
    """
    This class cointains all types and logics for the 'Location'-Profile
    """
    def create_profile(self) -> dict[str, int | None]:
        """
        Creates all types of the 'Location' profile (Country, City, Building, Room)

        The hierarchy ends at Room: this profile no longer builds a Rack type. A Rack is the RACK
        SpecialType created by the 'Rack View' profile (see RackProfile) - the basic Rack this profile
        used to create carried none of the Rack View behaviour, and having two different Rack types
        depending on which checkbox was ticked was a trap: a CmdbType's 'special_type' can never be
        changed afterwards, so an install that got the basic one could not be moved onto the real one

        Returns:
            dict[str, int | None]: The shared slot map of created type ids
        """
        # Each type is created (inserted) before the next is built, so a type's reference fields can
        # resolve the public_ids of types created earlier in this profile
        self.create_basic_type('country_id', self.get_country_type())
        self.create_basic_type('city_id', self.get_city_type())
        self.create_basic_type('building_id', self.get_building_type())
        self.create_basic_type('room_id', self.get_room_type())

        return self.created_type_ids

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  TYPE DATA - SECTION                                                 #
# -------------------------------------------------------------------------------------------------------------------- #

    def get_country_type(self) -> dict[str, Any]:
        """
        Builds the 'Country' type for the 'Location' profile

        Returns:
            dict[str, Any]: The Country CmdbType config
        """
        country_sections: list[dict[str, Any]] = [
            {
                "name": "section-15910",
                "label": "Information",
                "fields": [
                    {
                        "type": "text",
                        "name": "text-84872",
                        "label": "Name",
                        "is_summary": True
                    }
                ]
            },
            {
                "name": "section-58608",
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

        country_type: dict[str, Any] = self.type_constructor.create_type_config(
            country_sections,
            'country',
            'Country',
            'far fa-flag'
        )

        return country_type

# -------------------------------------------------------------------------------------------------------------------- #

    def get_city_type(self) -> dict[str, Any]:
        """
        Builds the 'City' type for the 'Location' profile

        Returns:
            dict[str, Any]: The City CmdbType config
        """
        city_sections: list[dict[str, Any]] = [
            {
                "name": "section-57114",
                "label": "Information",
                "fields": [
                    {
                        "type": "text",
                        "name": "text-31555",
                        "label": "Name",
                        "is_summary": True
                    }
                ]
            },
            {
                "name": "section-88673",
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


        city_type: dict[str, Any] = self.type_constructor.create_type_config(
            city_sections,
            'city',
            'City',
            'fas fa-city'
        )

        return city_type

# -------------------------------------------------------------------------------------------------------------------- #

    def get_building_type(self) -> dict[str, Any]:
        """
        Builds the 'Building' type for the 'Location' profile

        Returns:
            dict[str, Any]: The Building CmdbType config
        """
        building_sections: list[dict[str, Any]] = [
            {
                "name": "section-67402",
                "label": "Information",
                "fields": [
                    {
                        "type": "text",
                        "name": "text-56569",
                        "label": "Name",
                        "is_summary": True
                    }
                ]
            },
            {
                "name": "section-17996",
                "label": "Address",
                "fields": [
                    {
                        "type": "text",
                        "name": "text-28009",
                        "label": "Street",
                        "is_summary": True
                    },
                    {
                        "type": "text",
                        "name": "text-36479",
                        "label": "Postal code"
                    },
                    {
                        "type": "text",
                        "name": "text-24247",
                        "label": "House number",
                        "is_summary": True
                    }
                ]
            },
            {
                "name": "section-14059",
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


        building_type: dict[str, Any] = self.type_constructor.create_type_config(
            building_sections,
            'building',
            'Building',
            'fas fa-hotel'
        )

        return building_type

# -------------------------------------------------------------------------------------------------------------------- #

    def get_room_type(self) -> dict[str, Any]:
        """
        Builds the 'Room' type for the 'Location' profile

        Returns:
            dict[str, Any]: The Room CmdbType config
        """
        room_sections: list[dict[str, Any]] = [
            {
                "name": "section-11343",
                "label": "Information",
                "fields": [
                    {
                        "type": "text",
                        "name": "text-72385",
                        "label": "Name",
                        "is_summary": True
                    }
                ]
            },
            {
                "name": "section-48412",
                "label": "Room details",
                "fields": [
                    {
                        "type": "text",
                        "name": "text-30789",
                        "label": "Room number",
                        "is_summary": True
                    },
                    {
                        "type": "text",
                        "name": "text-59951",
                        "label": "Floor",
                        "is_summary": True
                    },
                    {
                        "type": "location",
                        "name": "dg_location",
                        "label": "Location"
                    }
                ]
            }
        ]

        room_type: dict[str, Any] = self.type_constructor.create_type_config(
            room_sections,
            'room',
            'Room',
            'fa fa-cube'
        )

        return room_type
