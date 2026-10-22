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
This class represents a type field section
Extends: TypeSection
"""
from logging import Logger, getLogger
from typing import Any
import json

from cmdb.models.type_model.type_section import TypeSection
from cmdb.models.type_model.section_key_enum import SectionKey
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                               TypeFieldSection - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class TypeFieldSection(TypeSection):
    """
    This class represents a type field section

    Extends: TypeSection
    """

    def __init__(
        self,
        type: str,
        name: str,
        label: str | None = None,
        fields: list[str] | None = None
    ) -> None:
        self.fields = fields or []
        super().__init__(type=type, name=name, label=label)

# -------------------------------------------------- CLASS FUNCTIONS ------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> "TypeFieldSection":
        """
        Generates a TypeFieldSection object from a dict

        Args:
            data (dict): Data with which the TypeFieldSection should be instantiated

        Returns:
            TypeFieldSection: TypeFieldSection class with given data
        """
        return cls(
            type=data.get(SectionKey.TYPE.value),
            name=data[SectionKey.NAME.value],
            label=data.get(SectionKey.LABEL.value),
            fields=data.get(SectionKey.FIELDS.value),
        )


    @classmethod
    def to_json(cls, instance: "TypeFieldSection") -> dict[str, Any]:
        """
        Returns a TypeFieldSection as JSON representation

        Args:
            instance (TypeFieldSection): TypeFieldSection which should be transformed

        Returns:
            dict: JSON representation of the given TypeFieldSection
        """
        return {
            SectionKey.TYPE.value: instance.type,
            SectionKey.NAME.value: instance.name,
            SectionKey.LABEL.value: instance.label,
            SectionKey.FIELDS.value: instance.fields
        }

# -------------------------------------------------- GENERAL METHODS ------------------------------------------------- #

    def get_fields(self) -> list[str]:
        """
        Retrieves all fields of the section

        Returns:
            list[str]: All fields of the section
        """
        return self.fields


    def __str__(self) -> str:
        return json.dumps(TypeFieldSection.to_json(self))
