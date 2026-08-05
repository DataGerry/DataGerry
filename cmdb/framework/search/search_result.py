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
Implementation of SearchResult
"""
from logging import Logger, getLogger
from typing import TypeVar, Generic, Any
from bson import Regex

from cmdb.framework.search.search_result_map import SearchResultMap
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

R = TypeVar('R')

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 SearchResult - CLASS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class SearchResult(Generic[R]):
    """
    Generic container for paginated search results.

    This class wraps a list of search results, along with metadata
    about the search such as pagination info, grouping, and regex matches.
    """
    #pylint: disable=R0917
    def __init__(self,
                 results: list[R],
                 total_results: int,
                 groups: list,
                 alive: bool,
                 limit: int,
                 skip: int,
                 matches_regex: list[str] = None):
        """
        Initialize a SearchResult

        Args:
            results (list[R]): List of generic search result objects
            total_results (int): Total number of results available in the database
            groups (list[Any]): Groups of objects related to the search results
            alive (bool): Flag indicating if there are more results available beyond the current limit
            limit (int): Maximum number of results to return (page size)
            skip (int): Number of results to skip (offset)
            matches_regex (list[str] | None): List of regex patterns to check matches within results
        """
        self.limit: int = limit
        self.skip: int = skip
        self.total_results: int = total_results
        self.alive = alive
        self.groups = groups
        self.results: list[SearchResultMap] = [
            SearchResultMap[R](result=result, matches=self.find_match_fields(result, matches_regex)) for result in
            results]


    def __len__(self) -> int:
        """
        Get the number of search results

        Returns:
            int: Number of search result objects in this page
        """
        return len(self.results)


    @staticmethod
    def find_match_fields(result: R, possible_regex_list: list[str] = None) -> list[Any] | None:

        """
        Find fields inside a result object that match any given regex patterns

        Args:
            result (R): A single search result object
            possible_regex_list (list[str] | None): List of regex patterns to match fields against

        Returns:
            list[Any] | None: List of fields where a regex matched, or None if no matches
        """
        matched_fields = []
        fields = result.fields

        if not possible_regex_list:
            return None


        def inner_match_fields(_fields: list[dict[str, Any]],
                               _matched_fields: list[Any],
                               _reference: dict[str, Any] = None) -> None:
            """
            Recursively search fields and nested fields for regex matches

            Args:
                _fields (List[Dict[str, Any]]): List of field dictionaries to check
                _matched_fields (List[Any]): List to store fields that matched
                _reference (dict[str, Any] | None): Optional reference object for nested fields
            """
            for regex_ in possible_regex_list:
                try:
                    runtime_regex = Regex(regex_, 'ims').try_compile()
                except Exception:
                    runtime_regex = regex_
                for field in _fields:
                    try:
                        res = runtime_regex.findall(str(field.get('value')))
                        if len(res) > 0:
                            inner_value = _reference if _reference else field
                            # removing duplicated from list
                            if inner_value not in _matched_fields:
                                _matched_fields.append(inner_value)
                        if field['type'] == 'ref':
                            inner_match_fields(field['reference']['summaries'], _matched_fields, field)
                        if field['type'] == 'ref-section-field':
                            inner_match_fields(field['references']['fields'], _matched_fields, field)
                    except Exception:
                        continue

        inner_match_fields(fields, matched_fields)

        if len(matched_fields) > 0:
            return matched_fields

        return None


    def to_json(self) -> dict:
        """
        Serialize the search result to a JSON-serializable dictionary

        Returns:
            dict: Dictionary containing all relevant search result data
        """
        return {
            'limit': self.limit,
            'skip': self.skip,
            'groups': self.groups,
            'total_results': self.total_results,
            'number_of_results': len(self),
            'results': self.results
        }
