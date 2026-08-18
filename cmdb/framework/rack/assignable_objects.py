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
Which CmdbObjects can be mounted into a Rack, and how they are shown in the picker

One positive marker and two exclusions decide it:

  1. **the type must carry a location field** - a rack member is mirrored into the location tree under
     its rack, and the object's own location field is what records that, so a type without one can not
     be a member at all
  2. **a Rack is not mountable** - Racks do not nest, so every object of a RACK-marked CmdbType is out.
     This is NOT covered by rule 1: the Rack type has a location field of its own
  3. **an object already in THIS rack is out** - it can not be added to the rack it is already in

An object held by a DIFFERENT rack is deliberately kept: it is offered with a hint naming that rack, and
mounting it moves it. So the answer does depend on which rack is being filled, and the rack id in the
route narrows the result rather than only validating the request.

Pure: the reads happen in the route, their results are passed in, so the filter construction and the row
projection are unit-testable without a database. The rules are appended as '$match' stages onto the
caller's own ``?filter=``, so a caller-supplied filter still applies and can not widen the result past
them
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey

from cmdb.framework.rack.rack_constants import RackOverviewKey
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

def build_assignable_criteria(
        location_field_type_ids: list[int],
        rack_type_ids: list[int],
        excluded_object_ids: list[int]) -> dict[str, Any]:
    """
    Builds the criteria that keep only the CmdbObjects which may be mounted

    The type marker is always applied, including when the list is empty: an installation where no type
    declares a location field has nothing that may be mounted, so '$in': [] matching nothing is the
    right answer rather than a rule to skip. The two exclusions are omitted when they would exclude
    nothing, so a rack holding nothing does not get a '$nin' against an empty list

    Args:
        location_field_type_ids (list[int]): public_ids of the CmdbTypes declaring a location field
        rack_type_ids (list[int]): public_ids of the CmdbTypes carrying the RACK marker
        excluded_object_ids (list[int]): public_ids of the CmdbObjects to hide - the members of the rack
            being filled, or every mounted object when the caller asked for free objects only

    Returns:
        dict[str, Any]: The Mongo criteria
    """
    type_criteria: dict[str, Any] = {'$in': location_field_type_ids}

    if rack_type_ids:
        # Both operators sit in the same field expression: a type must declare a location field AND not
        # be the Rack type, which does declare one
        type_criteria['$nin'] = rack_type_ids

    criteria: dict[str, Any] = {CmdbObjectKey.TYPE_ID.value: type_criteria}

    if excluded_object_ids:
        criteria[CmdbObjectKey.PUBLIC_ID.value] = {'$nin': excluded_object_ids}

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
        type_meta: dict[int, dict[str, Any]],
        assigned_racks: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """
    Projects one candidate object into the row the rack picker draws

    The first six keys are deliberately the ones a mount row carries, so the frontend has one shape for
    "an object I could mount" and "an object I have mounted". The last two are the picker's own: they
    name the rack the candidate is currently in, and are null for an object that is in no rack. An
    object whose type no longer resolves keeps its row with null type metadata rather than being dropped
    - it is still assignable, and hiding it would offer no way to notice the broken type

    Args:
        object_doc (dict[str, Any]): The candidate CmdbObject document
        summary_lines (dict[int, str]): {object_id: summary_line}, batch-resolved
        type_meta (dict[int, dict[str, Any]]): {type_id: metadata}, batch-resolved
        assigned_racks (dict[int, dict[str, Any]]): {object_id: {public_id, display_name}} of the rack
            the object is currently in, batch-resolved; absent for a free object

    Returns:
        dict[str, Any]: The picker row
    """
    object_id: Any = object_doc.get(CmdbObjectKey.PUBLIC_ID.value)
    type_id: Any = object_doc.get(CmdbObjectKey.TYPE_ID.value)
    meta: dict[str, Any] = type_meta.get(type_id, {}) if isinstance(type_id, int) else {}
    assigned: dict[str, Any] = assigned_racks.get(object_id, {}) if isinstance(object_id, int) else {}

    return {
        RackOverviewKey.PUBLIC_ID.value: object_id,
        RackOverviewKey.SUMMARY_LINE.value: summary_lines.get(object_id),
        RackOverviewKey.TYPE_ID.value: type_id,
        RackOverviewKey.TYPE_LABEL.value: meta.get(RackOverviewKey.TYPE_LABEL.value),
        RackOverviewKey.TYPE_ICON.value: meta.get(RackOverviewKey.TYPE_ICON.value),
        RackOverviewKey.TYPE_COLOR.value: meta.get(RackOverviewKey.TYPE_COLOR.value),
        RackOverviewKey.ASSIGNED_RACK_ID.value: assigned.get(RackOverviewKey.PUBLIC_ID.value),
        RackOverviewKey.ASSIGNED_RACK_NAME.value: assigned.get(RackOverviewKey.DISPLAY_NAME.value),
    }


def build_assignable_rows(
        object_docs: list[dict[str, Any]],
        summary_lines: dict[int, str],
        type_meta: dict[int, dict[str, Any]],
        assigned_racks: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Projects a whole page of candidates, preserving the order the database returned

    The order is the caller's ``?sort=`` / ``?order=``, applied by the aggregation, so it is not
    re-sorted here

    Args:
        object_docs (list[dict[str, Any]]): The candidate CmdbObject documents of one page
        summary_lines (dict[int, str]): {object_id: summary_line}, batch-resolved
        type_meta (dict[int, dict[str, Any]]): {type_id: metadata}, batch-resolved
        assigned_racks (dict[int, dict[str, Any]]): {object_id: {public_id, display_name}} of the rack
            each candidate is currently in, batch-resolved

    Returns:
        list[dict[str, Any]]: One row per document, in input order
    """
    return [build_assignable_row(doc, summary_lines, type_meta, assigned_racks) for doc in object_docs]
