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
This module contains all available profile names for the DataGerry assistant
"""

from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

class ProfileName(BaseStrEnum):
    """
    Enumeration of all valid profile names which can be created through the DataGerry assistant

    The member values are the wire tokens the assistant receives (the '#'-separated 'data' request
    parameter is split into these). ProfileAssistant.create_profiles tests membership of these
    values to decide which profiles to build.
    """
    USER_MANAGEMENT = 'user-management-profile'
    RACK = 'rack-profile'
    LOCATION = 'location-profile'
    IPAM = 'ipam-profile'
    CLIENT_MANAGEMENT = 'client-management-profile'
    SERVER_MANAGEMENT = 'server-management-profile'
    NETWORK_INFRASTRUCTURE = 'network-infrastructure-profile'
