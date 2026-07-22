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

from cmdb.errors.manager.ci_explorer_profile_manager import (
    CI_EXPLORER_PROFILE_MANAGER_ERRORS,
    CiExplorerProfileManagerUpdateError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)
<<<<<<< HEAD
=======

# CiExplorerProfile filter-array fields a deleted type / relation id is pulled from
TYPES_FILTER_FIELD: str = 'types_filter'
RELATIONS_FILTER_FIELD: str = 'relations_filter'
>>>>>>> origin/version-3.2

# -------------------------------------------------------------------------------------------------------------------- #
#                                            CiExplorerProfileManager - CLASS                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class CiExplorerProfileManager(GenericManager):
    """
    The CiExplorerProfileManager manages the interaction between CiExplorer profiles and the database

    Extends: GenericManager
    """
<<<<<<< HEAD
    def __init__(self, dbm: MongoDatabaseManager, database: str = None) -> None:
=======
    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        """
        Set the database connection for the CiExplorerProfileManager

        Args:
            dbm (MongoDatabaseManager): Database interaction manager
            database (str | None): Name of the database the dbm should connect to. Only used in cloud mode
        """
>>>>>>> origin/version-3.2
        super().__init__(dbm, CmdbCiExplorerProfile, CI_EXPLORER_PROFILE_MANAGER_ERRORS, database)

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

<<<<<<< HEAD
    def remove_type_from_profiles(self, type_id: int) -> None:
        """
        Removes a type_id from all CiExplorerProfiles

        Args:
            type_id(int): public_id of the CmdbType which should be removed from all CiExplorerProfiles
        """
        criteria: dict[str, int] = {'types_filter': type_id}

        update: dict[str, dict[str, int]] = {
            '$pull': {
                'types_filter': type_id
            }
        }

        self.update_many(criteria=criteria, update=update, plain=True)
=======
    def _remove_id_from_filter(self, filter_field: str, id_value: int) -> None:
        """
        Pulls an id out of the given filter-array field across all CiExplorerProfiles

        Args:
            filter_field (str): The CiExplorerProfile array field to pull from
                (TYPES_FILTER_FIELD or RELATIONS_FILTER_FIELD)
            id_value (int): The public_id to remove from that field on every profile

        Raises:
            CiExplorerProfileManagerUpdateError: When the pull operation fails
        """
        try:
            self.update_many_pull({filter_field: id_value}, {filter_field: id_value})
        except Exception as err:
            LOGGER.error("[_remove_id_from_filter] Exception: %s. Type: %s", err, type(err))
            raise CiExplorerProfileManagerUpdateError(err) from err


    def remove_type_from_profiles(self, type_id: int) -> None:
        """
        Removes a type_id from the 'types_filter' of all CiExplorerProfiles

        Args:
            type_id(int): public_id of the CmdbType which should be removed from all CiExplorerProfiles

        Raises:
            CiExplorerProfileManagerUpdateError: When the pull operation fails
        """
        self._remove_id_from_filter(TYPES_FILTER_FIELD, type_id)
>>>>>>> origin/version-3.2


    def remove_relation_from_profiles(self, relation_id: int) -> None:
        """
<<<<<<< HEAD
        Removes a relation_id from all CiExplorerProfiles

        Args:
            relation_id(int): public_id of the CmdbRelation which should be removed from all CiExplorerProfiles
        """
        criteria: dict[str, int] = {'relations_filter': relation_id}

        update: dict[str, dict[str, int]] = {
            '$pull': {
                'relations_filter': relation_id
            }
        }

        self.update_many(criteria=criteria, update=update, plain=True)
=======
        Removes a relation_id from the 'relations_filter' of all CiExplorerProfiles

        Args:
            relation_id(int): public_id of the CmdbRelation which should be removed from all CiExplorerProfiles

        Raises:
            CiExplorerProfileManagerUpdateError: When the pull operation fails
        """
        self._remove_id_from_filter(RELATIONS_FILTER_FIELD, relation_id)
>>>>>>> origin/version-3.2
