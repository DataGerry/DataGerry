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

A profile is a named, shared CI Explorer filter: the two id filters and the three edge-source toggles
(``with_locations``, ``with_ipam_relations``, ``with_port_connections``). A toggle the stored document
lacks reads as its default - TRUE, the frontend graph's own default (``DEFAULT_PROFILE_SCOPE``)
"""
from typing import Any
from logging import Logger, getLogger

from cmdb.models.cmdb_dao import CmdbDAO

from cmdb.class_schema.ci_explorer_model.cmdb_ci_explorer_profile_schema import get_cmdb_ci_explorer_profile_schema
from cmdb.models.ci_explorer_model.ci_explorer_profile_constants import CiExplorerProfileKey, DEFAULT_PROFILE_SCOPE

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

    SCHEMA: dict[str, Any] = get_cmdb_ci_explorer_profile_schema()


    def __init__(
        self,
        *,
        public_id: int,
        name: str,
        types_filter: list[int],
        relations_filter: list[int],
        with_locations: bool = DEFAULT_PROFILE_SCOPE[CiExplorerProfileKey.WITH_LOCATIONS],
        with_ipam_relations: bool = DEFAULT_PROFILE_SCOPE[CiExplorerProfileKey.WITH_IPAM_RELATIONS],
        with_port_connections: bool = DEFAULT_PROFILE_SCOPE[CiExplorerProfileKey.WITH_PORT_CONNECTIONS],
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
                                        Defaults to True
            with_port_connections (bool): If True the saved filter includes the CIs the object is cabled
                                          to. Defaults to True

        Raises:
            CmdbCiExplorerProfileInitError: When the CmdbCiExplorerProfile could not be initialised
        """
        try:
            self.name = name
            self.types_filter = types_filter or []
            self.relations_filter = relations_filter or []
            self.with_locations = with_locations
            self.with_ipam_relations = with_ipam_relations
            self.with_port_connections = with_port_connections

            super().__init__(public_id=public_id)
        except Exception as err:
            raise CmdbCiExplorerProfileInitError(err) from err

# -------------------------------------------------- CLASS FUNCTIONS ------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> "CmdbCiExplorerProfile":
        """
        Initialises a CmdbCiExplorerProfile from a dict

        Args:
            data (dict[str, Any]): Data with which the CmdbCiExplorerProfile should be initialised

        Raises:
            CmdbCiExplorerProfileInitFromDataError: If the initialisation with the given data fails

        Returns:
            CmdbCiExplorerProfile: CmdbCiExplorerProfile with the given data
        """
        try:
            return cls(
                public_id=data.get(CiExplorerProfileKey.PUBLIC_ID),
                name=data.get(CiExplorerProfileKey.NAME),
                types_filter=data.get(CiExplorerProfileKey.TYPES_FILTER, []),
                relations_filter=data.get(CiExplorerProfileKey.RELATIONS_FILTER, []),
                **{key: data.get(key, default) for key, default in DEFAULT_PROFILE_SCOPE.items()},
            )
        except Exception as err:
            raise CmdbCiExplorerProfileInitFromDataError(err) from err


    @classmethod
    def to_json(cls, instance: "CmdbCiExplorerProfile") -> dict[str, Any]:
        """
        Converts a CmdbCiExplorerProfile into a json compatible dict

        Args:
            instance (CmdbCiExplorerProfile): The CmdbCiExplorerProfile which should be converted

        Raises:
            CmdbCiExplorerProfileToJsonError: If CmdbCiExplorerProfile could not be converted to a json compatible dict

        Returns:
            dict[str, Any]: Json compatible dict of the CmdbCiExplorerProfile values
        """
        try:
            return {
                CiExplorerProfileKey.PUBLIC_ID.value: instance.get_public_id(),
                CiExplorerProfileKey.NAME.value: instance.name,
                CiExplorerProfileKey.TYPES_FILTER.value: instance.types_filter,
                CiExplorerProfileKey.RELATIONS_FILTER.value: instance.relations_filter,
                CiExplorerProfileKey.WITH_LOCATIONS.value: instance.with_locations,
                CiExplorerProfileKey.WITH_IPAM_RELATIONS.value: instance.with_ipam_relations,
                CiExplorerProfileKey.WITH_PORT_CONNECTIONS.value: instance.with_port_connections,
            }
        except Exception as err:
            raise CmdbCiExplorerProfileToJsonError(err) from err
