# DATAGERRY - OpenSource Enterprise CMDB
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
Which CmdbObjects are free to be mounted into a Rack, and how they are shown in the picker

Two rules decide it, and both are exclusions rather than a positive marker - anything that is not
excluded can be mounted:

  1. **a Rack is not mountable** - Racks do not nest, so every object of a RACK-marked CmdbType is out
  2. **an object belongs to at most one Rack** - so anything already held by a mount is out, whether it
     is placed in that rack or merely a member of it

Neither rule depends on WHICH rack is being filled: the answer is the same for every rack, and the rack
id in the route exists to validate the request, not to narrow the result.

Pure: the reads happen in the route, their results are passed in, so the filter construction and the row
projection are unit-testable without a database. The exclusions are appended as '$match' stages onto the
caller's own ``?filter=``, so a caller-supplied filter still applies and can not widen the result past
the two rules
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey

from cmdb.framework.rack.rack_constants import RackOverviewKey
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

def build_assignable_criteria(rack_type_ids: list[int], mounted_object_ids: list[int]) -> dict[str, Any]:
    """
    Builds the criteria that keep only the CmdbObjects free to be mounted

    Each half is omitted when it would exclude nothing, so an installation with no rack type and no
    mounts produces an empty criteria dict rather than two '$nin' stages against empty lists

    Args:
        rack_type_ids (list[int]): public_ids of the CmdbTypes carrying the RACK marker
        mounted_object_ids (list[int]): public_ids of the CmdbObjects already held by a mount

    Returns:
        dict[str, Any]: The Mongo criteria, empty when nothing has to be excluded
    """
    criteria: dict[str, Any] = {}

    if rack_type_ids:
        criteria[CmdbObjectKey.TYPE_ID.value] = {'$nin': rack_type_ids}

    if mounted_object_ids:
        criteria[CmdbObjectKey.PUBLIC_ID.value] = {'$nin': mounted_object_ids}

    return criteria


def append_criteria_to_filter(
        request_filter: dict[str, Any] | list[dict[str, Any]] | None,
        criteria: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Appends the assignable criteria to the caller's ``?filter=`` as a further pipeline stage

    The same technique the objects route uses for its active-objects filter: a dict filter becomes a
    single '$match' stage and the exclusions are appended after it, so the caller's filter narrows the
    result and the exclusions narrow it further. Appending rather than merging means a caller can not
    overwrite an exclusion by naming the same key

    Args:
        request_filter (dict[str, Any] | list[dict[str, Any]] | None): The parsed ``?filter=``, either a
            criteria dict or an aggregation pipeline
        criteria (dict[str, Any]): The assignable criteria from build_assignable_criteria

    Returns:
        list[dict[str, Any]]: The pipeline to hand to the query builder
    """
    if isinstance(request_filter, list):
        pipeline: list[dict[str, Any]] = list(request_filter)
    elif request_filter:
        pipeline = [{'$match': request_filter}]
    else:
        pipeline = []

    if criteria:
        pipeline.append({'$match': criteria})

    return pipeline


def build_assignable_row(
        object_doc: dict[str, Any],
        summary_lines: dict[int, str],
        type_meta: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """
    Projects one candidate object into the row the rack picker draws

    Deliberately the same keys a mount row carries, so the frontend has one shape for "an object I could
    mount" and "an object I have mounted". An object whose type no longer resolves keeps its row with
    null type metadata rather than being dropped - it is still assignable, and hiding it would offer no
    way to notice the broken type

    Args:
        object_doc (dict[str, Any]): The candidate CmdbObject document
        summary_lines (dict[int, str]): {object_id: summary_line}, batch-resolved
        type_meta (dict[int, dict[str, Any]]): {type_id: metadata}, batch-resolved

    Returns:
        dict[str, Any]: The picker row
    """
    object_id: Any = object_doc.get(CmdbObjectKey.PUBLIC_ID.value)
    type_id: Any = object_doc.get(CmdbObjectKey.TYPE_ID.value)
    meta: dict[str, Any] = type_meta.get(type_id, {}) if isinstance(type_id, int) else {}

    return {
        RackOverviewKey.PUBLIC_ID.value: object_id,
        RackOverviewKey.SUMMARY_LINE.value: summary_lines.get(object_id),
        RackOverviewKey.TYPE_ID.value: type_id,
        RackOverviewKey.TYPE_LABEL.value: meta.get(RackOverviewKey.TYPE_LABEL.value),
        RackOverviewKey.TYPE_ICON.value: meta.get(RackOverviewKey.TYPE_ICON.value),
        RackOverviewKey.TYPE_COLOR.value: meta.get(RackOverviewKey.TYPE_COLOR.value),
    }


def build_assignable_rows(
        object_docs: list[dict[str, Any]],
        summary_lines: dict[int, str],
        type_meta: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Projects a whole page of candidates, preserving the order the database returned

    The order is the caller's ``?sort=`` / ``?order=``, applied by the aggregation, so it is not
    re-sorted here

    Args:
        object_docs (list[dict[str, Any]]): The candidate CmdbObject documents of one page
        summary_lines (dict[int, str]): {object_id: summary_line}, batch-resolved
        type_meta (dict[int, dict[str, Any]]): {type_id: metadata}, batch-resolved

    Returns:
        list[dict[str, Any]]: One row per document, in input order
    """
    return [build_assignable_row(doc, summary_lines, type_meta) for doc in object_docs]
