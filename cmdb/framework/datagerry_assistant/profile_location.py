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

from cmdb.manager.types_manager import TypesManager
from cmdb.manager.section_templates_manager import SectionTemplatesManager

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
    def __init__(
            self,
            created_type_ids: dict,
            types_manager: TypesManager,
            section_templates_manager: SectionTemplatesManager):
        self.created_type_ids = created_type_ids
        super().__init__(created_type_ids, types_manager, section_templates_manager)


    def create_location_profile(self) -> dict:
        """
        Creates all types from the 'Location'- Profile

        Returns:
            dict: The created type ids dict
        """
        # Do NOT change the order of data due dependency
        location_profile_data: dict = {
            'country_id' : self.get_country_type(),
            'city_id': self.get_city_type(),
            'building_id': self.get_building_type(),
            'room_id': self.get_room_type(),
            'rack_id': self.get_rack_type()
        }

        for type_name, type_dict in location_profile_data.items():
            self.create_basic_type(type_name, type_dict)

        return self.created_type_ids

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  TYPE DATA - SECTION                                                 #
# -------------------------------------------------------------------------------------------------------------------- #

    def get_country_type(self) -> dict:
        """
        Returns the 'Country'-Type for the 'Location'-Profile
        """
        country_sections: list = [
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

        country_type: dict = self.type_constructor.create_type_config(country_sections,
                                                                      'country',
                                                                      'Country',
                                                                      'far fa-flag')

        return country_type

# -------------------------------------------------------------------------------------------------------------------- #

    def get_city_type(self) -> dict:
        """
        Returns the 'City'-Type for the 'Location'-Profile
        """
        city_sections: list = [
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


        city_type: dict = self.type_constructor.create_type_config(city_sections,
                                                                      'city',
                                                                      'City',
                                                                      'fas fa-city')

        return city_type

# -------------------------------------------------------------------------------------------------------------------- #

    def get_building_type(self) -> dict:
        """
        Returns the 'Building'-Type for the 'Location'-Profile
        """
        building_sections: list = [
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


        building_type: dict = self.type_constructor.create_type_config(building_sections,
                                                                            'building',
                                                                            'Building',
                                                                            'fas fa-hotel')

        return building_type

# -------------------------------------------------------------------------------------------------------------------- #

    def get_room_type(self) -> dict:
        """
        Returns the 'Room'-Type for the 'Location'-Profile
        """
        room_sections: list = [
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

        room_type: dict = self.type_constructor.create_type_config(room_sections,
                                                                    'room',
                                                                    'Room',
                                                                    'fa fa-cube')

        return room_type

# -------------------------------------------------------------------------------------------------------------------- #

    def get_rack_type(self) -> dict:
        """
        Returns the 'Rack'-Type for the 'Location'-Profile
        """
        rack_sections: list = [
            {
                "name": "section-39958",
                "label": "Information",
                "fields": [
                    {
                        "type": "text",
                        "name": "text-65752",
                        "label": "Name",
                        "is_summary": True
                    },
                ]
            },
            self.type_constructor.get_predefined_template_data('dg-rackmounting'),
            {
                "name": "section-55832",
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

        rack_type: dict = self.type_constructor.create_type_config(rack_sections,
                                                                      'rack',
                                                                      'Rack',
                                                                      'fas fa-th-large')

        return rack_type
