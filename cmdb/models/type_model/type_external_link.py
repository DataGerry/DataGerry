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
This class represents an external link
"""
from logging import Logger, getLogger
from typing import Any
import re

from cmdb.errors.models.cmdb_type import CmdbTypeExternalFillError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                               TypeExternalLink - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class TypeExternalLink:
    """
    This class represents an external link
    """

    def __init__(
        self,
        name: str,
        href: str,
        label: str | None = None,
        icon: str | None = None,
        fields: list[str] | None = None
    ) -> None:
        """TODO: document"""
        self.name: str = name
        self.href: str = href
        self.label: str = label or self.name.title()
        self.icon: str | None = icon
        self.fields: list[str] = fields or []

# -------------------------------------------------- CLASS FUNCTIONS ------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> "TypeExternalLink":
        """
        Generates a TypeExternalLink object from a dict

        Args:
            data (dict): Data with which the TypeExternalLink should be instantiated

        Returns:
            TypeExternalLink: TypeExternalLink class with given data
        """
        return cls(
            name = data['name'],
            href = data['href'],
            label = data.get('label'),
            icon = data.get('icon'),
            fields = data.get('fields', [])
        )


    @classmethod
    def to_json(cls, instance: "TypeExternalLink") -> dict[str, Any]:
        """
        Returns a TypeExternalLink as JSON representation

        Args:
            instance (TypeExternalLink): TypeExternalLink which should be transformed

        Returns:
            dict: JSON representation of the given TypeExternalLink
        """
        return {
            'name': instance.name,
            'href': instance.href,
            'label': instance.label,
            'icon': instance.icon,
            'fields': instance.fields,
        }

# ------------------------------------------------- GENERAL FUNCTIONS ------------------------------------------------ #

    def has_icon(self) -> bool:
        """
        Checks if the TypeExternalLink has an icon

        Returns:
            (bool): True if icon is set else False
        """
        return bool(self.icon)


    def link_requires_fields(self) -> bool:
        """
        the type of arguments passed to it and formats it according to the format codes defined in the string
        checks if the href link requires field informations.

        Examples:
            http://example.org/{}/dynamic/ -> True
            http://example.org/static/ -> False

        Returns:
            bool
        """
        if re.search('{.*?}', self.href):
            return True

        return False


    def has_fields(self) -> bool:
        """
        Checks if the TypeExternalLink has any fields

        Returns:
            (bool): True if at least one field is set else False
        """
        return len(self.fields) > 0


    def fill_href(self, inputs: list[Any]) -> None:
        """
        Fills the href brackets with data
        """
        try:
            self.href = self.href.format(*inputs)
        except Exception as err:
            raise CmdbTypeExternalFillError(f"Href link do not fit with inputs: {self.href}!") from err
