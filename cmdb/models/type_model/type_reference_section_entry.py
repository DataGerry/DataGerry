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
This class represents a type reference section entry
"""
from logging import Logger, getLogger
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                           TypeReferenceSectionEntry - CLASS                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class TypeReferenceSectionEntry:
    """This class represents a type reference section entry"""

    def __init__(
        self,
        type_id: int,
        section_name: str,
        selected_fields: list[str] | None = None
    ) -> None:
        """TODO: document"""
        self.type_id: int = type_id
        self.section_name: str = section_name
        self.selected_fields: list[str] = selected_fields or []

# -------------------------------------------------- CLASS FUNCTIONS ------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> "TypeReferenceSectionEntry":
        """
        Generates a TypeReferenceSectionEntry object from a dict

        Args:
            data (dict): Data with which the TypeReferenceSectionEntry should be instantiated

        Returns:
            TypeReferenceSectionEntry: TypeReferenceSectionEntry class with given data
        """
        return cls(
            type_id = data.get('type_id'),
            section_name = data.get('section_name'),
            selected_fields = data.get('selected_fields')
        )


    @classmethod
    def to_json(cls, instance: "TypeReferenceSectionEntry") -> dict[str, Any]:
        """
        Returns a TypeReferenceSectionEntry as JSON representation

        Args:
            instance (TypeReferenceSectionEntry): TypeReferenceSectionEntry which should be transformed

        Returns:
            dict: JSON representation of the given TypeReferenceSectionEntry
        """
        return {
            'type_id': instance.type_id,
            'section_name': instance.section_name,
            'selected_fields': instance.selected_fields
        }


    def __repr__(self) -> str:
        """TODO: document"""
        return (f"{self.__class__.__name__}(\n"
                f"type_id={self.type_id}\n "
                f"section_name={repr(self.section_name)}\n "
                f"selected_fields={repr(self.selected_fields)})\n")
