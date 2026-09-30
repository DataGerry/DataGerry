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
How one search term finds an object through what it references

A search term matches a CmdbObject when one of the object's **own** field values matches it, or when
the object **references** another object one of whose own field values matches it - a search for a
customer's name finds the servers pointing at that customer. Both `GET|POST /search/` and the quick
search count answer that question through this module, so the two cannot disagree.

**The join is reversed.** Rather than joining every object with everything it references and then
matching the merged fields, the term is matched first, on its own, against the objects that could be
referenced - one plain query, answering their `public_id`s - and a candidate is then kept if its own
values match OR one of its **reference rows** carries one of those ids. No document is joined, so a
hit comes back exactly as stored: nothing is projected away and no referenced value is folded into it.

Three rules the reversal makes explicit:

* **only reference rows count** - a stored row whose `type` is one of `REFERENCE_FIELD_KINDS`. A
  number field whose value happens to equal an object's id is a number; a legacy row without a
  `type` is not counted either
* **only readable referenced objects count** - the first query carries the caller's ACL stages, so an
  object cannot be found by the contents of an object the caller may not read
* **the answer does not depend on how many objects the term matches** - past
  `MAX_REFERENCED_MATCH_IDS`, the id list would outgrow what an aggregation command may carry, so the
  same rule is evaluated by a join in the database instead: slower, identical result
"""
from typing import Any, TYPE_CHECKING

from cmdb.utils import Builder
from cmdb.models.object_model.cmdb_object import CmdbObject
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectFieldKey, CmdbObjectKey
from cmdb.framework.search.search_constants import (
    MAX_REFERENCED_MATCH_IDS,
    REFERENCE_FIELD_KINDS,
    REFERENCED_MATCH_FIELD,
)

if TYPE_CHECKING:
    # Imported for type checking only - cmdb.manager imports the query builders, which import this
    # module, so a module-level import would be circular
    from cmdb.manager import ObjectsManager
# -------------------------------------------------------------------------------------------------------------------- #

__all__ = [
    'build_reference_rows_condition',
    'build_term_join_stages',
    'build_text_term_stages',
    'collect_referenced_match_ids',
]


def collect_referenced_match_ids(
        objects_manager: 'ObjectsManager',
        value_condition: dict[str, Any],
        acl_stages: list[dict[str, Any]],
        limit: int = MAX_REFERENCED_MATCH_IDS) -> list[int] | None:
    """
    Answers the public_ids of the objects whose own field values match a term

    These are the objects a candidate may reference to be found through them. The caller's ACL stages
    run here, so an object the caller may not read is never one of them

    Args:
        objects_manager (ObjectsManager): Runs the query against `framework.objects`
        value_condition (dict[str, Any]): The term's match on the own field values
        acl_stages (list[dict[str, Any]]): The caller's access-control stages; empty for none
        limit (int): The most ids answered as a list. Defaults to MAX_REFERENCED_MATCH_IDS

    Returns:
        list[int] | None: The matching ids, or None when there are more than `limit` of them
    """
    pipeline: list[dict[str, Any]] = [
        Builder.match_(value_condition),
        *acl_stages,
        Builder.project_({'_id': 0, CmdbObjectKey.PUBLIC_ID.value: 1}),
        # One past the limit is enough to know the limit was passed, without reading the rest
        Builder.limit_(limit + 1),
    ]

    public_ids: list[int] = [
        document[CmdbObjectKey.PUBLIC_ID.value] for document in objects_manager.aggregate_objects(pipeline=pipeline)
    ]

    return None if len(public_ids) > limit else public_ids


def build_reference_rows_condition(referenced_ids: list[int]) -> dict[str, Any]:
    """
    Builds the condition "one of the object's reference rows carries one of these ids"

    Row kind and row value are matched in ONE `$elemMatch`, so both have to hold for the same row: a
    reference row pointing elsewhere next to a number row holding one of the ids does not match

    Args:
        referenced_ids (list[int]): The ids a reference row has to carry

    Returns:
        dict[str, Any]: The query condition on `fields`
    """
    return {
        CmdbObjectKey.FIELDS.value: {
            '$elemMatch': {
                CmdbObjectFieldKey.TYPE.value: {'$in': list(REFERENCE_FIELD_KINDS)},
                CmdbObjectFieldKey.VALUE.value: {'$in': referenced_ids},
            }
        }
    }


def build_term_join_stages(
        value_condition: dict[str, Any],
        acl_stages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Evaluates the same rule inside the database, for a term too broad for an id list

    Each candidate joins only the objects its own reference rows point at, and only those of them
    that match the term and pass the caller's ACL; one such object is enough, so the join stops at the
    first. The working field is removed again, so the documents leave the stages as they entered

    Args:
        value_condition (dict[str, Any]): The term's match on the own field values
        acl_stages (list[dict[str, Any]]): The caller's access-control stages; empty for none

    Returns:
        list[dict[str, Any]]: The join, the match and the clean-up stage
    """
    fields_path: str = f'${CmdbObjectKey.FIELDS.value}'
    reference_values: dict[str, Any] = {
        '$map': {
            'input': {
                '$filter': {
                    'input': {'$ifNull': [fields_path, []]},
                    'cond': {'$in': [f'$$this.{CmdbObjectFieldKey.TYPE.value}', list(REFERENCE_FIELD_KINDS)]},
                }
            },
            'in': f'$$this.{CmdbObjectFieldKey.VALUE.value}',
        }
    }

    return [
        Builder.correlated_lookup_(
            CmdbObject.COLLECTION,
            {'references': reference_values},
            [
                Builder.match_({'$expr': {'$in': [f'${CmdbObjectKey.PUBLIC_ID.value}', '$$references']}}),
                Builder.match_(value_condition),
                *acl_stages,
                Builder.limit_(1),
                Builder.project_({'_id': 1}),
            ],
            REFERENCED_MATCH_FIELD,
        ),
        Builder.match_(Builder.or_([value_condition, {REFERENCED_MATCH_FIELD: {'$ne': []}}])),
        Builder.unset_([REFERENCED_MATCH_FIELD]),
    ]


def build_text_term_stages(
        objects_manager: 'ObjectsManager',
        value_condition: dict[str, Any],
        acl_stages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Builds the stages keeping only the objects one search term finds, itself or through a reference

    Args:
        objects_manager (ObjectsManager): Runs the query collecting the matching referenced objects
        value_condition (dict[str, Any]): The term's match on the own field values
        acl_stages (list[dict[str, Any]]): The caller's access-control stages; empty for none

    Returns:
        list[dict[str, Any]]: One `$match` - or, for a term too broad for an id list, the join stages
    """
    referenced_ids: list[int] | None = collect_referenced_match_ids(
        objects_manager, value_condition, acl_stages, MAX_REFERENCED_MATCH_IDS,
    )

    if referenced_ids is None:
        return build_term_join_stages(value_condition, acl_stages)

    if not referenced_ids:
        return [Builder.match_(value_condition)]

    return [Builder.match_(Builder.or_([value_condition, build_reference_rows_condition(referenced_ids)]))]
