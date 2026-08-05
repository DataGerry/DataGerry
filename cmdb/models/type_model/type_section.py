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
This class represents a type section
"""
from logging import Logger, getLogger
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  TypeSection - CLASS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TypeSection:
    """Type section class"""

    def __init__(self, type: str, name: str, label: str | None = None) -> None:
        self.type: str = type
        self.name: str = name
        self.label: str = label or self.name.title()

# -------------------------------------------------- CLASS FUNCTIONS ------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> "TypeSection":
        """
        Generates a TypeSection object from a dict

        Args:
            data (dict): Data with which the TypeSection should be instantiated

        Returns:
            TypeSection: TypeSection class with given data
        """
        return cls(
            type = data['type'],
            name = data['name'],
            label = data.get('label'),
        )


    @classmethod
    def to_json(cls, instance: "TypeSection") -> dict[str, Any]:
        """
        Returns a TypeSection as JSON representation

        Args:
            instance (TypeSection): TypeSection which should be transformed

        Returns:
            dict: JSON representation of the given TypeSection
        """
        return {
            'type': instance.type,
            'name': instance.name,
            'label': instance.label
        }
