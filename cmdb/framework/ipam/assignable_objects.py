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
Lists CmdbObjects that can carry a dg-ipam-interface MDS row

A CmdbType is 'IPAM capable' when its schema includes the dg-ipam-interface multi-data section
template, i.e. one ``render_meta.sections`` entry with ``name == IpamSection.INTERFACE``. Any
CmdbObject of such a type can hold one or more interface rows pointing at a SUBNET and an IP,
so the subnet IP-Übersicht FE uses this listing as the picker for 'assign an object to a free
IP'. A CmdbObject is never 'consumed' by an assignment - the same object can carry several
interface rows referencing different subnets - so the list is intentionally unfiltered by
existing assignments and returns every assignable candidate in the tenant
"""
from typing import Any

from cmdb.manager import ObjectsManager, TypesManager
from cmdb.models.object_model import CmdbObjectKey
from cmdb.models.special_type_model.ipam_constants import (
    IpamOverviewKey,
    IpamSection,
)
from cmdb.framework.ipam.pagination import clamp_page
from cmdb.framework.ipam.search import active_search
# -------------------------------------------------------------------------------------------------------------------- #


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  PURE HELPERS                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def find_ipam_capable_type_ids(types_manager: TypesManager) -> list[int]:
    """
    Returns the public_ids of every CmdbType whose schema contains the dg-ipam-interface section

    Issues one Mongo find against the types collection with an ``$elemMatch`` on
    ``render_meta.sections`` matching the IPAM interface section name. Types whose schema
    cannot be deserialized are dropped by the underlying ``find_types`` call; their absence
    here simply means objects of those types will not appear in the assignable picker until
    the type document is repaired

    Args:
        types_manager (TypesManager): db interface for CmdbTypes

    Returns:
        list[int]: Distinct public_ids of IPAM-capable CmdbTypes, in the order returned by the
            database; empty when no type carries the interface section
    """
    criteria: dict[str, Any] = {
        'render_meta.sections': {
            '$elemMatch': {'name': IpamSection.INTERFACE},
        },
    }

    return [cmdb_type.public_id for cmdb_type in types_manager.find_types(criteria)]


def _build_type_label_lookup(
    types_manager: TypesManager,
    type_ids: list[int],
) -> dict[int, str]:
    """
    Bulk-resolves a list of CmdbType public_ids to their human-readable label

    A single ``get_types_lookup`` round-trip; the projection happens client-side so callers can
    answer per-row label queries without further DB work. Types whose document no longer
    resolves are absent from the mapping - callers should treat a missing key as 'unknown
    label' and fall back to a placeholder if needed

    Args:
        types_manager (TypesManager): db interface for CmdbTypes
        type_ids (list[int]): The CmdbType public_ids to resolve (duplicates allowed)

    Returns:
        dict[int, str]: {type_id: label} for every type that resolved successfully
    """
    if not type_ids:
        return {}

    lookup = types_manager.get_types_lookup(list(set(type_ids)))

    return {tid: t.label for tid, t in lookup.items()}


def _build_row(
    object_doc: dict[str, Any],
    summary_lines: dict[int, str],
    type_labels: dict[int, str],
) -> dict[str, Any]:
    """
    Shapes one assignable-object row from a CmdbObject document and the bulk lookups

    The row carries the minimum the FE needs to render a selection dropdown: the object's
    public_id, its rendered summary line, and a small ``type_info`` sub-dict echoing the
    type id and label so the FE can group / colour entries by type without a second round-
    trip. Missing summary lines fall back to the empty string (objects whose owner type no
    longer resolves) and missing type labels fall back to the empty string in the same
    spirit; the FE renders both as 'unknown' placeholders

    Args:
        object_doc (dict[str, Any]): The CmdbObject document (as_dict=True shape)
        summary_lines (dict[int, str]): {object_public_id: summary_line} produced by
            ``ObjectsManager.get_summary_lines_lookup``
        type_labels (dict[int, str]): {type_id: label} produced by ``_build_type_label_lookup``

    Returns:
        dict[str, Any]: {'public_id', 'type_info': {'public_id', 'label'}, 'summary_line'}
    """
    public_id: Any = object_doc.get(CmdbObjectKey.PUBLIC_ID)
    type_id: Any = object_doc.get(CmdbObjectKey.TYPE_ID)

    return {
        CmdbObjectKey.PUBLIC_ID: public_id,
        IpamOverviewKey.TYPE_INFO: {
            CmdbObjectKey.PUBLIC_ID: type_id,
            IpamOverviewKey.LABEL: type_labels.get(type_id, ''),
        },
        IpamOverviewKey.SUMMARY_LINE: summary_lines.get(public_id, ''),
    }


def _apply_search(
    rows: list[dict[str, Any]],
    needle: str | None,
) -> list[dict[str, Any]]:
    """
    Narrows the row list to entries whose summary line carries the search needle

    The match is case-insensitive and substring-based, mirroring the search semantics of the
    subnet IP-Übersicht route. ``needle`` is the already-normalized query produced by
    ``active_search`` - when None the helper returns ``rows`` unchanged. Rows with an empty
    summary line never match an active needle, so objects whose owner-type / summary fell
    out of resolution drop out of the search results regardless of the query

    Args:
        rows (list[dict[str, Any]]): Assignable-object rows produced by ``_build_row``
        needle (str | None): Normalized search query, or None to skip the filter

    Returns:
        list[dict[str, Any]]: The filtered row list, in input order
    """
    if needle is None:
        return rows

    lowered: str = needle.lower()

    return [row for row in rows if lowered in row[IpamOverviewKey.SUMMARY_LINE].lower()]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  DATASET LOADER                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def _load_assignable_rows(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    capable_type_ids: list[int],
) -> list[dict[str, Any]]:
    """
    Loads every assignable CmdbObject and shapes the per-row picker payload

    One ``find_objects`` round-trip over ``type_id ∈ capable_type_ids``, followed by two bulk
    lookups (summary lines keyed by object public_id, type labels keyed by type id). The type-
    label lookup is scoped to the type ids actually present on the loaded objects rather than
    every capable type so a tenant with many IPAM-capable types but few objects of them does
    not pay for unused lookups

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        capable_type_ids (list[int]): public_ids of every IPAM-capable CmdbType; assumed
            non-empty (callers short-circuit on the empty case before reaching this helper)

    Returns:
        list[dict[str, Any]]: One row per object, in ``find_objects`` order; each row is
            {'public_id', 'type_info': {'public_id', 'label'}, 'summary_line'}
    """
    objects: list[dict[str, Any]] = objects_manager.find_objects(
        {CmdbObjectKey.TYPE_ID: {'$in': capable_type_ids}},
        as_dict=True,
    )

    object_ids: list[int] = [
        obj[CmdbObjectKey.PUBLIC_ID]
        for obj in objects
        if isinstance(obj.get(CmdbObjectKey.PUBLIC_ID), int)
    ]
    present_type_ids: list[int] = [
        obj[CmdbObjectKey.TYPE_ID]
        for obj in objects
        if isinstance(obj.get(CmdbObjectKey.TYPE_ID), int)
    ]

    summary_lines: dict[int, str] = (
        objects_manager.get_summary_lines_lookup(object_ids, with_type=True)
        if object_ids else {}
    )
    type_labels: dict[int, str] = _build_type_label_lookup(types_manager, present_type_ids)

    return [_build_row(obj, summary_lines, type_labels) for obj in objects]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   ORCHESTRATOR                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def build_assignable_objects_page(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    *,
    page: int,
    page_size: int,
    search: str,
) -> dict[str, Any]:
    """
    Builds the paginated assignable-objects payload for the subnet IP-Übersicht picker

    Steps:
      1. Resolve every IPAM-capable CmdbType via ``find_ipam_capable_type_ids``. With no
         capable type the response collapses to an empty page envelope before any object
         lookup is issued
      2. Load every CmdbObject of a capable type and shape it into a picker row via
         ``_load_assignable_rows`` (one ``find_objects`` + two bulk lookups inside)
      3. Apply the case-insensitive substring filter against the summary line (skipped when
         the normalized query is shorter than IpamSearch.MIN_QUERY_LENGTH)
      4. Compute the post-filter total, clamp the requested page/page_size into the valid
         range via ``clamp_page``, and slice the page out of the filtered row list

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        page (int): Requested 1-based page number; clamped server-side
        page_size (int): Requested page size; clamped into [IpamPagination.MIN_PAGE_SIZE,
            IpamPagination.MAX_PAGE_SIZE]
        search (str): Raw search query; whitespace is stripped and queries shorter than
            IpamSearch.MIN_QUERY_LENGTH are ignored. The MAX_QUERY_LENGTH truncation is the
            route's responsibility

    Returns:
        dict[str, Any]: {'page', 'page_size', 'total', 'search', 'rows': [...]} where each row
            is {'public_id', 'type_info': {'public_id', 'label'}, 'summary_line'} and 'total'
            is the count after the search filter, not the unfiltered count
    """
    capable_type_ids: list[int] = find_ipam_capable_type_ids(types_manager)

    if not capable_type_ids:
        clamped_page, clamped_size = clamp_page(page, page_size, 0)

        return {
            IpamOverviewKey.PAGE: clamped_page,
            IpamOverviewKey.PAGE_SIZE: clamped_size,
            IpamOverviewKey.TOTAL: 0,
            IpamOverviewKey.SEARCH: search,
            IpamOverviewKey.ROWS: [],
        }

    rows: list[dict[str, Any]] = _load_assignable_rows(
        objects_manager, types_manager, capable_type_ids,
    )
    filtered: list[dict[str, Any]] = _apply_search(rows, active_search(search))

    total: int = len(filtered)
    clamped_page, clamped_size = clamp_page(page, page_size, total)
    start_offset: int = (clamped_page - 1) * clamped_size

    return {
        IpamOverviewKey.PAGE: clamped_page,
        IpamOverviewKey.PAGE_SIZE: clamped_size,
        IpamOverviewKey.TOTAL: total,
        IpamOverviewKey.SEARCH: search,
        IpamOverviewKey.ROWS: filtered[start_offset:start_offset + clamped_size],
    }
