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

from cmdb.errors.models.cmdb_type import CmdbTypeExternalFillError, CmdbTypeInitFromDataError
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
        """
        Initialises a TypeExternalLink

        Args:
            name (str): Identifier of the link within its CmdbType, unique among that type's externals
            href (str): The target URL. `{}` placeholders are filled per rendered object from `fields`
            label (str | None): What the frontend renders; defaults to the title-cased name
            icon (str | None): Icon class shown beside the label, None when the link carries none
            fields (list[str] | None): Names of the object fields whose values fill the placeholders,
                                       in order. `object_id` is accepted as a pseudo-field
        """
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
        name: Any = data.get('name')
        href: Any = data.get('href')

        if not name or not href:
            raise CmdbTypeInitFromDataError(
                f"An external link needs a name and an href, got name={name!r}, href={href!r}!"
            )

        return cls(
            name = name,
            href = href,
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
        Checks whether the href carries `{}` placeholders that have to be filled from object fields

        Examples:
            http://example.org/{}/dynamic/ -> True
            http://example.org/static/ -> False

        Returns:
            bool: True when the href contains at least one placeholder
        """
        return bool(re.search('{.*?}', self.href))


    def has_fields(self) -> bool:
        """
        Checks if the TypeExternalLink has any fields

        Returns:
            (bool): True if at least one field is set else False
        """
        return len(self.fields) > 0


    def filled_href(self, inputs: list[Any]) -> str:
        """
        Returns the href with its placeholders filled from the given values

        **Deliberately does not write `self.href`.** A TypeExternalLink belongs to a CmdbType, and the
        renderer shares ONE cached CmdbType across every object of that type in a batch - so filling in
        place left the first object's values in the template, after which `link_requires_fields()`
        answered False and every following object was served the first one's URL. Returning the value
        keeps the template pristine by construction rather than by every caller remembering to copy it

        Args:
            inputs (list[Any]): The field values to substitute, in the order the placeholders expect

        Raises:
            CmdbTypeExternalFillError: When the values do not fit the href's placeholders

        Returns:
            str: The filled href; the unchanged href when it carries no placeholders
        """
        try:
            return self.href.format(*inputs)
        except Exception as err:
            raise CmdbTypeExternalFillError(f"Href link do not fit with inputs: {self.href}!") from err
