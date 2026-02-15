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
This module contains the classes of all CollectionValidator errors
"""
# -------------------------------------------------------------------------------------------------------------------- #

class CollectionValidatorError(Exception):
    """
    Raised to catch all CollectionValidator related errors
    """
    def __init__(self, err: str) -> None:
        """
        Raised to catch all CollectionValidator related errors
        """
        super().__init__(err)

# ------------------------------------------- CollectionValidator - ERRORS ------------------------------------------- #

class CollectionValidatorInitError(CollectionValidatorError):
    """
    Raised when the CollectionValidator could not be initialised
    """


class CollectionInitError(CollectionValidatorError):
    """
    Raised when the initialisation of a Collection failed
    """


class CollectionValidationError(CollectionValidatorError):
    """
    Raised when the valdation of Collections failed
    """
