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

Also holds ``resolve_pulled_field_names``, the one implementation of what a ref-section actually shows.
Two layers need that rule - the renderer, which builds the block, and the CmdbType update guard, which
refuses an edit that would leave the block empty - and the rule has a non-obvious case (an EMPTY
selection means "every field of the section", not "no fields"), so it lives here rather than being
spelled out twice
"""
from logging import Logger, getLogger
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

def resolve_pulled_field_names(
        selected_fields: list[str] | None,
        section_field_names: list[str]) -> list[str]:
    """
    Returns the field names a ref-section shows, given its selection and the target section

    An empty (or absent) selection means the section is not limited, so every field of the referenced
    section is shown - which is why this is not simply an intersection. A selection is applied in the
    REFERENCED section's order, not the selection's, and a selected name the section no longer carries
    is dropped: that is exactly how a stale entry stops being displayed

    Args:
        selected_fields (list[str] | None): The ref-section's configured selection, empty for "all"
        section_field_names (list[str]): Field names of the referenced section, in its own order

    Returns:
        list[str]: The field names that are pulled in, empty when nothing resolves
    """
    if selected_fields:
        return [name for name in section_field_names if name in selected_fields]

    return list(section_field_names)

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


    def resolve_pulled_field_names(self, section_field_names: list[str]) -> list[str]:
        """
        Returns the field names this reference pulls from the given referenced section

        Args:
            section_field_names (list[str]): Field names of the referenced section, in its own order

        Returns:
            list[str]: The field names that are pulled in, empty when nothing resolves
        """
        return resolve_pulled_field_names(self.selected_fields, section_field_names)


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
