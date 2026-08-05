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
Base class shared by every DataGerry assistant profile

Holds the managers and the ProfileTypeConstructor, the running 'created_type_ids' slot map, and the
helpers each profile uses to create CmdbTypes (and IPAM SpecialTypes) and to look up the public_ids
of types created earlier in the same run.
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.manager import TypesManager, SectionTemplatesManager

from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.framework.ipam.special_type_wiring import handle_special_types
from .datagerry_assistant_constants import TypeSlotKey
from .profile_type_constructor import ProfileTypeConstructor
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  ProfileBase - CLASS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class ProfileBase:
    """
    Base class containing the functions shared by every assistant profile

    Subclasses implement a create_<name>_profile() method that builds their CmdbTypes by calling
    create_basic_type / create_special_type and reading previously created ids via get_created_id.
    """
    def __init__(
            self,
            created_type_ids: dict[str, int | None],
            types_manager: TypesManager,
            section_templates_manager: SectionTemplatesManager,
            type_constructor: ProfileTypeConstructor) -> None:
        """
        Args:
            created_type_ids (dict[str, int | None]): Slot map shared across the whole profile run;
                                                      each TypeSlotKey maps to a created public_id, or
                                                      None until that slot's type is created
            types_manager (TypesManager): db interface for CmdbTypes
            section_templates_manager (SectionTemplatesManager): db interface for section templates
            type_constructor (ProfileTypeConstructor): Shared builder used to assemble CmdbType dicts
                                                       (created once per run and reused by every profile)
        """
        self.types_manager: TypesManager = types_manager
        self.section_templates_manager: SectionTemplatesManager = section_templates_manager
        self.created_type_ids: dict[str, int | None] = created_type_ids
        self.type_constructor: ProfileTypeConstructor = type_constructor

# ------------------------------------------------- HELPER FUNCTIONS ------------------------------------------------- #

    def create_profile(self) -> dict[str, int | None]:
        """
        Builds this profile's CmdbTypes and returns the updated slot map

        Subclasses override this; ProfileAssistant calls it once per selected profile.

        Returns:
            dict[str, int | None]: The shared slot map of created type ids

        Raises:
            NotImplementedError: If a subclass does not override this method
        """
        raise NotImplementedError

    def get_created_id(self, identifier: str) -> int | None:
        """
        Retrieves the public_id of a type from the 'created_type_ids'-dict

        Args:
            identifier (str): Name of key for the type (see TypeSlotKey)

        Returns:
            int | None: public_id of the type, or None if the slot is unknown or not yet created
        """
        return self.created_type_ids.get(identifier)


    def get_ipam_interface_section(self) -> dict[str, Any]:
        """
        Returns the dg-ipam-interface section template wired to this run's Subnet type

        Profiles attach this in place of the legacy dg-network section so the IPAM interface
        feature is usable out-of-the-box. The Subnet reference is wired only when an IPAM Subnet
        type was created earlier in the run; otherwise the reference stays empty.

        Returns:
            dict[str, Any]: The formatted dg-ipam-interface section template
        """
        return self.type_constructor.get_ipam_interface_template_data(self.get_created_id(TypeSlotKey.SUBNET_ID))


    def create_basic_type(self, type_name_key: str, type_dict: dict[str, Any]) -> int:
        """
        Inserts a new CmdbType into the db and records its public_id under 'type_name_key'

        Args:
            type_name_key (str): Slot key under which the created type's public_id is stored
                                 (a TypeSlotKey value, e.g. 'company_id')
            type_dict (dict[str, Any]): Full CmdbType config to insert; the public_id is assigned here

        Returns:
            int: public_id of the created type
        """
        type_dict['public_id'] = self.types_manager.get_new_type_public_id()
        new_type_id: int = self.types_manager.insert_type(type_dict)

        self.created_type_ids[type_name_key] = new_type_id

        return new_type_id


    def create_special_type(self, type_name_key: str, special_type: SpecialType, type_dict: dict[str, Any]) -> int:
        """
        Creates an IPAM SpecialType in the db and cross-wires its reference fields

        Inserts the type like create_basic_type, then calls handle_special_types so the SpecialType
        reference fields (Subnet -> Supernet, VLAN -> Subnet) and the dg-ipam-interface section
        template are wired to the newly created type. Must be called in dependency order
        (Supernet, then Subnet, then VLAN) so each wiring target already exists.

        Args:
            type_name_key (str): Slot key under which the created type's public_id is stored
            special_type (SpecialType): The SpecialType marker of the created type
            type_dict (dict[str, Any]): Full CmdbType config to insert

        Returns:
            int: public_id of the created type
        """
        new_type_id: int = self.create_basic_type(type_name_key, type_dict)

        handle_special_types(self.types_manager, special_type, self.section_templates_manager, new_type_id)

        return new_type_id


    def get_created_type_ids(self) -> dict[str, int | None]:
        """
        Returns the slot map of all created type ids, reused by later profile creations

        Returns:
            dict[str, int | None]: Each TypeSlotKey mapped to its created public_id, or None when
                                   the slot's type was not created
        """
        return self.created_type_ids
