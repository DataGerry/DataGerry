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

The object list has to match a term against a CmdbObject's own field values **and** against the
values of the objects it references - a search for a customer's name finds the servers pointing at
that customer. The Angular app would otherwise implement that itself, as a nine-stage aggregation
posted through `?filter=`, copied into five files
posted as a client filter. This module is the server-side replacement.

**What is searchable:** the object's `public_id`, its two timestamps, the values of its own fields,
and the values of the fields of every object it references. Not the summary line - it is composed
during rendering and never stored, so the browser's version of this query matched it against nothing
and said so with a 200.

**The term is a literal.** It is escaped before it becomes a `$regex`, so a search for `C++` finds
`C++` and a search for `*` finds a `*`. That is the newer convention across the backend
(`locations_manager`, `mongo_query_builder`, `assignable_cables`, ...) and it is deliberately NOT
what `GET /search/`'s TEXT form does yet - that one is a regular expression by contract, and aligning
it needs the frontend to stop escaping at the same time.

**Nothing is projected away.** The browser's pipeline rebuilt each document with an explicit
`$project`, which silently dropped everything it did not list - `multi_data_sections`, `version`,
`editor_id`. These stages only *add* two working fields and remove them again, so a searched listing
returns the same documents an unsearched one does
"""
from typing import Any

from cmdb.manager.query_builder.builder import Builder
from cmdb.models.object_model.cmdb_object import CmdbObject
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectFieldKey, CmdbObjectKey
from cmdb.framework.search.list_search import as_text, build_search_match_stages
# -------------------------------------------------------------------------------------------------------------------- #

__all__ = [
    'REFERENCED_OBJECTS_FIELD',
    'build_object_search_stages',
    'build_searchable_values_expression',
]

#: Working field holding the joined referenced objects; removed again by the last stage
REFERENCED_OBJECTS_FIELD: str = '__dg_referenced'


def build_searchable_values_expression() -> dict[str, Any]:
    """
    Builds the expression collecting everything a search term is matched against, as strings

    The referenced values come from the joined documents in `REFERENCED_OBJECTS_FIELD`, flattened with
    the same `$reduce` / `$setUnion` the frontend used and the backend's own
    `SearchReferencesPipelineBuilder` still uses. Every array is `$ifNull`-guarded because
    `$concatArrays` answers null if any of its inputs is null, which would make an object with no
    fields unsearchable rather than merely unmatched

    Returns:
        dict[str, Any]: The aggregation expression, an array of strings
    """
    own_and_referenced_entries: dict[str, Any] = {
        '$concatArrays': [
            {'$ifNull': [f'${CmdbObjectKey.FIELDS.value}', []]},
            {'$reduce': {
                'input': {'$ifNull': [f'${REFERENCED_OBJECTS_FIELD}.{CmdbObjectKey.FIELDS.value}', []]},
                'initialValue': [],
                'in': {'$setUnion': ['$$value', '$$this']},
            }},
        ]
    }

    return {
        '$concatArrays': [
            [as_text(f'${CmdbObjectKey.PUBLIC_ID.value}')],
            [as_text(f'${CmdbObjectKey.CREATION_TIME.value}')],
            [as_text(f'${CmdbObjectKey.LAST_EDIT_TIME.value}')],
            {'$map': {
                'input': own_and_referenced_entries,
                'as': 'entry',
                'in': as_text(f'$$entry.{CmdbObjectFieldKey.VALUE.value}'),
            }},
        ]
    }


def build_object_search_stages(search_term: str | None) -> list[dict[str, Any]]:
    """
    Builds the aggregation stages that narrow an object listing to a free-text term

    Four stages: join the referenced objects, collect every searchable value as a string, match the
    term against them, and drop both working fields again. An empty or absent term adds **no stages
    at all**, so an unsearched listing pays for none of it.

    Args:
        search_term (str | None): The term as the request carried it; None or blank means no search

    Returns:
        list[dict[str, Any]]: The stages to splice into the listing pipeline, possibly empty
    """
    term: str = (search_term or '').strip()

    if not term:
        return []

    return [
        Builder.lookup_(
            CmdbObject.COLLECTION,
            f'{CmdbObjectKey.FIELDS.value}.{CmdbObjectFieldKey.VALUE.value}',
            CmdbObjectKey.PUBLIC_ID.value,
            REFERENCED_OBJECTS_FIELD,
        ),
        *build_search_match_stages(
            build_searchable_values_expression(), term, extra_cleanup_fields=(REFERENCED_OBJECTS_FIELD,),
        ),
    ]
