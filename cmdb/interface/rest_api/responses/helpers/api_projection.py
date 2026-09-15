# DataGerry - OpenSource Enterprise CMDB
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
Implementation of APIProjection

`APIProjection` wraps the client-supplied `projection` query parameter and splits it into the
set of keys to include and the set to exclude, which `APIProjector` then applies to the response
document(s). Two input shapes are accepted:

- a **dict** mapping field name -> flag, MongoDB-style: a truthy flag (``1``) marks the key as an
  *include*, a falsy flag (``0``) marks it as an *exclude*;
- a **list** of field names, treated as an all-includes projection (equivalent to ``{name: 1}``).

Every key is classified by the truthiness of its flag, so no key is ever silently dropped. The
include and exclude key sets are derived once at construction; includes and excludes are exposed
independently and `APIProjector` decides how to combine them.
"""
from logging import Logger, getLogger
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 APIProjection - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class APIProjection:
    """
    Wrapper around the `projection` query parameter, exposing its include and exclude keys
    """

    def __init__(self, projection: dict | list | None = None) -> None:
        """
        Normalizes the projection and derives its include/exclude key sets

        Args:
            projection (dict | list | None): Either a MongoDB-style ``{field: 1|0}`` mapping, a
                list of field names (treated as an all-includes projection), or None (empty
                projection). A truthy flag marks an include, a falsy flag marks an exclude
        """
        if isinstance(projection, list):
            projection = dict.fromkeys(projection, 1)

        self.projection: dict = projection or {}
        self.__includes: list[str] = self.__select_keys(self.projection, include=True)
        self.__excludes: list[str] = self.__select_keys(self.projection, include=False)

# ---------------------------------------------------- PROPERTIES ---------------------------------------------------- #

    @property
    def includes(self) -> list[str]:
        """
        The keys marked for inclusion (those with a truthy projection flag)

        Returns:
            list[str]: The projection keys to keep
        """
        return self.__includes


    @property
    def excludes(self) -> list[str]:
        """
        The keys marked for exclusion (those with a falsy projection flag)

        Returns:
            list[str]: The projection keys to drop
        """
        return self.__excludes


    @property
    def has_includes(self) -> bool:
        """
        Whether the projection selects any keys for inclusion

        Returns:
            bool: True if at least one key is marked for inclusion
        """
        return bool(self.__includes)


    @property
    def has_excludes(self) -> bool:
        """
        Whether the projection selects any keys for exclusion

        Returns:
            bool: True if at least one key is marked for exclusion
        """
        return bool(self.__excludes)

# -------------------------------------------------- STATIC METHODS -------------------------------------------------- #

    @staticmethod
    def __select_keys(projection: dict, include: bool) -> list[str]:
        """
        Selects the projection keys on one side of the include/exclude split

        Each key is classified by the truthiness of its flag, so every key lands in exactly one
        set and none is silently dropped: a truthy flag is an include, a falsy flag is an exclude.

        Args:
            projection (dict): The normalized projection mapping (field name -> flag)
            include (bool): True to return the include keys (truthy flags), False to return the
                exclude keys (falsy flags)

        Returns:
            list[str]: The keys whose flag falls on the requested side of the split
        """
        return [key for key, value in projection.items() if bool(value) == include]
