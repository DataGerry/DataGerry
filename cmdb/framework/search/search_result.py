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
import re
from logging import Logger, getLogger
from typing import TypeVar, Generic, Any
from bson import Regex

from cmdb.framework.rendering.render_constants import RenderedFieldKey
from cmdb.framework.search.search_constants import (
    SEARCH_REGEX_FLAGS,
    SEARCH_REGEX_RE_FLAGS,
    SearchResultKey,
)
from cmdb.framework.search.search_result_map import SearchResultMap
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.field_type_enum import FieldType
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

R = TypeVar('R')

#: Hard bound on how deep the matcher follows reference expansions. `CmdbMultiRender` produces a
#: finite structure, so this is purely a guard against a cyclic expansion turning a search into a
#: RecursionError. It is deliberately far above any real nesting depth
MAX_REFERENCE_DEPTH: int = 10


def compile_search_pattern(raw_pattern: Any) -> re.Pattern:
    """
    Compiles one raw search pattern, falling back to a literal match when it is not a usable regex

    The patterns come from the `$regex` values of the executed aggregation pipeline, so a caller can
    reach this with anything Mongo accepted. A pattern that cannot be compiled is matched literally
    (via `re.escape`) rather than dropped, so a search for something like `[unclosed` still finds the
    objects that literally contain that text instead of silently matching nothing

    Args:
        raw_pattern (Any): A `$regex` value lifted out of the search pipeline

    Returns:
        re.Pattern: The compiled pattern, or an escaped literal pattern if compilation failed
    """
    if isinstance(raw_pattern, str):
        try:
            return Regex(raw_pattern, SEARCH_REGEX_FLAGS).try_compile()
        except re.error as err:
            LOGGER.debug(
                "[compile_search_pattern] '%s' is not a valid regex (%s), matching it literally", raw_pattern, err
            )
    else:
        LOGGER.debug("[compile_search_pattern] Pattern is a %s, not a str, matching it literally", type(raw_pattern))

    return re.compile(re.escape(str(raw_pattern)), SEARCH_REGEX_RE_FLAGS)


def compile_search_patterns(raw_patterns: list[str] | None) -> list[re.Pattern]:
    """
    Compiles every raw search pattern once, up front

    Compiling here rather than inside the field walk matters: the walk visits each pattern at every
    field of every result, so compiling per visit repeated the same work for each nesting level

    Args:
        raw_patterns (list[str] | None): The `$regex` values of the search pipeline, if any

    Returns:
        list[re.Pattern]: The compiled patterns; empty when nothing was passed
    """
    return [compile_search_pattern(raw_pattern) for raw_pattern in raw_patterns or []]


def field_value_matches(field: dict[str, Any], patterns: list[re.Pattern]) -> bool:
    """
    Checks whether a field's value matches any of the compiled search patterns

    A field carrying no value never matches: it holds no text to search. Everything else is
    stringified before matching, so numeric and boolean values are searchable, and a value of `0`,
    `False` or `''` is matched on its own text rather than being treated as absent

    Args:
        field (dict[str, Any]): A single rendered field entry
        patterns (list[re.Pattern]): The compiled search patterns

    Returns:
        bool: True if at least one pattern matches the field's value
    """
    value = field.get(FieldKey.VALUE.value)

    if value is None:
        return False

    return any(pattern.search(str(value)) for pattern in patterns)


