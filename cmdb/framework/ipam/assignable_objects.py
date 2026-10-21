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
existing assignments and lists every assignable candidate the caller may read.

**What is read.** A row needs an object's ``public_id``, its ``type_id`` and the ``fields`` its summary
line is composed of - nothing else (``ASSIGNABLE_OBJECT_PROJECTION``), so the interface rows themselves
(``multi_data_sections``, the large part of these objects) are never loaded. Without a search the page is
cut by MongoDB (a count for the total, then ``skip`` / ``limit``), so a request reads one page of
documents; with a search every candidate is read (projected), because the search matches the composed
summary line, which only exists after the read. **Both paths list in ``public_id`` order**
(``ASSIGNABLE_OBJECT_ORDER``), the order the rack picker asks for too: ``public_id`` is unique, so a page is the same
rows on every request and the pages together list every candidate exactly once - MongoDB's natural order guarantees
neither.
"""
from typing import Any

from cmdb.manager import ObjectsManager, TypesManager
from cmdb.manager.objects_summary_helper import compose_summary_line
from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.user_model import CmdbUser
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.models.object_model import CmdbObjectKey
from cmdb.models.type_model.section_key_enum import SectionKey
from cmdb.models.type_model.cmdb_type import CmdbType
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.models.special_type_model.ipam_constants import (
    IpamOverviewKey,
    IpamSection,
)
from cmdb.framework.ipam.pagination import clamp_page
from cmdb.framework.ipam.search import active_search
# -------------------------------------------------------------------------------------------------------------------- #

# The picker's order: by public_id, ascending - unique, so a total order and stable pages
ASSIGNABLE_OBJECT_ORDER: list[tuple[str, int]] = [(CmdbObjectKey.PUBLIC_ID.value, CmdbDAO.DAO_ASCENDING)]

# What a picker row is built from: the identity, the type, and the fields the summary line is composed of
ASSIGNABLE_OBJECT_PROJECTION: dict[str, int] = {
    CmdbObjectKey.PUBLIC_ID.value: 1,
    CmdbObjectKey.TYPE_ID.value: 1,
    CmdbObjectKey.FIELDS.value: 1,
}


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
    sections_path: str = f'{TypeSchemaKey.RENDER_META.value}.{TypeSchemaKey.SECTIONS.value}'
    criteria: dict[str, Any] = {
        sections_path: {
            '$elemMatch': {SectionKey.NAME: IpamSection.INTERFACE},
        },
    }

    return [cmdb_type.public_id for cmdb_type in types_manager.find_types(criteria)]


def build_summary_lines(object_docs: list[dict[str, Any]], types_lookup: dict[int, CmdbType]) -> dict[int, str]:
    """
    Composes the summary line of every given CmdbObject from an already-loaded type lookup

    The same line ``ObjectsManager.get_summary_lines_lookup`` answers (``compose_summary_line``, with the type
    label), without its own type query: the page's types are read once and serve the summary lines and the type
    labels alike. A doc without an integer public_id, or whose type did not resolve, gets no line

    Args:
        object_docs (list[dict[str, Any]]): CmdbObject documents carrying at least public_id, type_id and fields
        types_lookup (dict[int, CmdbType]): {type_id: CmdbType} covering the docs' types

    Returns:
        dict[int, str]: {object_public_id: summary_line}
    """
    lines: dict[int, str] = {}

    for doc in object_docs:
        public_id: Any = doc.get(CmdbObjectKey.PUBLIC_ID)
        object_type: CmdbType | None = types_lookup.get(doc.get(CmdbObjectKey.TYPE_ID))

        if isinstance(public_id, int) and object_type is not None:
            lines[public_id] = compose_summary_line(doc, object_type, with_type=True)

    return lines


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
def _shape_rows(
    types_manager: TypesManager,
    object_docs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Shapes the picker rows for already-loaded CmdbObject documents

    **One type query**: the types actually present on the given docs are read once
    (``get_types_lookup``), and that lookup serves both the summary lines (``build_summary_lines``) and the
    type labels - so a page costs one type read, and a tenant with many IPAM-capable types but few objects of
    them does not pay for unused types

    Args:
        types_manager (TypesManager): db interface for CmdbTypes
        object_docs (list[dict[str, Any]]): CmdbObject documents (``ASSIGNABLE_OBJECT_PROJECTION`` is enough)

    Returns:
        list[dict[str, Any]]: One row per doc, in input order; each row is
            {'public_id', 'type_info': {'public_id', 'label'}, 'summary_line'}
    """
    present_type_ids: list[int] = list({
        obj[CmdbObjectKey.TYPE_ID]
        for obj in object_docs
        if isinstance(obj.get(CmdbObjectKey.TYPE_ID), int)
    })

    types_lookup: dict[int, CmdbType] = types_manager.get_types_lookup(present_type_ids) if present_type_ids else {}
    summary_lines: dict[int, str] = build_summary_lines(object_docs, types_lookup)
    type_labels: dict[int, str] = {type_id: object_type.label for type_id, object_type in types_lookup.items()}

    return [_build_row(obj, summary_lines, type_labels) for obj in object_docs]


