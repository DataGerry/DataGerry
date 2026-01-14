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
This module contains the ProfileAssistant class
"""
from logging import Logger, getLogger
from typing import Any
from datetime import datetime, timezone

from cmdb.manager import CategoriesManager
from cmdb.manager.types_manager import TypesManager
from cmdb.manager.section_templates_manager import SectionTemplatesManager

from cmdb.errors.dg_assistant.dg_assistant_errors import ProfileCreationError

from .profile_name import ProfileName
from .profile_user_management import UserManagementProfile
from .profile_location import LocationProfile
from .profile_ipam import IPAMProfile
from .profile_client_management import ClientManagementProfile
from .profile_server_management import ServerManagementProfile
from .profile_network_infrastructure import NetworkInfrastructureProfile
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                               ProfileAssistant - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class ProfileAssistant:
    """
    This class creates all CmdbTypes and CmdbCategories selected in the DataGerry assistant
    """
    def __init__(
        self,
        categories_manager: CategoriesManager,
        types_manager: TypesManager,
        section_templates_manager: SectionTemplatesManager
    ) -> None:
        self.categories_manager: CategoriesManager = categories_manager
        self.types_manager:TypesManager = types_manager
        self.section_templates_manager: SectionTemplatesManager = section_templates_manager

    def create_profiles(self, profile_list):
        """
        Creates types from profiles in the profile_list

        Args:
            profile_list: List of profiles which should be created
        """
        # This is passed along the creation process
        created_type_ids: dict[str, int | None] = {
            "company_id": None,
            "user_id": None,
            "customer_user_id": None,
            "country_id": None,
            "city_id": None,
            "building_id": None,
            "room_id": None,
            "rack_id": None,
            "network_id": None,
            "vlan_id": None,
            "operating_system_id": None,
            "client_id": None,
            "monitor_id": None,
            "printer_id": None,
            "server_id": None,
            "appliance_id": None,
            "virtual_server_id": None,
            "switch_id": None,
            "router_id": None,
            "patch_panel_id": None,
            "wireless_access_point_id": None,
        }

        try:
            # create all types from user management profile
            if ProfileName.USER_MANAGEMENT in profile_list:
                cur_profile = UserManagementProfile(created_type_ids,
                                                    self.types_manager,
                                                    self.section_templates_manager)
                created_type_ids = cur_profile.create_user_management_profile()

            # create all types from location profile
            if ProfileName.LOCATION in profile_list:
                cur_profile = LocationProfile(created_type_ids,
                                              self.types_manager,
                                              self.section_templates_manager)
                created_type_ids = cur_profile.create_location_profile()

            # create all types from ipam profile
            if ProfileName.IPAM in profile_list:
                cur_profile = IPAMProfile(created_type_ids,
                                          self.types_manager,
                                          self.section_templates_manager)
                created_type_ids = cur_profile.create_ipam_profile()

            # create all types from client management profile
            if ProfileName.CLIENT_MANAGEMENT in profile_list:
                cur_profile = ClientManagementProfile(created_type_ids,
                                                      self.types_manager,
                                                      self.section_templates_manager)
                created_type_ids = cur_profile.create_client_management_profile()

            # create all types from server management profile
            if ProfileName.SERVER_MANAGEMENT in profile_list:
                cur_profile = ServerManagementProfile(created_type_ids,
                                                      self.types_manager,
                                                      self.section_templates_manager)
                created_type_ids = cur_profile.create_server_management_profile()

            # create all types from network infrastructure profile
            if ProfileName.NETWORK_INFRASTRUCTURE in profile_list:
                cur_profile = NetworkInfrastructureProfile(created_type_ids,
                                                           self.types_manager,
                                                           self.section_templates_manager)
                created_type_ids = cur_profile.create_network_infrastructure_profile()


            self.create_all_categories(created_type_ids)

        except Exception as err:
            LOGGER.debug("[create_profiles] Error: %s",err)
            raise ProfileCreationError(str(err)) from err

        created_ids = []

        for type_id in created_type_ids:
            if type_id:
                created_ids.append(type_id)

        return created_ids

# ------------------------------------------------- CATEGORY CREATION ------------------------------------------------ #

    def create_all_categories(self, all_type_ids: dict):
        """
        Creates all categories for the assistant

        Args:
            all_type_ids (dict): All created type_ids from the assistant
        """
        all_categories: list[dict] = self.get_all_categories(all_type_ids)

        for _, category in enumerate(all_categories):
            self.categories_manager.insert_category(category)


    def get_all_categories(self, all_type_ids: dict) -> list[dict]:
        """Gets all category models if at least one type_id is set"""
        all_categories: list = []

        # Contact category
        requested_ids: list = ["company_id","customer_user_id","user_id"]
        found_type_ids: list = self.get_category_type_ids(all_type_ids, requested_ids)

        if len(found_type_ids) > 0:
            all_categories.append(self.get_category_body("contact",
                                                         "Contact",
                                                         "fas fa-male",
                                                         found_type_ids))

        # Hardware category
        requested_ids = ["client_id","monitor_id","printer_id","appliance_id","rack_id","server_id"]
        found_type_ids = self.get_category_type_ids(all_type_ids, requested_ids)

        if len(found_type_ids) > 0:
            all_categories.append(self.get_category_body("hardware",
                                                         "Hardware",
                                                         "fas fa-hdd",
                                                         found_type_ids))

        # Location category
        requested_ids = ["country_id","city_id","building_id","room_id"]
        found_type_ids = self.get_category_type_ids(all_type_ids, requested_ids)

        if len(found_type_ids) > 0:
            all_categories.append(self.get_category_body("location",
                                                         "Location",
                                                         "fas fa-hotel",
                                                         found_type_ids))

        # Network category
        requested_ids = ["network_id","patch_panel_id","router_id","switch_id","vlan_id","wireless_access_point_id"]
        found_type_ids = self.get_category_type_ids(all_type_ids, requested_ids)

        if len(found_type_ids) > 0:
            all_categories.append(self.get_category_body("network",
                                                         "Network",
                                                         "fas fa-network-wired",
                                                         found_type_ids))

        # Software category
        requested_ids = ["operating_system_id","virtual_server_id"]
        found_type_ids = self.get_category_type_ids(all_type_ids, requested_ids)

        if len(found_type_ids) > 0:
            all_categories.append(self.get_category_body("software",
                                                         "Software",
                                                         "far fa-id-card",
                                                         found_type_ids))

        return all_categories


    def get_category_type_ids(self, all_type_ids: dict, requested_ids: list) -> list:
        """
        Extracts all required type_ids for a category

        Args:
            all_type_ids (dict): All created type ids 
            requested_ids (list): Required type ids

        Returns:
            list: All required type_ids as a list
        """
        found_type_ids: list = []

        for type_id in requested_ids:
            if all_type_ids[type_id] is not None:
                found_type_ids.append(all_type_ids[type_id])

        return found_type_ids


    def get_category_body(self, cat_name: str, cat_label: str, cat_icon: str, cat_types: list[int]) -> dict[str, Any]:
        """
        Generates a CmdbCategory dict representation which can be used to create a CmdbCategory

        Args:
            cat_name (str): Name for CmdbCategory
            cat_label (str): Label for CmdbCategory
            cat_icon (str): Icon for CmdbCategory
            cat_types (list[int]): public_ids of CmdbTypes assigned to this CmdbCategory

        Returns:
            dict[str, Any]: CmdbCategory dict representation
        """
        return {
            "name": cat_name,
            "label": cat_label,
            "meta": {
                "icon": cat_icon,
                "order": None
            },
            "parent": None,
            "types": cat_types,
            "creation_time": datetime.now(timezone.utc)
        }
