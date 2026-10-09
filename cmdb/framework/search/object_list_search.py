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
The free-text search of the object list, as `?search=`

The object list has to match a term against a CmdbObject's own values **and** against the values of
the objects it references - a search for a customer's name finds the servers pointing at that
customer. The Angular app would otherwise implement that itself, as a nine-stage aggregation posted
through `?filter=`, copied into five files. This module is the server-side replacement, used by
`GET /objects/` and `GET /objects/references/<id>`.

**What is searchable:** the object's `public_id`, its two timestamps and the values of its own fields;
and, of every object it **references**, the values of that object's own fields. Not the summary line -
it is composed during rendering and never stored.

**How a reference is followed** is the rule of `GET /search/` (`search_reference_match`), so the two
cannot disagree:

* **only reference rows count** - a row whose stored `type` is one of `REFERENCE_FIELD_KINDS`. A number
  field whose value happens to equal an object's id is a number, and a legacy row without a `type` is
  not followed either
* **only readable referenced objects count** - the referenced objects are collected with the caller's
  ACL stages, so an object is never found by the contents of an object the caller may not read
* **nothing is joined per document** - the referenced objects matching the term are collected first, in
  one query answering their ids, and a candidate is then kept if its own values match or one of its
  reference rows carries one of those ids. Past `MAX_REFERENCED_MATCH_IDS` the same rule runs as a join
  in the database instead: slower, identical result

**Every value is matched as a string**, on both sides: a number, a date or a bool is converted first
(`as_text`), so a search for `42` finds a number field holding 42 - its own, or one of a referenced
object's.

**The term is a literal.** It is escaped before it becomes a regular expression, so a search for `C++`
finds `C++` and a search for `*` finds a `*`, case-insensitively. That is deliberately NOT what
`GET /search/`'s TEXT form does yet - that one is a regular expression by contract (T187).

**Nothing is projected away.** The stages only match (the join fallback adds one working field and
removes it again), so a searched listing returns the same documents an unsearched one does
"""
from typing import Any, TYPE_CHECKING

from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectFieldKey, CmdbObjectKey
from cmdb.framework.search.list_search import as_text
from cmdb.framework.search.search_constants import SEARCH_REGEX_FLAGS
from cmdb.framework.search.search_pattern import escape_search_term
from cmdb.framework.search.search_reference_match import build_text_term_stages

if TYPE_CHECKING:
    # Imported for type checking only - cmdb.manager imports the query builders, which import the search
    # package, so a module-level import would be circular
    from cmdb.manager import ObjectsManager
# -------------------------------------------------------------------------------------------------------------------- #

__all__ = [
    'build_field_values_expression',
    'build_object_search_stages',
    'build_own_values_expression',
    'build_term_condition',
]


def build_field_values_expression() -> dict[str, Any]:
    """
    Builds the expression collecting an object's field values, each as a string

    What a **referenced** object is searched by. The array is `$ifNull`-guarded, so an object without
    fields yields an empty list rather than null

    Returns:
        dict[str, Any]: The aggregation expression, an array of strings
    """
    return {
        '$map': {
            'input': {'$ifNull': [f'${CmdbObjectKey.FIELDS.value}', []]},
            'as': 'entry',
            'in': as_text(f'$$entry.{CmdbObjectFieldKey.VALUE.value}'),
        }
    }


def build_own_values_expression() -> dict[str, Any]:
    """
    Builds the expression collecting what a **listed** object is searched by, each as a string

    Its `public_id`, its two timestamps and its field values

    Returns:
        dict[str, Any]: The aggregation expression, an array of strings
    """
    return {
        '$concatArrays': [
            [as_text(f'${CmdbObjectKey.PUBLIC_ID.value}')],
            [as_text(f'${CmdbObjectKey.CREATION_TIME.value}')],
            [as_text(f'${CmdbObjectKey.LAST_EDIT_TIME.value}')],
            build_field_values_expression(),
        ]
    }


def build_term_condition(values_expression: dict[str, Any], term: str) -> dict[str, Any]:
    """
    Builds the query condition "one of these values contains the term"

    An `$expr`, because the values are computed strings rather than stored fields: a plain `$regex` on
    `fields.value` would only ever match the values that are stored as strings

    Args:
        values_expression (dict[str, Any]): An aggregation expression yielding an array of strings
        term (str): The term, already trimmed and known to be non-empty; escaped here

    Returns:
        dict[str, Any]: The condition, usable in a `$match` and inside a `$lookup` pipeline
    """
    return {
        '$expr': {
            '$anyElementTrue': [{
                '$map': {
                    'input': values_expression,
                    'as': 'value',
                    'in': {'$regexMatch': {
                        'input': '$$value',
                        'regex': escape_search_term(term),
                        'options': SEARCH_REGEX_FLAGS,
                    }},
                }
            }]
        }
    }


def build_object_search_stages(
        search_term: str | None,
        objects_manager: 'ObjectsManager',
        acl_stages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Builds the aggregation stages that narrow an object listing to a free-text term

    **Runs a query while building** - the one collecting the readable referenced objects that match the
    term - so a route builds these stages inside its own error handling. An empty or absent term adds
    **no stages and runs no query**, so an unsearched listing pays for none of it

    Args:
        search_term (str | None): The term as the request carried it; None or blank means no search
        objects_manager (ObjectsManager): Runs the query collecting the referenced objects
        acl_stages (list[dict[str, Any]]): The caller's access-control stages for reading objects, which
            the referenced objects have to pass; empty for none

    Returns:
        list[dict[str, Any]]: The stages to splice into the listing pipeline, possibly empty
    """
    term: str = (search_term or '').strip()

    if not term:
        return []

    return build_text_term_stages(
        objects_manager,
        build_term_condition(build_field_values_expression(), term),
        acl_stages,
        own_condition=build_term_condition(build_own_values_expression(), term),
    )
