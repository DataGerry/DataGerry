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
This module is the base class for the profiles of DataGerry assistant
"""
from logging import Logger, getLogger
from flask import current_app

from cmdb.manager import TypesManager, SectionTemplatesManager

from cmdb.models.type_model import CmdbType
from .profile_type_constructor import ProfileTypeConstructor
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  ProfileBase - CLASS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class ProfileBase:
    """
    This class cointains all functions required by the different profiles
    """
    def __init__(
            self,
            created_type_ids: dict,
            types_manager: TypesManager,
            section_templates_manager: SectionTemplatesManager):
        self.types_manager = types_manager
        self.section_templates_manager = section_templates_manager
        self.type_dict: dict = {}
        self.created_type_ids: dict = created_type_ids

        self.type_collection = CmdbType.COLLECTION

        with current_app.app_context():
            self.type_constructor = ProfileTypeConstructor(self.section_templates_manager)

# ------------------------------------------------- HELPER FUNCTIONS ------------------------------------------------- #

    def get_created_id(self, identifier: str) -> int:
        """
        Retrieves the public_id of a type from the 'created_type_ids'-dict
        Args:
            identifier (str): Name of key for the type

        Returns:
            int: public_id of the type. Default is None
        """
        return self.created_type_ids[identifier]


    def create_basic_type(self, type_name_key: str, type_dict: dict):
        """
        Creates a new type in the db
        Args:
            type_name_id (str): Key which should be used for the id of this type, like 'user_type_id'
            type_dict (dict): all the required data to create the type except the public_id
        """
        type_dict['public_id'] = self.types_manager.get_new_type_public_id()
        new_type_id: int = self.types_manager.insert_type(type_dict)

        self.created_type_ids[type_name_key] = new_type_id


    def get_created_type_ids(self) -> dict:
        """
        Returns all created type ids which can be used for other profile creations

        Returns:
            dict: All created type ids
        """
        return self.created_type_ids
