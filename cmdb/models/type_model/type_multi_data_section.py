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
Implementation of a TypeMultiDataSection
"""
from logging import Logger, getLogger
from typing import Any
import json

from cmdb.models.type_model.type_section import TypeSection
from cmdb.models.type_model.section_key_enum import SectionKey
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                             TypeMultiDataSection - CLASS                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class TypeMultiDataSection(TypeSection):
    """
    This class represents a TypeMultiDataSection

    Extends: TypeSection
    """

    def __init__(
        self,
        type: str,
        name: str,
        label: str | None = None,
        fields: list[str] | None = None,
        hidden_fields: list[str] | None = None
    ) -> None:
        """TODO: document"""
        self.fields = fields or []
        self.hidden_fields = hidden_fields or []
        super().__init__(type=type, name=name, label=label)

# -------------------------------------------------- CLASS FUNCTIONS ------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> "TypeMultiDataSection":
        """
        Generates a TypeMultiDataSection object from a dict

        Args:
            data (dict): Data with which the TypeMultiDataSection should be instantiated

        Returns:
            TypeMultiDataSection: TypeMultiDataSection class with given data
        """
        return cls(
            type=data[SectionKey.TYPE.value],
            name=data[SectionKey.NAME.value],
            label=data.get(SectionKey.LABEL.value),
            fields=data.get(SectionKey.FIELDS.value),
            hidden_fields=data.get(SectionKey.HIDDEN_FIELDS.value, [])
        )


    @classmethod
    def to_json(cls, instance: "TypeMultiDataSection") -> dict[str, Any]:
        """
        Returns a TypeMultiDataSection as JSON representation

        Args:
            instance (TypeMultiDataSection): TypeMultiDataSection which should be transformed

        Returns:
            dict: JSON representation of the given TypeMultiDataSection
        """
        return {
            SectionKey.TYPE.value: instance.type,
            SectionKey.NAME.value: instance.name,
            SectionKey.LABEL.value: instance.label,
            SectionKey.FIELDS.value: instance.fields,
            SectionKey.HIDDEN_FIELDS.value: instance.hidden_fields
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
        """TODO: document"""
        return json.dumps(TypeMultiDataSection.to_json(self))
