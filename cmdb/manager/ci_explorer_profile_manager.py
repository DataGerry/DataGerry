# DATAGERRY - OpenSource Enterprise CMDB
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
This module contains the implementation of the CiExplorerProfileManager
"""
from logging import Logger, getLogger

from cmdb.database import MongoDatabaseManager
from cmdb.manager.generic_manager import GenericManager

from cmdb.models.ci_explorer_model import CmdbCiExplorerProfile

from cmdb.errors.manager.ci_explorer_profile_manager import CI_EXPLORER_PROFILE_MANAGER_ERRORS
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                            CiExplorerProfileManager - CLASS                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class CiExplorerProfileManager(GenericManager):
    """
    The CiExplorerProfileManager manages the interaction between CiExplorer profiles and the database

    Extends: GenericManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        """
        Set the database connection for the CiExplorerProfileManager

        Args:
            dbm (MongoDatabaseManager): Database interaction manager
            database (str | None): Name of the database the dbm should connect to. Only used in cloud mode
        """
        super().__init__(dbm, CmdbCiExplorerProfile, CI_EXPLORER_PROFILE_MANAGER_ERRORS, database)

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def remove_type_from_profiles(self, type_id: int) -> None:
        """
        Removes a type_id from the 'types_filter' of all CiExplorerProfiles

        Args:
            type_id(int): public_id of the CmdbType which should be removed from all CiExplorerProfiles
        """
        self.update_many_pull({'types_filter': type_id}, {'types_filter': type_id})


    def remove_relation_from_profiles(self, relation_id: int) -> None:
        """
        Removes a relation_id from the 'relations_filter' of all CiExplorerProfiles

        Args:
            relation_id(int): public_id of the CmdbRelation which should be removed from all CiExplorerProfiles
        """
        self.update_many_pull({'relations_filter': relation_id}, {'relations_filter': relation_id})