def get_reference_expansion(field: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Returns the nested fields a reference-like field expands into

    A `FieldType.REFERENCE` field carries the referenced object's summary fields, and a
    `FieldType.REF_SECTION` field the pulled-in section fields. Both expansions are added by
    `CmdbMultiRender` and are absent whenever the reference could not be resolved, so every step is
    checked rather than subscripted

    Args:
        field (dict[str, Any]): A single rendered field entry

    Returns:
        list[dict[str, Any]]: The nested field entries, or an empty list for a plain or unresolved field
    """
    field_type = field.get(FieldKey.TYPE.value)

    if field_type == FieldType.REFERENCE:
        expansion_key, nested_key = RenderedFieldKey.REFERENCE, RenderedFieldKey.SUMMARIES
    elif field_type == FieldType.REF_SECTION:
        expansion_key, nested_key = RenderedFieldKey.REFERENCES, RenderedFieldKey.FIELDS
    else:
        return []

    expansion = field.get(expansion_key.value)

    if not isinstance(expansion, dict):
        return []

    nested_fields = expansion.get(nested_key.value)

    return nested_fields if isinstance(nested_fields, list) else []


def append_unique(matched_fields: list[dict[str, Any]], field: dict[str, Any]) -> None:
    """
    Appends a field to the match list unless an equal entry is already present

    Args:
        matched_fields (list[dict[str, Any]]): The accumulated matches, modified in place
        field (dict[str, Any]): The field entry to record
    """
    if field not in matched_fields:
        matched_fields.append(field)


def collect_matching_fields(
    fields: list[dict[str, Any]],
    patterns: list[re.Pattern],
    reference: dict[str, Any] | None = None,
    depth: int = 0,
) -> list[dict[str, Any]]:
    """
    Walks a list of rendered fields and collects the ones matching any search pattern

    Recurses into reference expansions. A match found inside an expansion is attributed to the field
    that *carries* the expansion, not to the nested field itself — that is what `reference` is for:
    it is the immediate parent field of the level being walked, and it is what gets recorded when a
    nested value matches. Attribution is one level only, so a hit two references deep is reported as
    the intermediate reference field rather than the outermost one. The frontend renders each entry
    with `<cmdb-render-element>`, so an entry must always be a complete field dict

    Results are deduplicated by equality and returned in field order — several patterns matching the
    same field, or several nested values under the same reference, yield a single entry

    Args:
        fields (list[dict[str, Any]]): The rendered field entries to walk
        patterns (list[re.Pattern]): The compiled search patterns
        reference (dict[str, Any] | None): The parent field to attribute nested matches to. None at
            the top level, where a match is attributed to the matching field itself
        depth (int): Current reference-expansion depth, bounded by `MAX_REFERENCE_DEPTH`

    Returns:
        list[dict[str, Any]]: The matching field entries, in field order, without duplicates
    """
    matched_fields: list[dict[str, Any]] = []

    if depth > MAX_REFERENCE_DEPTH:
        LOGGER.warning(
            "[collect_matching_fields] Reference expansion deeper than %s levels, stopping the walk",
            MAX_REFERENCE_DEPTH,
        )

        return matched_fields

    for field in fields:
        if not isinstance(field, dict):
            LOGGER.debug("[collect_matching_fields] Skipping a field entry of type %s", type(field))
            continue

        if field_value_matches(field, patterns):
            append_unique(matched_fields, reference if reference is not None else field)

        for nested_match in collect_matching_fields(get_reference_expansion(field), patterns, field, depth + 1):
            append_unique(matched_fields, nested_match)

    return matched_fields

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 SearchResult - CLASS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class SearchResult(Generic[R]):
    """
    Generic container for paginated search results

    This class wraps a list of search results, along with metadata about the search such as
    pagination info, grouping, and regex matches.

    The element type `R` is generic in name only: it must expose a `fields` list (walked to find the
    matched fields) and a `to_json()` (called by `SearchResultMap` when serializing). `RenderResult`
    is the only type used today
    """
    #pylint: disable=R0917
    def __init__(self,
                 results: list[R],
                 total_results: int,
                 groups: list[dict[str, Any]],
                 alive: bool,
                 limit: int,
                 skip: int,
                 matches_regex: list[str] | None = None):
        """
        Initialize a SearchResult

        The search patterns are compiled once here and reused for every result, rather than being
        recompiled per result

        Args:
            results (list[R]): List of generic search result objects
            total_results (int): Total number of results available in the database
            groups (list[dict[str, Any]]): Groups of objects related to the search results
            alive (bool): Flag indicating if there are more results available beyond the current limit
            limit (int): Maximum number of results to return (page size)
            skip (int): Number of results to skip (offset)
            matches_regex (list[str] | None): List of regex patterns to check matches within results
        """
        self.limit: int = limit
        self.skip: int = skip
        self.total_results: int = total_results
        self.alive: bool = alive
        self.groups: list[dict[str, Any]] = groups

        patterns = compile_search_patterns(matches_regex)

        self.results: list[SearchResultMap] = [
            SearchResultMap[R](result=result, matches=self.match_result(result, patterns)) for result in results
        ]


    def __len__(self) -> int:
        """
        Get the number of search results

        Returns:
            int: Number of search result objects in this page
        """
        return len(self.results)


    @staticmethod
    def match_result(result: R, patterns: list[re.Pattern]) -> list[dict[str, Any]] | None:
        """
        Finds the fields of a single result that match any of the compiled search patterns

        Args:
            result (R): A single search result object, exposing a `fields` list
            patterns (list[re.Pattern]): The compiled search patterns

        Returns:
            list[dict[str, Any]] | None: The matching field entries, or None when there is nothing to
                match against or nothing matched. None (rather than an empty list) is what the
                frontend checks to show its "No displayable content." fallback
        """
        if not patterns:
            return None

        return collect_matching_fields(result.fields, patterns) or None


    @staticmethod
    def find_match_fields(result: R, possible_regex_list: list[str] | None = None) -> list[dict[str, Any]] | None:
        """
        Find fields inside a result object that match any given regex patterns

        Single-result entry point that compiles the patterns itself. `__init__` does not use it — it
        compiles once for the whole page and calls `match_result` per result instead

        Args:
            result (R): A single search result object
            possible_regex_list (list[str] | None): List of regex patterns to match fields against

        Returns:
            list[dict[str, Any]] | None: List of fields where a regex matched, or None if no matches
        """
        return SearchResult.match_result(result, compile_search_patterns(possible_regex_list))


    def to_json(self) -> dict[str, Any]:
        """
        Serialize the search result to a JSON-serializable dictionary

        `results` holds `SearchResultMap` instances rather than dicts; the `database_utils.default`
        JSON hook converts them on the way out

        Returns:
            dict[str, Any]: Dictionary containing all relevant search result data
        """
        return {
            SearchResultKey.LIMIT.value: self.limit,
            SearchResultKey.SKIP.value: self.skip,
            SearchResultKey.GROUPS.value: self.groups,
            SearchResultKey.TOTAL_RESULTS.value: self.total_results,
            SearchResultKey.NUMBER_OF_RESULTS.value: len(self),
            SearchResultKey.RESULTS.value: self.results,
        }
