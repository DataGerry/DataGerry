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
What a search term becomes on its way into a `$regex`

A search term reaches MongoDB as a regular expression, so a term that is not a usable pattern is not
a search that finds nothing - it is a query the database **refuses**, which the route answers as a
400. Typing `*` into a search box is not a client error.

This module holds the one rule that prevents it: a term that compiles is sent as written, a term that
does not is sent as an escaped literal, so every term is answerable. It is the query-side twin of
`search_result.compile_search_pattern`, which applies the identical rule when the *highlighting* reads
the executed patterns back out of the pipeline - the two together are why a search for `[unclosed`
both runs and highlights what it matched.

**Python's `re` is the gate, and it is close to MongoDB's PCRE but not identical.** Measured on
Python 3.12: `*`, `[unclosed` and `a**` are refused by both, while `C++` compiles in both (possessive
quantifiers have been valid `re` syntax since 3.11). So this rule turns a **refused** query into an
answerable one; it does not turn a valid-but-surprising pattern into a literal. `C++` still matches
`CCC`, and that half needs the frontend to stop escaping at the same time - tier 2 **T187**.

The fallback is applied to the TEXT form only, never to REGEX: there a caller has asked for a pattern,
and a second engine's opinion of it must not silently change what they meant. Where the two engines
disagree, a REGEX term is the caller's problem to hear about; a TEXT term is not
"""
import re
from logging import Logger, getLogger

from bson import Regex

from cmdb.framework.search.search_constants import SEARCH_REGEX_FLAGS
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

__all__ = ['as_executable_pattern', 'escape_search_term']

# -------------------------------------------------------------------------------------------------------------------- #


def as_executable_pattern(raw_pattern: str) -> str:
    """
    Returns a `$regex` value the database can execute, whatever the caller typed

    A pattern that compiles is returned unchanged, so a caller that meant a regular expression still
    gets one; a pattern that does not is returned `re.escape`d, so it is matched as the literal text
    it evidently was. Nothing is ever dropped, and nothing raises

    Args:
        raw_pattern (str): The search term as the request carried it

    Returns:
        str: The term itself when it is a usable pattern, an escaped literal when it is not
    """
    try:
        Regex(raw_pattern, SEARCH_REGEX_FLAGS).try_compile()

        return raw_pattern
    except re.error as err:
        LOGGER.debug(
            "[as_executable_pattern] '%s' is not a valid regex (%s), matching it literally", raw_pattern, err
        )

        return re.escape(raw_pattern)


def escape_search_term(term: str) -> str:
    """
    Escapes a search term so it is matched as the literal text the user typed

    The whole of the `?search=` contract, in one line: that term is **not** a pattern. It is the
    opposite end of `as_executable_pattern`, which keeps a pattern a pattern where one was asked for -
    the two sit together because which of them a route reaches for *is* its search contract

    Args:
        term (str): The raw search term

    Returns:
        str: The term with its regex metacharacters escaped
    """
    return re.escape(term)
