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
Orchestrator for the DataGerry assistant

ProfileAssistant turns the list of selected profile names into CmdbTypes and CmdbCategories: it runs
each requested profile in a fixed, dependency-aware order against a shared 'created_type_ids' slot
map, then derives the categories from whichever slots were filled.
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
from .profile_rack import RackProfile
from .profile_location import LocationProfile
from .profile_ipam import IPAMProfile
from .profile_client_management import ClientManagementProfile
from .profile_server_management import ServerManagementProfile
from .profile_network_infrastructure import NetworkInfrastructureProfile
from .profile_base import ProfileBase
from .predefined_template_provider import PredefinedTemplateProvider
from .profile_type_constructor import ProfileTypeConstructor
from .datagerry_assistant_constants import (
    TypeSlotKey,
    CategoryBodyKey,
    CategoryMetaKey,
    CategoryDefinitionKey,
    CATEGORY_DEFINITIONS,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# Profiles are built in this fixed order regardless of selection order: later profiles reference
# types created by earlier ones (e.g. conditional reference sections / dependent types)
PROFILE_BUILDERS: list[tuple[ProfileName, type[ProfileBase]]] = [
    (ProfileName.USER_MANAGEMENT, UserManagementProfile),
    # Runs before the location profile: both fill the RACK_ID slot, and the Rack View's SpecialType
    # takes precedence over the basic Rack type the location profile would otherwise create
    (ProfileName.RACK, RackProfile),
    (ProfileName.LOCATION, LocationProfile),
    (ProfileName.IPAM, IPAMProfile),
    (ProfileName.CLIENT_MANAGEMENT, ClientManagementProfile),
    (ProfileName.SERVER_MANAGEMENT, ServerManagementProfile),
    (ProfileName.NETWORK_INFRASTRUCTURE, NetworkInfrastructureProfile),
]

# -------------------------------------------------------------------------------------------------------------------- #
#                                               ProfileAssistant - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class ProfileAssistant:
    """
    Creates all CmdbTypes and CmdbCategories selected in the DataGerry assistant
    """
    def __init__(
        self,
        categories_manager: CategoriesManager,
        types_manager: TypesManager,
        section_templates_manager: SectionTemplatesManager
    ) -> None:
        """
        Args:
            categories_manager (CategoriesManager): db interface for CmdbCategories
            types_manager (TypesManager): db interface for CmdbTypes
            section_templates_manager (SectionTemplatesManager): db interface for section templates
        """
        self.categories_manager: CategoriesManager = categories_manager
        self.types_manager: TypesManager = types_manager
        self.section_templates_manager: SectionTemplatesManager = section_templates_manager

    def create_profiles(self, profile_list: list[str]) -> list[int]:
        """
        Creates the CmdbTypes (and their categories) for every requested profile

        Profiles run in a fixed order regardless of the order in 'profile_list', because later
        profiles reference types created by earlier ones (e.g. conditional reference sections). All
        creation is wrapped so any failure is re-raised as ProfileCreationError.

        Args:
            profile_list (list[str]): ProfileName values selected in the assistant

        Returns:
            list[int]: public_ids of every CmdbType created during the run

        Raises:
            ProfileCreationError: If any type or category creation fails
        """
        # Passed along the whole creation process; every slot starts as None and is filled with the
        # created type's public_id as profiles run (see TypeSlotKey)
        created_type_ids: dict[str, int | None] = {slot: None for slot in TypeSlotKey}

        try:
            # The predefined templates and the type builder are created once and reused by every
            # profile, so the predefined section templates are loaded from the DB only once per run
            template_provider: PredefinedTemplateProvider = PredefinedTemplateProvider(self.section_templates_manager)
            type_constructor: ProfileTypeConstructor = ProfileTypeConstructor(template_provider)

            profile_name: ProfileName
            profile_cls: type[ProfileBase]
            for profile_name, profile_cls in PROFILE_BUILDERS:
                if profile_name in profile_list:
                    profile: ProfileBase = profile_cls(
                        created_type_ids,
                        self.types_manager,
                        self.section_templates_manager,
                        type_constructor,
                    )
                    created_type_ids = profile.create_profile()

            self.create_all_categories(created_type_ids)

        except Exception as err:
            LOGGER.debug("[create_profiles] Error: %s", err)
            raise ProfileCreationError(str(err)) from err

        created_ids: list[int] = [type_id for type_id in created_type_ids.values() if type_id]

        return created_ids

# ------------------------------------------------- CATEGORY CREATION ------------------------------------------------ #

    def create_all_categories(self, all_type_ids: dict[str, int | None]) -> None:
        """
        Builds and inserts every CmdbCategory that has at least one created member type

        Args:
            all_type_ids (dict[str, int | None]): The slot map of created type ids from the run
        """
        all_categories: list[dict[str, Any]] = self.get_all_categories(all_type_ids)

        category: dict[str, Any]
        for category in all_categories:
            self.categories_manager.insert_category(category)


    def get_all_categories(self, all_type_ids: dict[str, int | None]) -> list[dict[str, Any]]:
        """
        Builds a CmdbCategory dict for every entry in CATEGORY_DEFINITIONS that has at least one
        of its member types created

        Args:
            all_type_ids (dict[str, int | None]): The slot map of created type ids from the run

        Returns:
            list[dict[str, Any]]: CmdbCategory dict representations to be inserted
        """
        all_categories: list[dict[str, Any]] = []

        definition: dict[str, Any]
        for definition in CATEGORY_DEFINITIONS:
            found_type_ids: list[int] = self.get_category_type_ids(
                all_type_ids,
                definition[CategoryDefinitionKey.TYPE_SLOTS],
            )

            if len(found_type_ids) > 0:
                all_categories.append(self.get_category_body(definition[CategoryDefinitionKey.NAME],
                                                             definition[CategoryDefinitionKey.LABEL],
                                                             definition[CategoryDefinitionKey.ICON],
                                                             found_type_ids))

        return all_categories


    def get_category_type_ids(self,
                              all_type_ids: dict[str, int | None],
                              requested_ids: list[TypeSlotKey]) -> list[int]:
        """
        Extracts the created public_ids for a category's requested type slots

        Args:
            all_type_ids (dict[str, int | None]): The slot map of created type ids from the run
            requested_ids (list[TypeSlotKey]): Type slots whose created ids belong to the category

        Returns:
            list[int]: public_ids of the requested slots that were created (uncreated slots skipped)
        """
        found_type_ids: list[int] = []

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
            CategoryBodyKey.NAME: cat_name,
            CategoryBodyKey.LABEL: cat_label,
            CategoryBodyKey.META: {
                CategoryMetaKey.ICON: cat_icon,
                CategoryMetaKey.ORDER: None
            },
            CategoryBodyKey.PARENT: None,
            CategoryBodyKey.TYPES: cat_types,
            CategoryBodyKey.CREATION_TIME: datetime.now(timezone.utc)
        }
