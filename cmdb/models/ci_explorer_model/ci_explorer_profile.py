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
Implementation of CmdbCiExplorerProfile in DataGerry
"""
from logging import Logger, getLogger

from cmdb.models.cmdb_dao import CmdbDAO

from cmdb.class_schema.ci_explorer_model.cmdb_ci_explorer_profile_schema import get_cmdb_ci_explorer_profile_schema

from cmdb.errors.models.cmdb_ci_explorer_profile import (
    CmdbCiExplorerProfileInitError,
    CmdbCiExplorerProfileInitFromDataError,
    CmdbCiExplorerProfileToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                             CmdbCiExplorerProfile - CLASS                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class CmdbCiExplorerProfile(CmdbDAO):
    """
    Implementation of CmdbCiExplorerProfile

    Extends: CmdbDAO
    """
    COLLECTION = "framework.ciExplorerProfile"

    SCHEMA: dict = get_cmdb_ci_explorer_profile_schema()


    def __init__(
        self,
        public_id: int,
        name: str,
        types_filter: list[int],
        relations_filter: list[int],
        with_locations: bool = True,
        with_ipam_relations: bool = False
    ) -> None:
        """
        Initialises a CmdbCiExplorerProfile

        Args:
            public_id (int): public_id of the CmdbCiExplorerProfile
            name (str): The name of the CmdbCiExplorerProfile
            types_filter (list[int]): List of CmdbType public_ids which should be filtered
            relations_filter (list[int]): List of CmdbRelation public_ids which should be filtered
            with_locations (bool): If True the saved filter includes the dg_location hierarchy.
                                   Defaults to True
            with_ipam_relations (bool): If True the saved filter includes IPAM-hierarchy neighbours.
                                        Defaults to False

        Raises:
            CmdbCiExplorerProfileInitError: When the CmdbCiExplorerProfile could not be initialised
        """
        try:
            self.name = name
            self.types_filter = types_filter or []
            self.relations_filter = relations_filter or []
            self.with_locations = with_locations
            self.with_ipam_relations = with_ipam_relations

            super().__init__(public_id=public_id)
        except Exception as err:
            raise CmdbCiExplorerProfileInitError(err) from err

# -------------------------------------------------- CLASS FUNCTIONS ------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict) -> "CmdbCiExplorerProfile":
        """
        Initialises a CmdbCiExplorerProfile from a dict

        Args:
            data (dict): Data with which the CmdbCiExplorerProfile should be initialised

        Raises:
            CmdbCiExplorerProfileInitFromDataError: If the initialisation with the given data fails

        Returns:
            CmdbCiExplorerProfile: CmdbCiExplorerProfile with the given data
        """
        try:
            return cls(
                public_id = data.get('public_id'),
                name = data.get('name'),
                types_filter = data.get('types_filter', []),
                relations_filter = data.get('relations_filter', []),
                with_locations = data.get('with_locations', True),
                with_ipam_relations = data.get('with_ipam_relations', False),
            )
        except Exception as err:
            raise CmdbCiExplorerProfileInitFromDataError(err) from err


    @classmethod
    def to_json(cls, instance: "CmdbCiExplorerProfile") -> dict:
        """
        Converts a CmdbCiExplorerProfile into a json compatible dict

        Args:
            instance (CmdbCiExplorerProfile): The CmdbCiExplorerProfile which should be converted

        Raises:
            CmdbCiExplorerProfileToJsonError: If CmdbCiExplorerProfile could not be converted to a json compatible dict

        Returns:
            dict: Json compatible dict of the CmdbCiExplorerProfile values
        """
        try:
            return {
                'public_id': instance.get_public_id(),
                'name': instance.name,
                'types_filter': instance.types_filter,
                'relations_filter': instance.relations_filter,
                'with_locations': instance.with_locations,
                'with_ipam_relations': instance.with_ipam_relations,
            }
        except Exception as err:
            raise CmdbCiExplorerProfileToJsonError(err) from err
