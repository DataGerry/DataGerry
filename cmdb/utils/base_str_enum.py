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
Shared base class for string-valued enums

Many DataGerry enums extend (str, Enum) to combine string semantics (dict keys, JSON
serialization, BSON wire format) with enum semantics (named members, type-safe lookups).
Most of them repeated the same is_valid() classmethod body. This module supplies a single
inheritance point so that body lives in one place and concrete enums stay declarative
"""
from enum import Enum
# -------------------------------------------------------------------------------------------------------------------- #


class BaseStrEnum(str, Enum):
    """
    Base for project-wide (str, Enum) classes that expose an is_valid() lookup

    Subclasses define their members as usual. Methods declared here are inherited by every
    concrete subclass; Python's Enum metaclass forbids further subclassing once members are
    defined, so adding members to a subclass remains a deliberate single-class action

    Designed as a small base today; place additional generic helpers here when more (str, Enum)
    classes need the same behavior
    """

    @classmethod
    def is_valid(cls, value: str) -> bool:
        """
        Checks whether the given string matches one of the concrete subclass's members

        Args:
            value (str): The string to test against the subclass member values

        Returns:
            bool: True if 'value' equals one of the subclass's enum values, False otherwise
        """
        return value in cls._value2member_map_
