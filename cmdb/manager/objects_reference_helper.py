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
Which CmdbObjects reference another one, and how the two answers are merged

An object can be referenced two ways and they are found by two different queries: a plain `ref` FIELD
matches in the database, while a reference inside a multi-data-section row is narrowed in the database to the
objects holding the referenced id in some row, and then confirmed in memory, row by row - the value has to sit in
a field of its Type that is a `ref` field. `references()` therefore runs both and merges them, which is what these
functions do.

**Both halves and the page are scoped alike**: the caller's denied Types (resolved once, by the manager) leave the
MDS half at its Type stage - their objects are never loaded - and narrow the page read as well, so no id that
reaches the page can answer an object the caller may not read. The caller's filter and search stages run on the
OBJECTS in both halves.

**Everything here is pure, and deliberately so**: the manager owns the reads (the ref-field names per
type, the two queries, the denied Types) and passes their results in, so deciding whether a row references an
object, and merging the two result sets, can be read and tested without a database.
"""
from typing import Any

from cmdb.models.object_model.cmdb_object import CmdbObject
from cmdb.models.object_model import (
    CmdbObjectKey,
    CmdbObjectFieldKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
)
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.section_type_enum import SectionType
from cmdb.models.type_model.cmdb_type import CmdbType
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.manager.query_builder import BaseQueryBuilder, BuilderParameters
from cmdb.manager.query_builder.query_builder_constants import SortPipeline
from cmdb.security.acl.builder import build_denied_types_condition
from cmdb.utils import Builder
# -------------------------------------------------------------------------------------------------------------------- #

# The reference lookup joins each object's CmdbType under this name and matches the referenced id in the field values
REFERENCE_TYPE_ALIAS: str = 'type'
REFERENCE_VALUE_PATH: str = f'{CmdbObjectKey.FIELDS.value}.{CmdbObjectFieldKey.VALUE.value}'

# The temporary flag a reference page sorts on first, so a missing or null sort value lands where the listing
# has always put it; projected away before the page is answered
SORT_MISSING_KEY: str = '_sort_value_missing'
ASCENDING: int = 1

# The MDS half joins each referencing Type's objects under this name, and narrows the join to the objects holding the
# referenced id in some row value
MDS_TYPE_OBJECTS_ALIAS: str = 'type_objects'
MDS_ROW_VALUE_PATH: str = '.'.join([
    CmdbObjectKey.MULTI_DATA_SECTIONS.value, CmdbObjectMdsKey.VALUES.value, CmdbObjectMdsRowKey.DATA.value,
    CmdbObjectFieldKey.VALUE.value,
])

# A sort key starting with this is an operator, not a field path, and a NUL character is no path at all
FIELD_PATH_OPERATOR_PREFIX: str = '$'
NUL_CHARACTER: str = '\x00'

# -------------------------------------------------------------------------------------------------------------------- #

def mds_rows_reference(result: dict[str, Any], ref_field_names: set[str], referenced_public_id: int) -> bool:
    """
    Reports whether any MDS row of the object holds a ref field pointing at the given id

    Args:
        result (dict[str, Any]): A CmdbObject document carrying multi_data_sections
        ref_field_names (set[str]): Names of the object type's 'ref'-type fields
        referenced_public_id (int): public_id the ref field must point at

    Returns:
        bool: True if any MDS ref field references the given object
    """
    for mds_entry in result.get(CmdbObjectKey.MULTI_DATA_SECTIONS.value, []):
        for value in mds_entry.get(CmdbObjectMdsKey.VALUES.value, []):
            for data_set in value.get(CmdbObjectMdsRowKey.DATA.value, []):
                if (
                    data_set.get(CmdbObjectFieldKey.NAME.value) in ref_field_names
                    and data_set.get(CmdbObjectFieldKey.VALUE.value) == referenced_public_id
                ):
                    return True

    return False


def as_stage_list(criteria: dict[str, Any] | list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """
    The caller's criteria as a list of pipeline stages

    Args:
        criteria (dict[str, Any] | list[dict[str, Any]] | None): One stage, a list of stages, or None for no filter;
            anything else contributes nothing

    Returns:
        list[dict[str, Any]]: A new list of the stages
    """
    if isinstance(criteria, dict):
        return [criteria]

    if isinstance(criteria, list):
        return list(criteria)

    return []


def build_mds_reference_pipeline(
        referenced_object: CmdbObject,
        criteria: dict[str, Any] | list[dict[str, Any]] | None,
        denied_type_ids: list[int],
) -> list[dict[str, Any]]:
    """
    The aggregation on ``framework.types`` finding the objects whose MDS rows may reference ``referenced_object``

    The Types with a ``ref`` field naming the referenced Type are kept - minus the caller's denied Types, so their
    objects are never loaded - and each one's objects are joined, narrowed in the join to those holding the
    referenced public_id in some MDS row value. The caller's stages then run on those OBJECTS, as they do in the
    field half. The candidates still have to be confirmed row by row (``filter_mds_results_referencing``): the
    value has to sit in a field of the object's Type that is a ``ref`` field

    Args:
        referenced_object (CmdbObject): The object being referenced
        criteria (dict[str, Any] | list[dict[str, Any]] | None): The caller's filter / search stages, for objects
        denied_type_ids (list[int]): public_ids of the CmdbTypes the caller may not read; empty narrows nothing

    Returns:
        list[dict[str, Any]]: The aggregation stages, answering CmdbObject documents without ``_id``
    """
    referencing_types: list[dict[str, Any]] = [
        {f'{TypeSchemaKey.FIELDS.value}.{FieldKey.TYPE.value}': FieldType.REFERENCE.value},
        {f'{TypeSchemaKey.FIELDS.value}.{FieldKey.REF_TYPES.value}': referenced_object.type_id},
    ]

    if denied_type_ids:
        # The stage runs on the Types themselves, so the denied ids are matched on their own public_id
        referencing_types.append({TypeSchemaKey.PUBLIC_ID.value: {'$nin': denied_type_ids}})

    return [
        Builder.match_(Builder.and_(referencing_types)),
        Builder.project_({TypeSchemaKey.PUBLIC_ID.value: 1, '_id': 0}),
        Builder.lookup_(from_collection=CmdbObject.COLLECTION,
                        local_field=TypeSchemaKey.PUBLIC_ID.value,
                        foreign_field=CmdbObjectKey.TYPE_ID.value,
                        as_field=MDS_TYPE_OBJECTS_ALIAS,
                        pipeline=[Builder.match_({MDS_ROW_VALUE_PATH: referenced_object.public_id})]),
        Builder.unwind_({'path': f'${MDS_TYPE_OBJECTS_ALIAS}'}),
        Builder.replace_root_(f'${MDS_TYPE_OBJECTS_ALIAS}'),
        *as_stage_list(criteria),
        Builder.project_({'_id': 0}),
    ]


def filter_mds_results_referencing(
        results: list[dict[str, Any]],
        referenced_public_id: int,
        ref_field_names_by_type: dict[int, set[str]],
) -> list[dict[str, Any]]:
    """
    Keeps only the result objects whose MDS rows reference the given object via a ref field

    Args:
        results (list[dict[str, Any]]): Candidate CmdbObject documents (must carry multi_data_sections)
        referenced_public_id (int): public_id the MDS ref field must point at
        ref_field_names_by_type (dict[int, set[str]]): {type_id: ref-field names}, resolved by the
            manager in ONE read - which is what keeps this a per-row decision rather than a per-row
            type fetch

    Returns:
        list[dict[str, Any]]: The subset of results that reference the given object in their MDS data
    """
    matching_results: list[dict[str, Any]] = []

    for result in results:
        ref_field_names: set[str] = ref_field_names_by_type.get(result.get(CmdbObjectKey.TYPE_ID.value), set())

        if mds_rows_reference(result, ref_field_names, referenced_public_id):
            matching_results.append(result)

    return matching_results


def build_reference_match_queries(object_: CmdbObject) -> list[dict[str, Any]]:
    """
    Builds the field-based and section-based reference match queries for ``references()``

    Both match against the joined 'type' document. ref_types is always a list of integer type
    public_ids, so an exact match is correct (the former substring-regex alternative never
    matched a numeric field anyway)

    Args:
        object_ (CmdbObject): The object whose referencing objects are being searched

    Returns:
        list[dict[str, Any]]: The field-ref and section-ref match queries, for an `$or`
    """
    field_ref_query: dict[str, Any] = {
        'type.fields.type': FieldType.REFERENCE.value,
        'type.fields.ref_types': object_.type_id,
    }

    section_ref_query: dict[str, Any] = {
        'type.render_meta.sections.type': SectionType.REF_SECTION.value,
        'type.render_meta.sections.reference.type_id': object_.type_id,
    }

    return [field_ref_query, section_ref_query]


def merge_reference_ids(field_ref_rows: list[dict[str, Any]], mds_rows: list[dict[str, Any]]) -> list[int]:
    """
    The public_ids of every referencing CmdbObject, the field references first and each id once

    Args:
        field_ref_rows (list[dict[str, Any]]): The rows of the ref-field query, carrying at least the public_id
        mds_rows (list[dict[str, Any]]): The CmdbObject documents whose MDS rows reference the object

    Returns:
        list[int]: The distinct public_ids, in the order they were first seen; a row without an integer
            public_id is skipped, since it names no object a page could hold
    """
    referenced_ids: dict[int, None] = {}

    for row in [*field_ref_rows, *mds_rows]:
        public_id: Any = row.get(CmdbObjectKey.PUBLIC_ID.value)

        if isinstance(public_id, int) and not isinstance(public_id, bool):
            referenced_ids[public_id] = None

    return list(referenced_ids)


def is_sortable_path(sort: str) -> bool:
    """
    Whether a client's sort key can be handed to MongoDB as a field path

    Args:
        sort (str): The requested sort key

    Returns:
        bool: True for a non-empty path that is no operator and holds no NUL character
    """
    return bool(sort) and not sort.startswith(FIELD_PATH_OPERATOR_PREFIX) and NUL_CHARACTER not in sort


def build_reference_page_criteria(public_ids: list[int], denied_type_ids: list[int]) -> dict[str, Any]:
    """
    The criteria of the page read: the referencing ids, minus the objects of the caller's denied Types

    The ids come from reads that are scoped themselves; the page read asks again, so an id that reached the merge any
    other way can still not answer an object the caller may not read

    Args:
        public_ids (list[int]): Every referencing CmdbObject
        denied_type_ids (list[int]): public_ids of the CmdbTypes the caller may not read; empty narrows nothing

    Returns:
        dict[str, Any]: The filter document
    """
    criteria: dict[str, Any] = Builder.in_(CmdbObjectKey.PUBLIC_ID.value, public_ids)

    if not denied_type_ids:
        return criteria

    return Builder.and_([criteria, build_denied_types_condition(denied_type_ids)])


def build_reference_page_stages(
        public_ids: list[int],
        limit: int,
        skip: int,
        sort: str,
        order: int,
        denied_type_ids: list[int] | None = None,
) -> list[dict[str, Any]]:
    """
    The aggregation answering one page of the referencing CmdbObjects, sorted and paged in the database

    The order is the reference listing's: by the sort key, a document missing it - or holding null - at the END
    of an ascending page and at the START of a descending one, and equal keys by public_id ascending. MongoDB
    alone would put the nulls the other way round, which is what the ``SORT_MISSING_KEY`` flag sorted first
    corrects. A ``limit`` of 0 answers every row and ignores ``skip``, as the listing always has.

    Args:
        public_ids (list[int]): Every referencing CmdbObject
        limit (int): Page size, 0 for every row
        skip (int): Rows passed over first; only applied together with a limit
        sort (str): The sort key; one that is no usable field path sorts by public_id
        order (int): 1 ascending, -1 descending
        denied_type_ids (list[int] | None): public_ids of the CmdbTypes the caller may not read; None or empty
            narrows nothing

    Returns:
        list[dict[str, Any]]: The stages, ending in the page's CmdbObject documents
    """
    sort_key: str = sort if is_sortable_path(sort) else CmdbObjectKey.PUBLIC_ID.value
    sort_specification: dict[str, int] = {SORT_MISSING_KEY: order, sort_key: order}

    if sort_key != CmdbObjectKey.PUBLIC_ID.value:
        sort_specification[CmdbObjectKey.PUBLIC_ID.value] = ASCENDING

    stages: list[dict[str, Any]] = [
        Builder.match_(build_reference_page_criteria(public_ids, denied_type_ids or [])),
        Builder.add_fields_({SORT_MISSING_KEY: {'$eq': [{'$ifNull': [f'${sort_key}', None]}, None]}}),
        Builder.sort_(sort_specification),
    ]

    if limit > 0:
        stages.extend([Builder.skip_(skip), Builder.limit_(limit)])

    stages.append(Builder.project_({SORT_MISSING_KEY: 0, '_id': 0}))

    return stages


def build_reference_id_criteria(
        object_: CmdbObject,
        criteria: dict[str, Any] | list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """
    The criteria of the field-reference read: the caller's stages, then the objects pointing at ``object_``

    Each candidate's CmdbType is joined, kept when a ref field or a ref-section of it names the referenced type, and
    the candidate kept when one of its field values is the referenced public_id

    Args:
        object_ (CmdbObject): The object whose referencing objects are searched
        criteria (dict[str, Any] | list[dict[str, Any]] | None): One stage, a list of stages, or None for no filter

    Returns:
        list[dict[str, Any]]: The criteria stages
    """
    query: list[dict[str, Any]] = as_stage_list(criteria)

    query.append(Builder.lookup_(from_collection=CmdbType.COLLECTION,
                                 local_field=CmdbObjectKey.TYPE_ID.value,
                                 foreign_field=CmdbObjectKey.PUBLIC_ID.value,
                                 as_field=REFERENCE_TYPE_ALIAS))
    query.append(Builder.unwind_({'path': f'${REFERENCE_TYPE_ALIAS}', 'preserveNullAndEmptyArrays': True}))
    query.append(Builder.match_(Builder.or_(build_reference_match_queries(object_))))
    query.append(Builder.match_({REFERENCE_VALUE_PATH: object_.public_id}))

    return query


def build_reference_page_query(
        query_builder: BaseQueryBuilder,
        public_ids: list[int],
        limit: int,
        skip: int,
        sort: str,
        order: int,
        denied_type_ids: list[int] | None = None,
) -> list[dict[str, Any]]:
    """
    The aggregation reading one page of the referencing CmdbObjects

    A ``fields.<name>`` key sorts by that field's value exactly as the object listing does (the query builder's
    sort); every other key by ``build_reference_page_stages``

    Args:
        query_builder (BaseQueryBuilder): The manager's query builder, for the field-value sort
        public_ids (list[int]): Every referencing CmdbObject
        limit (int): Page size, 0 for every row
        skip (int): Rows passed over first; only applied together with a limit
        sort (str): The sort key
        order (int): 1 ascending, -1 descending
        denied_type_ids (list[int] | None): public_ids of the CmdbTypes the caller may not read; None or empty
            narrows nothing

    Returns:
        list[dict[str, Any]]: The aggregation stages
    """
    if not sort.startswith(SortPipeline.FIELDS_PREFIX):
        return build_reference_page_stages(public_ids, limit, skip, sort, order, denied_type_ids)

    return query_builder.build(BuilderParameters(
        criteria=build_reference_page_criteria(public_ids, denied_type_ids or []),
        limit=limit,
        skip=skip if limit > 0 else 0,
        sort=sort,
        order=order,
    ))
