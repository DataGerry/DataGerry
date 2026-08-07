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
Implementation of SearchResultMap
"""
from typing import TypeVar, Generic, Any

from cmdb.framework.search.search_constants import SearchResultMapKey
# -------------------------------------------------------------------------------------------------------------------- #

R = TypeVar('R')

# -------------------------------------------------------------------------------------------------------------------- #
#                                                SearchResultMap - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class SearchResultMap(Generic[R]):
    """
    Result mapper for Result/Match binding

    Binds one search result to the fields that matched the search patterns. The element type `R`
    must expose a `to_json()`; `RenderResult` is the only type used today
    """
    def __init__(self, result: R, matches: list[dict[str, Any]] | None = None) -> None:
        """
        Initialize a SearchResultMap

        Args:
            result (R): The search result being wrapped
            matches (list[dict[str, Any]] | None): The field entries that matched the search, or None
                when the search carried no patterns or nothing matched
        """
        self.result: R = result
        self.matches: list[dict[str, Any]] | None = matches


    def to_json(self) -> dict[str, Any]:
        """
        Serialize the result/match binding for the API response

        Returns:
            dict[str, Any]: The serialized result together with its matched fields
        """
        return {
            SearchResultMapKey.RESULT.value: self.result.to_json(),
            SearchResultMapKey.MATCHES.value: self.matches,
        }
