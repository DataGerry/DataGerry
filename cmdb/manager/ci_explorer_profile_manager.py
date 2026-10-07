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
from typing import Any

from cmdb.database import MongoDatabaseManager
from cmdb.manager.generic_manager import GenericManager

from cmdb.models.ci_explorer_model import CiExplorerProfileKey, CmdbCiExplorerProfile

from cmdb.errors.manager.ci_explorer_profile_manager import (
    CI_EXPLORER_PROFILE_MANAGER_ERRORS,
    CiExplorerProfileManagerUpdateError,
)
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

    @staticmethod
    def build_emptied_filter_criteria(filter_field: str, id_value: int) -> dict[str, Any]:
        """
        Builds the criteria of the profiles a pull of `id_value` would leave with an EMPTY filter

        Those are the profiles whose filter holds the id and nothing else - once, or repeated. Matched
        BEFORE the pull: afterwards they would be indistinguishable from a profile saved with an empty
        filter on purpose, which means "no restriction" and has to be left alone

        Args:
            filter_field (str): The filter-array field (a `CiExplorerProfileKey` filter member)
            id_value (int): The public_id about to be pulled

        Returns:
            dict[str, Any]: The query selecting exactly those profiles
        """
        return {'$and': [
            {filter_field: id_value},
            {filter_field: {'$not': {'$elemMatch': {'$ne': id_value}}}},
        ]}


    def _remove_id_from_filter(self, filter_field: str, id_value: int) -> list[int]:
        """
        Removes an id from the given filter-array field across all CiExplorerProfiles

        **A profile the removal would leave with an empty filter is deleted instead.** An empty filter
        means "no restriction" - the frontend leaves it out of the graph request and the graph treats
        it as disabled - so pulling a narrow profile's last id would silently widen it to everything,
        the opposite of what it was saved for. Such a profile has lost its meaning, and a
        profile that is gone is at least visible, where a widened one is not. Every other profile has
        the id pulled and stays as narrow as its remaining ids.

        The deletion runs first: pulled first, the emptied profiles would be indistinguishable from
        one saved empty on purpose. Re-run safe - a second call finds nothing left to delete or pull

        Args:
            filter_field (str): The filter-array field (a `CiExplorerProfileKey` filter member)
            id_value (int): The public_id to remove from that field on every profile

        Raises:
            CiExplorerProfileManagerUpdateError: When the lookup, the deletion or the pull fails

        Returns:
            list[int]: The public_ids of the profiles deleted because their filter would have emptied
        """
        try:
            emptied: list[dict[str, Any]] = self.find(
                criteria=self.build_emptied_filter_criteria(filter_field, id_value),
                projection={CiExplorerProfileKey.PUBLIC_ID.value: 1, CiExplorerProfileKey.NAME.value: 1},
            )
            emptied_ids: list[int] = [profile[CiExplorerProfileKey.PUBLIC_ID.value] for profile in emptied]

            if emptied_ids:
                self.delete_many({CiExplorerProfileKey.PUBLIC_ID.value: {'$in': emptied_ids}})
                LOGGER.warning(
                    "[_remove_id_from_filter] Deleted CiExplorer Profile(s) %s: removing %s %s would have "
                    "emptied their filter, which widens a profile to everything",
                    [(profile.get(CiExplorerProfileKey.NAME.value), profile[CiExplorerProfileKey.PUBLIC_ID.value])
                     for profile in emptied],
                    filter_field, id_value,
                )

            self.update_many_pull({filter_field: id_value}, {filter_field: id_value})

            return emptied_ids
        except Exception as err:
            LOGGER.error("[_remove_id_from_filter] Exception: %s. Type: %s", err, type(err))
            raise CiExplorerProfileManagerUpdateError(err) from err


    def remove_type_from_profiles(self, type_id: int) -> list[int]:
        """
        Removes a type_id from the 'types_filter' of all CiExplorerProfiles

        A profile whose type filter held this type alone is deleted instead - see `_remove_id_from_filter`

        Args:
            type_id(int): public_id of the CmdbType which should be removed from all CiExplorerProfiles

        Raises:
            CiExplorerProfileManagerUpdateError: When the cleanup fails

        Returns:
            list[int]: The public_ids of the profiles deleted because their type filter would have emptied
        """
        return self._remove_id_from_filter(CiExplorerProfileKey.TYPES_FILTER.value, type_id)


    def remove_relation_from_profiles(self, relation_id: int) -> list[int]:
        """
        Removes a relation_id from the 'relations_filter' of all CiExplorerProfiles

        A profile whose relation filter held this relation alone is deleted instead - see
        `_remove_id_from_filter`

        Args:
            relation_id(int): public_id of the CmdbRelation which should be removed from all CiExplorerProfiles

        Raises:
            CiExplorerProfileManagerUpdateError: When the cleanup fails

        Returns:
            list[int]: The public_ids of the profiles deleted because their relation filter would have emptied
        """
        return self._remove_id_from_filter(CiExplorerProfileKey.RELATIONS_FILTER.value, relation_id)
