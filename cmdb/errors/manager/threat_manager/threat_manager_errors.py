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
This module contains the classes of all ThreatManager errors
"""
# -------------------------------------------------------------------------------------------------------------------- #

class ThreatManagerError(Exception):
    """
    Raised to catch all ThreatManager related errors
    """
    def __init__(self, err: str) -> None:
        """
        Raised to catch all ThreatManager related errors
        """
        super().__init__(err)

# ---------------------------------------------- ThreatManager - ERRORS ---------------------------------------------- #

class ThreatManagerInitError(ThreatManagerError):
    """
    Raised when ThreatManager could not be initialised
    """


class ThreatManagerInsertError(ThreatManagerError):
    """
    Raised when ThreatManager could not insert an IsmsThreat
    """


class ThreatManagerGetError(ThreatManagerError):
    """
    Raised when ThreatManager could not retrieve an IsmsThreat
    """


class ThreatManagerUpdateError(ThreatManagerError):
    """
    Raised when ThreatManager could not update an IsmsThreat
    """


class ThreatManagerDeleteError(ThreatManagerError):
    """
    Raised when ThreatManager could not delete an IsmsThreat
    """


class ThreatManagerIterationError(ThreatManagerError):
    """
    Raised when ThreatManager could not iterate over IsmsThreats
    """


class ThreatManagerRiskUsageError(ThreatManagerError):
    """
    Raised when ThreatManager could not delete an IsmsThreat because an IsmsRisk is using it
    """