# A read page: the total it is a page of, the clamped page number and size, and its rows
PickerPage = tuple[int, int, int, list[dict[str, Any]]]


def read_unsearched_page(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    criteria: dict[str, Any],
    page: int,
    page_size: int,
    request_user: CmdbUser | None,
) -> PickerPage:
    """
    Reads one page of candidates without a search, cut by MongoDB

    A count for the total, then exactly the requested page (``skip`` / ``limit``, projected) - both through the
    caller's READ ACL, so the total counts what the pages show. In ``public_id`` order (``ASSIGNABLE_OBJECT_ORDER``)

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        criteria (dict[str, Any]): The candidate filter (the IPAM-capable types)
        page (int): Requested 1-based page number; clamped
        page_size (int): Requested page size; clamped
        request_user (CmdbUser | None): The caller, whose READ access scopes the count and the page

    Returns:
        PickerPage: (total, clamped page, clamped page size, the page's rows)
    """
    total: int = objects_manager.count_objects(criteria, user=request_user, permission=AccessControlPermission.READ)
    clamped_page, clamped_size = clamp_page(page, page_size, total)
    page_docs: list[dict[str, Any]] = objects_manager.find_objects(
        criteria,
        as_dict=True,
        projection=ASSIGNABLE_OBJECT_PROJECTION,
        user=request_user,
        permission=AccessControlPermission.READ,
        sort=ASSIGNABLE_OBJECT_ORDER,
        skip=(clamped_page - 1) * clamped_size,
        limit=clamped_size,
    )

    return total, clamped_page, clamped_size, _shape_rows(types_manager, page_docs)


def read_searched_page(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    criteria: dict[str, Any],
    needle: str,
    page: int,
    page_size: int,
    request_user: CmdbUser | None,
) -> PickerPage:
    """
    Reads one page of the candidates whose summary line carries the needle

    The search matches the composed summary line, which only exists after the read, so every readable candidate
    is read (projected to what a row needs), shaped, filtered, and the filtered rows are paged

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        criteria (dict[str, Any]): The candidate filter (the IPAM-capable types)
        needle (str): The normalized search query (``active_search``)
        page (int): Requested 1-based page number; clamped against the filtered count
        page_size (int): Requested page size; clamped
        request_user (CmdbUser | None): The caller, whose READ access scopes the read

    Returns:
        PickerPage: (filtered total, clamped page, clamped page size, the page's rows)
    """
    object_docs: list[dict[str, Any]] = objects_manager.find_objects(
        criteria,
        as_dict=True,
        projection=ASSIGNABLE_OBJECT_PROJECTION,
        user=request_user,
        permission=AccessControlPermission.READ,
        sort=ASSIGNABLE_OBJECT_ORDER,
    )
    filtered: list[dict[str, Any]] = _apply_search(_shape_rows(types_manager, object_docs), needle)

    total: int = len(filtered)
    clamped_page, clamped_size = clamp_page(page, page_size, total)
    start_offset: int = (clamped_page - 1) * clamped_size

    return total, clamped_page, clamped_size, filtered[start_offset:start_offset + clamped_size]


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
    request_user: CmdbUser | None = None,
) -> dict[str, Any]:
    """
    Builds the paginated assignable-objects payload for the subnet IP-Übersicht picker

    Steps:
      1. Resolve every IPAM-capable CmdbType via ``find_ipam_capable_type_ids``. With no
         capable type the response collapses to an empty page envelope before any object
         lookup is issued
      2. Without an active search: count the readable candidates (``count_objects``) for ``total``,
         clamp the page, then read exactly that page from MongoDB (``find_objects`` with ``skip`` /
         ``limit`` and ``ASSIGNABLE_OBJECT_PROJECTION``) and shape it - one page of documents read
      3. With an active search: read every readable candidate (projected), shape them all so the
         case-insensitive substring filter can match the composed summary line, then page the
         filtered rows (the filter is skipped when the normalized query is shorter than
         IpamSearch.MIN_QUERY_LENGTH, which is the no-search path)
      4. ``total`` reflects the post-filter count (or the unfiltered count without a search);
         page / page_size are clamped via ``clamp_page``. Both paths list in ``public_id`` order

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

    # The picker offers objects the caller may actually open, so it is ACL-scoped like every other
    # presentation read - the count and the page alike
    criteria: dict[str, Any] = {CmdbObjectKey.TYPE_ID: {'$in': capable_type_ids}}
    needle: str | None = active_search(search)

    if needle is None:
        total, clamped_page, clamped_size, page_rows = read_unsearched_page(
            objects_manager, types_manager, criteria, page, page_size, request_user,
        )
    else:
        total, clamped_page, clamped_size, page_rows = read_searched_page(
            objects_manager, types_manager, criteria, needle, page, page_size, request_user,
        )

    return {
        IpamOverviewKey.PAGE: clamped_page,
        IpamOverviewKey.PAGE_SIZE: clamped_size,
        IpamOverviewKey.TOTAL: total,
        IpamOverviewKey.SEARCH: search,
        IpamOverviewKey.ROWS: page_rows,
    }
