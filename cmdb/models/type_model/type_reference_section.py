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
This class represents a type reference section
Extends: TypeSection
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.models.type_model.type_section import TypeSection
from cmdb.models.type_model.type_reference_section_entry import TypeReferenceSectionEntry
from cmdb.models.type_model.section_key_enum import SectionKey
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 TypeReferenceSection                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TypeReferenceSection(TypeSection):
    """
    This class represents a type reference section
    Extends: TypeSection
    """

    def __init__(
        self,
        type: str,
        name: str,
        label: str | None = None,
        reference: TypeReferenceSectionEntry | None = None,
        fields: list[str] | None = None
    ) -> None:
        """TODO: document"""
        self.reference = reference or {}
        self.fields = fields or []
        super().__init__(type=type, name=name, label=label)

# -------------------------------------------------- CLASS FUNCTIONS ------------------------------------------------- #
    @classmethod
    def from_data(cls, data: dict[str, Any]) -> "TypeReferenceSection":
        """
        Generates a TypeReferenceSection object from a dict

        Args:
            data (dict): Data with which the TypeReferenceSection should be instantiated

        Returns:
            TypeReferenceSection: TypeReferenceSection class with given data
        """
        reference = data.get(SectionKey.REFERENCE.value)
        if reference:
            reference: TypeReferenceSectionEntry = TypeReferenceSectionEntry.from_data(reference)

        return cls(
            type=data.get(SectionKey.TYPE.value),
            name=data.get(SectionKey.NAME.value),
            label=data.get(SectionKey.LABEL.value),
            reference=reference,
            fields=data.get(SectionKey.FIELDS.value)
        )


    @classmethod
    def to_json(cls, instance: "TypeReferenceSection") -> dict[str, Any]:
        """
        Returns a TypeReferenceSection as JSON representation

        Args:
            instance (TypeReferenceSection): TypeReferenceSection which should be transformed

        Returns:
            dict: JSON representation of the given TypeReferenceSection
        """
        return {
            SectionKey.TYPE.value: instance.type,
            SectionKey.NAME.value: instance.name,
            SectionKey.LABEL.value: instance.label,
            SectionKey.REFERENCE.value: TypeReferenceSectionEntry.to_json(instance.reference),
            SectionKey.FIELDS.value: instance.fields,
        }


    def __repr__(self) -> str:
        """TODO: document"""
        return (f"{self.__class__.__name__}(\n"
                f"type={repr(self.type)},\n "
                f"name={repr(self.name)},\n "
                f"label={repr(self.label)},\n "
                f"reference={repr(self.reference)},\n "
                f"fields={repr(self.fields)})\n")
