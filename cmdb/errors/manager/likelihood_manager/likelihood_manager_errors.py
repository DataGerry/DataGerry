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
This module contains the classes of all LikelihoodManager errors
"""
# -------------------------------------------------------------------------------------------------------------------- #

class LikelihoodManagerError(Exception):
    """
    Raised to catch all LikelihoodManager related errors
    """
    def __init__(self, err: str) -> None:
        """
        Raised to catch all LikelihoodManager related errors
        """
        super().__init__(err)

# -------------------------------------------- LikelihoodManager - ERRORS -------------------------------------------- #

class LikelihoodManagerInitError(LikelihoodManagerError):
    """
    Raised when LikelihoodManager could not be initialised
    """


class LikelihoodManagerInsertError(LikelihoodManagerError):
    """
    Raised when LikelihoodManager could not insert an IsmsLikelihood
    """


class LikelihoodManagerGetError(LikelihoodManagerError):
    """
    Raised when LikelihoodManager could not retrieve an IsmsLikelihood
    """


class LikelihoodManagerUpdateError(LikelihoodManagerError):
    """
    Raised when LikelihoodManager could not update an IsmsLikelihood
    """


class LikelihoodManagerDeleteError(LikelihoodManagerError):
    """
    Raised when LikelihoodManager could not delete an IsmsLikelihood
    """


class LikelihoodManagerIterationError(LikelihoodManagerError):
    """
    Raised when LikelihoodManager could not iterate over IsmsLikelihoods
    """
