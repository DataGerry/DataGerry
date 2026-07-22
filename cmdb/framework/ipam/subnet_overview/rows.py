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
Wire-format row shaping for the subnet IP-Übersicht table

Owns the assigned / free row shapes and the paginated 'ips' block assembly. Summary lines
for assigned rows are batch-resolved once per page (``resolve_summary_lines_for_ips``)
instead of per row
"""
from typing import Any

from cmdb.manager import ObjectsManager
from cmdb.models.object_model import CmdbObjectKey
from cmdb.models.special_type_model.ipam_constants import IpamOverviewKey, IpamRowStatus
from cmdb.framework.ipam.cidr import Network
from cmdb.framework.ipam.pagination import clamp_page
from cmdb.framework.ipam.subnet_overview.assigned_rows import (
    AssignedField,
    resolve_summary_lines_for_ips,
)
from cmdb.framework.ipam.subnet_overview.candidates import page_slice_ips
# -------------------------------------------------------------------------------------------------------------------- #


def _compose_assigned_row(
    ip_str: str,
    type_info: dict[str, Any] | None,
    assigned_to: dict[str, Any],
    mac_address: str | None,
    is_valid: bool,
) -> dict[str, Any]:
    """
    Shapes one 'assigned' row of the IP table

    'type_info' carries the owning CmdbObject's CmdbType as a
    {public_id, label, ci_explorer_color} triple so two distinct types sharing the
    same label remain distinguishable on the frontend and the row can be tinted
    with the user-chosen CI-Explorer colour. The dict is built by the orchestrator:
    public_id is the raw type_id stored on the CmdbObject, label and
    ci_explorer_color come from the bulk type lookup and may be None when the type
    can no longer be resolved (e.g. it was deleted after the interface row was
    written) or when the type has no color set

    'is_valid' is True when the row's IP falls inside the subnet's current CIDR and False
    when the row references this subnet but the IP is outside the (now-edited) CIDR.
    Invalid rows are surfaced so the FE can flag conflicts after a CIDR change

    Args:
        ip_str (str): The IP address as canonical string
        type_info (dict[str, Any] | None): {'public_id', 'label', 'ci_explorer_color'}
            for the owning CmdbObject's CmdbType, or None when the type_id is missing
        assigned_to (dict[str, Any]): {'public_id', 'summary_line'} for the owning CmdbObject
        mac_address (str | None): MAC stored on the interface row, or None when absent
        is_valid (bool): True when the row's IP is inside the subnet's CIDR, False otherwise

    Returns:
        dict[str, Any]: Row with keys ip, status, type_info, assigned_to, mac_address, is_valid
    """
    return {
        IpamOverviewKey.IP: ip_str,
        IpamOverviewKey.STATUS: IpamRowStatus.ASSIGNED,
        IpamOverviewKey.TYPE_INFO: type_info,
        IpamOverviewKey.ASSIGNED_TO: assigned_to,
        IpamOverviewKey.MAC_ADDRESS: mac_address,
        IpamOverviewKey.IS_VALID: is_valid,
    }


def _compose_free_row(ip_str: str) -> dict[str, Any]:
    """
    Shapes one 'free' row of the IP table

    Args:
        ip_str (str): The IP address as canonical string

    Returns:
        dict[str, Any]: Row with status='free' and the assignment-related fields nulled
    """
    return {
        IpamOverviewKey.IP: ip_str,
        IpamOverviewKey.STATUS: IpamRowStatus.FREE,
        IpamOverviewKey.TYPE_INFO: None,
        IpamOverviewKey.ASSIGNED_TO: None,
        IpamOverviewKey.MAC_ADDRESS: None,
    }


def compose_ip_row(
    ip_str: str,
    assigned: dict[str, dict[str, Any]],
    type_meta: dict[int, dict[str, Any]],
    summary_lines: dict[str, str],
) -> dict[str, Any]:
    """
    Shapes one IP-table row, returning either the assigned or the free variant

    Branches once on the presence of the IP in the assigned map. For an assigned IP the
    helper reads the summary line from the pre-batched ``summary_lines`` map (an owner that
    no longer resolves comes through as the empty string) and shapes the type_info triple
    from ``type_meta`` (any missing label / color comes through as None). For a free IP it
    returns the free-row shape directly. Keeping this composition in one function lets
    ``build_subnet_overview`` build the page-rows as a single list comprehension

    Args:
        ip_str (str): The canonical IP string this row represents
        assigned (dict[str, dict[str, Any]]): {ip_str: row_info} as produced by
            ``load_assigned_rows_map``
        type_meta (dict[int, dict[str, Any]]): {type_id: {'label', 'ci_explorer_color'}} as
            produced by ``resolve_type_meta``
        summary_lines (dict[str, str]): {ip_str: summary_line} as produced by
            ``resolve_summary_lines_for_ips`` for the IPs being shaped; IPs whose owner did
            not resolve are absent and fall back to the empty string

    Returns:
        dict[str, Any]: An assigned or free row shape as produced by ``_compose_assigned_row``
            / ``_compose_free_row``
    """
    info: dict[str, Any] | None = assigned.get(ip_str)

    if info is None:
        return _compose_free_row(ip_str)

    summary_line: str = summary_lines.get(ip_str, '')

    type_id: Any = info[AssignedField.TYPE_ID]
    type_entry: dict[str, Any] | None = type_meta.get(type_id) if type_id is not None else None
    type_info: dict[str, Any] | None = (
        {
            CmdbObjectKey.PUBLIC_ID: type_id,
            IpamOverviewKey.LABEL: type_entry.get(IpamOverviewKey.LABEL) if type_entry else None,
            IpamOverviewKey.CI_EXPLORER_COLOR: (
                type_entry.get(IpamOverviewKey.CI_EXPLORER_COLOR) if type_entry else None
            ),
        }
        if type_id is not None
        else None
    )

    return _compose_assigned_row(
        ip_str,
        type_info,
        {
            CmdbObjectKey.PUBLIC_ID: info[AssignedField.OBJECT_ID],
            IpamOverviewKey.SUMMARY_LINE: summary_line,
        },
        info[AssignedField.MAC],
        info[AssignedField.IS_VALID],
    )


def build_ips_block(
    network: Network,
    assignable: int,
    page: int,
    page_size: int,
    candidates: list[str] | None,
    assigned: dict[str, dict[str, Any]],
    type_meta: dict[int, dict[str, Any]],
    objects_manager: ObjectsManager,
) -> dict[str, Any]:
    """
    Builds the 'ips' page block (page, page_size, total, rows) for the IP-Übersicht payload

    Splits on whether the caller pre-resolved the candidate IP list. ``candidates is None``
    signals the lazy path: pagination uses ``page_slice_ips`` against the full assignable
    range so a large subnet does not materialize its IPs in memory, and 'total' equals the
    subnet's assignable count. A non-None ``candidates`` is the final candidate order
    (after search filtering and / or sort) and pagination slices it directly with 'total'
    set to the candidate count. Either way each IP on the page is shaped via
    ``compose_ip_row`` so the assigned-vs-free row composition stays encapsulated

    Summary lines for the page's assigned rows are batch-resolved in ONE
    ``resolve_summary_lines_for_ips`` round-trip pair before the rows are shaped - never
    one lookup per row

    Args:
        network (IPv4Network): The parsed subnet network
        assignable (int): Assignable address count of the subnet (used only on the lazy path)
        page (int): 1-based page number; clamped server-side
        page_size (int): Page size; clamped server-side
        candidates (list[str] | None): Pre-resolved candidate IP list (search-filtered and / or
            sorted) or None to signal the lazy ascending-IP path
        assigned (dict[str, dict[str, Any]]): {ip_str: row_info} as produced by
            ``load_assigned_rows_map``
        type_meta (dict[int, dict[str, Any]]): {type_id: {'label', 'ci_explorer_color'}} as
            produced by ``resolve_type_meta``
        objects_manager (ObjectsManager): db interface for CmdbObjects (used by the page's
            single summary-line batch)

    Returns:
        dict[str, Any]: {page, page_size, total, rows} block ready to drop under the 'ips'
            key of the overview payload
    """
    if candidates is None:
        safe_page, safe_size = clamp_page(page, page_size, assignable)
        page_ips: list[str] = page_slice_ips(network, safe_page, safe_size)
        ips_total: int = assignable
    else:
        safe_page, safe_size = clamp_page(page, page_size, len(candidates))
        start: int = (safe_page - 1) * safe_size
        page_ips = candidates[start:start + safe_size]
        ips_total = len(candidates)

    summary_lines: dict[str, str] = resolve_summary_lines_for_ips(page_ips, assigned, objects_manager)

    return {
        IpamOverviewKey.PAGE: safe_page,
        IpamOverviewKey.PAGE_SIZE: safe_size,
        IpamOverviewKey.TOTAL: ips_total,
        IpamOverviewKey.ROWS: [
            compose_ip_row(ip, assigned, type_meta, summary_lines) for ip in page_ips
        ],
    }
