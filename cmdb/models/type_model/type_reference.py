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
This class represents a type reference
"""
import logging
import re

from cmdb.errors.models.cmdb_type import CmdbTypeReferenceLineFillError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                     TypeReference                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TypeReference:
    """Represents a type reference"""

    def __init__(self, type_id: int, object_id: int, type_label: str, line: str = None,
                 prefix: bool = False, icon=None, summaries: list = None):
        self.type_id = type_id
        self.object_id = object_id
        self.type_label = type_label or ''
        self.summaries = summaries or []
        self.line = line
        self.icon = icon
        self.prefix = prefix

# -------------------------------------------------- CLASS FUCNTIONS ------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict) -> "TypeReference":
        """
        Generates a TypeReference object from a dict

        Args:
            data (dict): Data with which the TypeReference should be instantiated

        Returns:
            TypeReference: TypeReference class with given data
        """
        return cls(
            type_id = data.get('type_id'),
            object_id = data.get('object_id'),
            line = data.get('line'),
            type_label = data.get('type_label', None),
            summaries = data.get('summaries', None),
            icon = data.get('icon', False),
            prefix = data.get('prefix', None)
        )


    @classmethod
    def to_json(cls, instance: "TypeReference") -> dict:
        """
        Returns a TypeReference as JSON representation

        Args:
            instance (TypeReference): TypeReference which should be transformed

        Returns:
            dict: JSON representation of the given TypeReference
        """
        return {
            'type_id': instance.type_id,
            'object_id': instance.object_id,
            'line': instance.line,
            'type_label': instance.type_label,
            'summaries': instance.summaries,
            'icon': instance.icon,
            'prefix': instance.prefix
        }

# ------------------------------------------------- GENERAL FUNCTIONS ------------------------------------------------ #

    def has_prefix(self) -> bool:
        """
        Checks if the TypeReference has a prefix

        Returns:
            (bool): True if prefix is set else False
        """
        return bool(self.prefix)


    def has_icon(self) -> bool:
        """
        Checks if the TypeReference has an icon

        Returns:
            (bool): True if icon is set else False
        """
        return bool(self.icon)


    def line_requires_fields(self) -> bool:
        """
        The type of arguments passed to it and formats it according to the format codes defined in the string
        checks if the line requires field informations.
        Examples:
            example {} -> True
            example -> False
        Returns:
            bool
        """
        if re.search('{.*?}', self.line):
            return True
        return False


    def has_summaries(self) -> bool:
        """
        Checks if the TypeReference has summaries

        Returns:
            (bool): True if at least one summary is set else False
        """
        return len(self.summaries) > 0


    def fill_line(self, inputs) -> None:
        """Fills the line brackets with data"""
        try:
            self.line = self.line.format(*inputs)
        except Exception as err:
            raise CmdbTypeReferenceLineFillError(
                f"Type reference summary line do not fit with inputs: {self.line}!"
            ) from err
