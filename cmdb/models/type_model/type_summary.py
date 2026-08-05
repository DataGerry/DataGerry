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
Class - Contains the summary fields of the CmdbType 'Type'
"""
from logging import Logger, getLogger
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  TypeSummary - CLASS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TypeSummary:
    """
    Contains the summary fields of CmdbType
    """
    def __init__(self, fields: list[str] | None = None) -> None:
        """TODO: document"""
        self.fields: list[str] = fields or []

# -------------------------------------------------- CLASS FUNCTIONS ------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> "TypeSummary":
        """
        Generates a TypeSummary object from a dict

        Args:
            data (dict): Data with which the TypeSummary should be instantiated

        Returns:
            TypeSummary: TypeSummary class with given data
        """
        return cls(fields = data.get('fields', []))


    @classmethod
    def to_json(cls, instance: "TypeSummary") -> dict[str, Any]:
        """
        Returns a TypeSummary as JSON representation

        Args:
            instance (TypeSummary): TypeSummary which should be transformed

        Returns:
            dict: JSON representation of the given TypeSummary
        """
        return {
            'fields': instance.fields
        }

# ------------------------------------------------- GENERAL FUNCTIONS ------------------------------------------------ #

    def has_fields(self) -> bool:
        """
        Checks if the TypeSummary has any fields

        Returns:
            (bool): True if at least one field is set else False
        """
        return len(self.fields) > 0


    def set_fields(self, fields: list[str]) -> None:
        """
        Sets the 'fields' attribute of the TypeSummary

        Args:
            fields (list[str]): List of field names which are used for the TypeSummary
        """
        self.fields = fields
