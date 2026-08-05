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
This module contains the classes of all IsmsControlMeasureAssignment errors
"""
# -------------------------------------------------------------------------------------------------------------------- #

class IsmsControlMeasureAssignmentError(Exception):
    """
    Raised to catch all IsmsControlMeasureAssignment related errors
    """
    def __init__(self, err: str) -> None:
        """
        Raised to catch all IsmsControlMeasureAssignment related errors
        """
        super().__init__(err)

# --------------------------------------- IsmsControlMeasureAssignment - ERRORS -------------------------------------- #

class IsmsControlMeasureAssignmentInitError(IsmsControlMeasureAssignmentError):
    """
    Raised when a IsmsControlMeasureAssignment could not be initialised
    """


class IsmsControlMeasureAssignmentInitFromDataError(IsmsControlMeasureAssignmentError):
    """
    Raised when a IsmsControlMeasureAssignment could not be initialised from a dict
    """


class IsmsControlMeasureAssignmentToJsonError(IsmsControlMeasureAssignmentError):
    """
    Raised when a IsmsControlMeasureAssignment could not be transformed into a json compatible dict
    """
