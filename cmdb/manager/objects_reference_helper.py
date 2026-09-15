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
matches in the database, while a reference inside a multi-data-section row does not - the MDS candidates
come back from a broader query and have to be filtered in memory, row by row. `references()` therefore
runs both and merges them, which is what these functions do.

**Everything here is pure, and deliberately so** - the same division `types_mds_helper` draws: the
manager owns the reads (the ref-field names per type, the two queries) and passes their results in, so
deciding whether a row references an object, and merging the two result sets, can be read and tested
without a database.
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.models.object_model.cmdb_object import CmdbObject
from cmdb.models.object_model import (
    CmdbObjectKey,
    CmdbObjectFieldKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
)
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.section_type_enum import SectionType
from cmdb.framework.results import IterationResult

from cmdb.errors.manager.objects_manager import ObjectsManagerMdsReferencesError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

def mds_rows_reference(result: dict, ref_field_names: set[str], referenced_public_id: int) -> bool:
    """
    Reports whether any MDS row of the object holds a ref field pointing at the given id

    Args:
        result (dict): A CmdbObject document carrying multi_data_sections
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


# The reference query exposes the full pagination/sort surface (limit/skip/sort/order) plus the
# target object and the ACL user/permission - eight, which is exactly what pylint allows, so the


def filter_mds_results_referencing(
        results: list[dict],
        referenced_public_id: int,
        ref_field_names_by_type: dict[int, set[str]],
) -> list[dict]:
    """
    Keeps only the result objects whose MDS rows reference the given object via a ref field

    Args:
        results (list[dict]): Candidate CmdbObject documents (must carry multi_data_sections)
        referenced_public_id (int): public_id the MDS ref field must point at
        ref_field_names_by_type (dict[int, set[str]]): {type_id: ref-field names}, resolved by the
            manager in ONE read - which is what keeps this a per-row decision rather than a per-row
            type fetch

    Returns:
        list[dict]: The subset of results that reference the given object in their MDS data
    """
    matching_results: list[dict] = []

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


def merge_mds_references(
        mds_result: list,
        obj_result: IterationResult,
        limit: int,
        skip: int,
        sort: str,
        order: int,
) -> IterationResult:
    """
    Merges MDS references into the existing object result set while ensuring uniqueness.
    The merged results are sorted and paginated as per the given parameters

    Args:
        mds_result (list[dict]): List of multi-data section references
        obj_result (IterationResult): Existing objects retrieved via normal references
        limit (int): Maximum number of objects to return (0 for no limit)
        skip (int): Number of objects to skip (for pagination)
        sort (str): Attribute name to sort by
        order (int): Sorting order (-1 for descending, 1 for ascending)

    Raises:
        ObjectsManagerMdsReferencesError: If the merge of references failed

    Returns:
        IterationResult: Merged, sorted, and paginated result set
    """
    try:
        # get public_id's of all currently referenced objects as a set
        referenced_ids = {obj.public_id for obj in obj_result.results}

        # add MDS objects to normal references if they are not already referenced
        for ref_obj in mds_result:
            new_obj = CmdbObject.from_data(ref_obj)
            if new_obj.public_id not in referenced_ids:
                obj_result.results.append(new_obj)
                referenced_ids.add(new_obj.public_id)

        obj_result.total = len(obj_result.results)

        # sort all findings according to sort and order. The key wraps the value in a
        # (is-None, value) tuple so objects whose sort attribute is missing/None sort
        # consistently to one end instead of raising a TypeError on a None-vs-value
        # comparison (Python 3); objects that DO carry the attribute keep their natural order
        descending_order = order == -1

        def _sort_key(obj: CmdbObject) -> tuple[bool, Any]:
            value: Any = getattr(obj, sort, None)
            return (value is None, value)

        obj_result.results.sort(key=_sort_key, reverse=descending_order)

        # just keep the given limit of objects if limit > 0
        if limit > 0:
            list_length = limit + skip

            # if the list_length is longer than the object_list then just set it to len(object_list)
            list_length = min(list_length, len(obj_result.results))

            obj_result.results = obj_result.results[skip:list_length]

        return obj_result
    except Exception as err:
        LOGGER.error("[merge_mds_references] Exception: %s, Type: %s", err, type(err))
        raise ObjectsManagerMdsReferencesError(err) from err
