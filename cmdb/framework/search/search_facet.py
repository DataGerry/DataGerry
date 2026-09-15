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
The ``$facet`` stage that answers a whole object search in one aggregation

Three questions are asked of the same matched set, which is why they are one stage and not three
round trips: how many objects match (``metadata``), which ones belong on the requested page
(``data``), and how the matches distribute over the CmdbTypes (``group``, what the frontend's type
filter bar draws).

Two things about the shapes here are contracts rather than implementation:

* the **group entries are ready-made search parameters** - the Angular result bar reads a group's
  ``searchLabel`` / ``total`` and re-submits the entry as a TYPE tag, so its keys are
  ``SearchGroupKey`` and its ``searchForm`` is ``SearchFormType.TYPE``
* the **page branch owns the paging semantics**: a limit of 0 (or less) means *unlimited*, the
  convention every paginated route in this API uses, and MongoDB refuses a ``$limit: 0`` outright -
  so the stage is omitted rather than sent

Cost note: a ``$facet`` sub-pipeline runs over EVERY document the preceding stages matched, is capped
at 104 MB and cannot use an index after its first stage. That is why the group branch tallies by
``type_id`` FIRST and only then resolves the labels of the (few) types that survive: resolving a type
per matched object instead would look up 50,000 documents to produce a handful of rows

Pure: every function returns stages and reads nothing, so the pipeline is unit-testable without a
database. ``SearchPipelineBuilder`` (the manager-layer query builder) composes them with the search
criteria; the framework layer sits above the managers, so that import direction is the intended one
"""
from typing import Any

from cmdb.manager.query_builder.builder import Builder

from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.type_model import CmdbType, TypeSchemaKey

from cmdb.framework.search.search_constants import (
    SearchFacetKey,
    SearchFormType,
    SearchGroupKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'build_page_stages',
    'build_search_facet',
    'build_total_stages',
    'build_type_group_stages',
]

# The key MongoDB owns on every document, and the name of a $group's own bucket id
MONGO_ID_KEY: str = '_id'

# Pipeline-local alias the type lookup of the group branch writes its match into
TYPE_LOOKUP_FIELD: str = 'lookup_data'

# -------------------------------------------------------------------------------------------------------------------- #

def build_total_stages() -> list[dict[str, Any]]:
    """
    Builds the facet branch counting every matched CmdbObject

    Returns:
        list[dict[str, Any]]: The `metadata` branch, one `$count` stage
    """
    return [Builder.count_(SearchGroupKey.TOTAL.value)]


def build_page_stages(skip: int, limit: int) -> list[dict[str, Any]]:
    """
    Builds the facet branch carrying the requested page of matched CmdbObjects

    A limit of 0 or less means *unlimited* - the convention of every paginated route in this API -
    and is expressed by omitting the stage, because MongoDB refuses a `$limit: 0` and would fail the
    whole aggregation. A negative skip is clamped to 0 for the same reason

    Args:
        skip (int): Number of matches to skip; a negative value is treated as 0
        limit (int): Page size; 0 or less means every match

    Returns:
        list[dict[str, Any]]: The `data` branch, at most a `$skip` and a `$limit` stage
    """
    stages: list[dict[str, Any]] = []

    if skip > 0:
        stages.append(Builder.skip_(skip))

    if limit > 0:
        stages.append(Builder.limit_(limit))

    return stages


def build_type_group_stages() -> list[dict[str, Any]]:
    """
    Builds the facet branch tallying the matches per CmdbType

    Tallies first and resolves labels second: the `$group` reduces the matched set to one row per
    type, and only those rows are joined against the types collection. Doing it the other way round
    (a `$lookup` per matched object, then grouping) produces the identical output at the cost of one
    lookup per match.

    An object whose type no longer exists is dropped by the `$unwind`, as it was before: the entry
    exists to offer a filter, and a filter needs a label to show

    Returns:
        list[dict[str, Any]]: The `group` branch, ordered by the tally descending
    """
    return [
        Builder.group_(
            f"${CmdbObjectKey.TYPE_ID.value}",
            {SearchGroupKey.TOTAL.value: {'$sum': 1}},
        ),
        Builder.lookup_(
            CmdbType.COLLECTION,
            MONGO_ID_KEY,
            TypeSchemaKey.PUBLIC_ID.value,
            TYPE_LOOKUP_FIELD,
        ),
        Builder.unwind_(f"${TYPE_LOOKUP_FIELD}"),
        Builder.project_({
            MONGO_ID_KEY: 0,
            SearchGroupKey.SEARCH_TEXT.value: f"${TYPE_LOOKUP_FIELD}.{TypeSchemaKey.LABEL.value}",
            SearchGroupKey.SEARCH_FORM.value: SearchFormType.TYPE.value,
            SearchGroupKey.SEARCH_LABEL.value: f"${TYPE_LOOKUP_FIELD}.{TypeSchemaKey.LABEL.value}",
            SearchGroupKey.SETTINGS.value: {SearchGroupKey.TYPES.value: [f"${MONGO_ID_KEY}"]},
            SearchGroupKey.TOTAL.value: 1,
        }),
        Builder.sort_(SearchGroupKey.TOTAL.value, -1),
    ]


def build_search_facet(skip: int, limit: int) -> dict[str, Any]:
    """
    Builds the whole ``$facet`` stage of an object search

    Args:
        skip (int): Number of matches to skip; a negative value is treated as 0
        limit (int): Page size; 0 or less means every match

    Returns:
        dict[str, Any]: The `$facet` stage carrying all three branches
    """
    return Builder.facet_({
        SearchFacetKey.METADATA.value: build_total_stages(),
        SearchFacetKey.DATA.value: build_page_stages(skip, limit),
        SearchFacetKey.GROUP.value: build_type_group_stages(),
    })
