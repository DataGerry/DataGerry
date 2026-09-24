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
The `?search=` of an ordinary list route

Every table in the product has a search box, and each one would otherwise implement it in the
browser: `$addFields` stages casting the columns it wanted to search with `$toString` /
`$dateToString`, then a `$match` with an `$or` of `$regex` conditions, posted as `?filter=`. Eighteen
screens, each hard-coding **which columns are searchable** and **how each is stringified** - the date
format alone differs between them, so the same text matches different things depending on which table
you are looking at.

This module is the one implementation. A route declares which of its fields are searchable and passes
the term; everything else - the conversion, the escaping, the cleanup - is the same everywhere.

**Every value is converted to a string first**, because `$regex` matches nothing else: a number, a
date, a bool or a null column would silently never match. That is not hypothetical - the ISMS impact
category filter regexes a numeric `public_id` under a comment saying it should be converted, and the
object list matched a `summary_line` that is not stored at all.

**The term is a literal**, escaped before it becomes a `$regex`, so a search for `C++` finds `C++` and
one for `.*` finds nothing. `object_list_search` is the richer sibling: the same match, over values
gathered through a `$lookup` as well as from the document itself
"""
import re
from collections.abc import Iterable, Sequence
from typing import Any

from cmdb.manager.query_builder.builder import Builder
from cmdb.framework.search.search_constants import SEARCH_REGEX_FLAGS, SEARCH_REGEX_RE_FLAGS
from cmdb.framework.search.search_pattern import escape_search_term
# -------------------------------------------------------------------------------------------------------------------- #

__all__ = [
    'SEARCHABLE_VALUES_FIELD',
    'matches_search_term',
    'as_text',
    'build_list_search_stages',
    'build_search_match_stages',
    'build_searchable_fields_expression',
]

#: Working field holding every searchable value of a document as a string; removed again at the end
SEARCHABLE_VALUES_FIELD: str = '__dg_searchable'

#: What a value is converted to before it is matched. A column can hold a number, a date, a bool or
#: null, and `$regex` matches none of those - so everything becomes a string first, and anything that
#: cannot be converted becomes the empty string rather than failing the whole aggregation
_AS_TEXT: dict[str, Any] = {'to': 'string', 'onError': '', 'onNull': ''}


def as_text(expression: Any) -> dict[str, Any]:
    """
    Wraps one aggregation expression in the string conversion every searchable value goes through

    A date converts to `2026-09-17T10:20:30.123Z`, which is byte for byte what the browser's
    `$dateToString` with `'%Y-%m-%dT%H:%M:%S.%LZ'` produced - so a term that matched a timestamp
    before still does, on the screens that used that format

    Args:
        expression (Any): The aggregation expression to convert

    Returns:
        dict[str, Any]: A `$convert` expression yielding a string, never an error and never null
    """
    return {'$convert': {'input': expression, **_AS_TEXT}}


def build_searchable_fields_expression(fields: Sequence[str]) -> dict[str, Any]:
    """
    Builds the expression collecting the named fields of a document as strings

    Args:
        fields (Sequence[str]): The field paths a search term is matched against, in any order

    Returns:
        dict[str, Any]: The aggregation expression, an array of strings
    """
    return {'$concatArrays': [[as_text(f'${field}')] for field in fields]}


def build_search_match_stages(values_expression: Any,
                              search_term: str,
                              extra_cleanup_fields: Sequence[str] = ()) -> list[dict[str, Any]]:
    """
    Builds the three stages every search shares: collect the values, match them, put the document back

    Split out so the object search - which gathers its values through a `$lookup` as well - matches
    and cleans up exactly the way an ordinary list does, rather than growing a second spelling of it.

    **Nothing is projected away.** The stages add a working field and remove it again, so a searched
    listing answers the same documents an unsearched one does. The browser's versions rebuilt each
    document with an inclusive `$project` and silently dropped every column they did not name

    Args:
        values_expression (Any): An aggregation expression yielding the array of strings to match
        search_term (str): The term, already trimmed and known to be non-empty
        extra_cleanup_fields (Sequence[str]): Further working fields the caller added and wants removed

    Returns:
        list[dict[str, Any]]: The `$addFields`, `$match` and `$project` stages
    """
    cleanup: dict[str, int] = {SEARCHABLE_VALUES_FIELD: 0}
    cleanup.update({field: 0 for field in extra_cleanup_fields})

    return [
        {'$addFields': {SEARCHABLE_VALUES_FIELD: values_expression}},
        Builder.match_(Builder.regex_(SEARCHABLE_VALUES_FIELD, escape_search_term(search_term), SEARCH_REGEX_FLAGS)),
        {'$project': cleanup},
    ]


def matches_search_term(values: Iterable[Any], search_term: str | None) -> bool:
    """
    Reports whether any of the given values contains the search term - the in-memory `?search=`

    The counterpart of `build_list_search_stages` for a collection that is NOT in MongoDB: the
    rights catalogue is a static in-code tree, so its list route cannot splice stages into a
    pipeline. Both sides share the same definition of a match, which is what keeps one `?search=`
    contract across the API - the term is escaped (it is text, never a pattern), matched
    case-insensitively, and every value is read as a string first

    An empty or absent term matches everything, exactly as an unsearched listing returns everything

    Args:
        values (Iterable[Any]): The values of one record's searchable fields
        search_term (str | None): The term as the request carried it; None or blank means no search

    Returns:
        bool: True when the record should be part of a searched listing
    """
    term: str = (search_term or '').strip()

    if not term:
        return True

    pattern = re.compile(escape_search_term(term), SEARCH_REGEX_RE_FLAGS)

    return any(pattern.search(str(value)) for value in values if value is not None)


def build_list_search_stages(search_term: str | None, fields: Sequence[str]) -> list[dict[str, Any]]:
    """
    Builds the aggregation stages narrowing a list route to a free-text term

    An empty or absent term, or an empty field set, adds **no stages at all**, so an unsearched
    listing pays for none of it

    Args:
        search_term (str | None): The term as the request carried it; None or blank means no search
        fields (Sequence[str]): The field paths this route declares searchable

    Returns:
        list[dict[str, Any]]: The stages to splice into the listing pipeline, possibly empty
    """
    term: str = (search_term or '').strip()

    if not term or not fields:
        return []

    return build_search_match_stages(build_searchable_fields_expression(fields), term)
