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
This module contains the classes of all FieldRulesManager errors
"""
# -------------------------------------------------------------------------------------------------------------------- #

class FieldRulesManagerError(Exception):
    """
    Raised to catch all FieldRulesManager related errors
    """
    def __init__(self, err: str | Exception) -> None:
        """
        Raised to catch all FieldRulesManager related errors

        Takes the wrapped exception itself as readily as a message: str() reads the same either way,
        but args[0] then carries the error being wrapped, which a caller can branch on

        Args:
            err (str | Exception): The message, or the error being wrapped
        """
        super().__init__(err)

# ------------------------------------------- FieldRulesManager - ERRORS ------------------------------------------- #

class FieldRulesManagerInsertError(FieldRulesManagerError):
    """
    Raised when FieldRulesManager could not insert a CmdbFieldRule
    """


class FieldRulesManagerGetError(FieldRulesManagerError):
    """
    Raised when FieldRulesManager could not retrieve a CmdbFieldRule
    """


class FieldRulesManagerUpdateError(FieldRulesManagerError):
    """
    Raised when FieldRulesManager could not update a CmdbFieldRule
    """


class FieldRulesManagerDeleteError(FieldRulesManagerError):
    """
    Raised when FieldRulesManager could not delete a CmdbFieldRule
    """


class FieldRulesManagerIterationError(FieldRulesManagerError):
    """
    Raised when FieldRulesManager could not iterate over CmdbFieldRules
    """
