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
Constants of the CmdbCiExplorerProfile model
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

__all__ = ['CiExplorerProfileKey', 'DEFAULT_PROFILE_SCOPE']


class CiExplorerProfileKey(BaseStrEnum):
    """
    Enumeration of the keys of a stored CmdbCiExplorerProfile

    **An empty filter list means "no restriction"**, end to end: the frontend leaves an empty list out of
    the graph request and the graph treats a missing filter as disabled. That is why a filter must never
    be emptied BY THE SYSTEM - see `CiExplorerProfileManager.remove_type_from_profiles`

    Attributes:
        PUBLIC_ID: The profile's public_id
        NAME: The name the profile is listed under
        TYPES_FILTER: public_ids of the CmdbTypes the graph's neighbours are restricted to
        RELATIONS_FILTER: public_ids of the CmdbRelations the graph's edges are restricted to
        WITH_LOCATIONS: Whether the graph includes the location hierarchy
        WITH_IPAM_RELATIONS: Whether the graph includes the IPAM hierarchy
        WITH_PORT_CONNECTIONS: Whether the graph includes the CIs the object is cabled to

    The three WITH_* toggles default to **true** - the frontend's own defaults for the graph
    (``DEFAULT_CI_EXPLORER_SCOPE``), so a profile saved without them means what the graph shows by default
    """
    PUBLIC_ID = 'public_id'
    NAME = 'name'
    TYPES_FILTER = 'types_filter'
    RELATIONS_FILTER = 'relations_filter'
    WITH_LOCATIONS = 'with_locations'
    WITH_IPAM_RELATIONS = 'with_ipam_relations'
    WITH_PORT_CONNECTIONS = 'with_port_connections'


# The default of every WITH_* toggle of a profile: the frontend graph's defaults, all three on
DEFAULT_PROFILE_SCOPE: dict[str, bool] = {
    CiExplorerProfileKey.WITH_LOCATIONS.value: True,
    CiExplorerProfileKey.WITH_IPAM_RELATIONS.value: True,
    CiExplorerProfileKey.WITH_PORT_CONNECTIONS.value: True,
}
