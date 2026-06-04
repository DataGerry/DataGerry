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
Excel (.xlsx) exports for the IPAM overviews

Two single-sheet exports live here:
- ``build_supernet_subnets_xlsx`` lists every subnet referencing a supernet, one row each, with the
  columns CIDR, IP range (first - last), used IPs and free IPs. An IPv4 supernet's sheet also carries
  a trailing 'Usage (%)' column; an IPv6 supernet omits it, since a used/total ratio against a 2**n
  address space is meaningless.
- ``build_subnet_ips_xlsx`` lists a subnet's IP-table rows, one row each, with the columns IP, type,
  status, assigned-to summary and MAC. An IPv4 subnet exports all assignable addresses (free +
  assigned); an IPv6 subnet exports only its assigned addresses.

Both pull their rows from the same overview pipelines that power the UI, so the exported figures
match what the user sees.
"""
from logging import Logger, getLogger
from typing import Any
from io import BytesIO

from openpyxl import Workbook

from cmdb.manager import ObjectsManager, TypesManager

from cmdb.models.special_type_model.ipam_constants import (
    IpamOverviewKey,
    IpamExport,
    IpamSubnetIpsExport,
    IpamRowStatus,
    IpAddressFamily,
)
from cmdb.framework.ipam.supernet_overview import load_assigned_subnet_rows, resolve_supernet_family
from cmdb.framework.ipam.subnet_overview import build_subnet_ip_export_rows
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

def _format_ip_range(ip_range: dict[str, str] | None) -> str:
    """
    Renders a subnet's ip_range as 'first - last'

    Args:
        ip_range (dict[str, str] | None): The {first, last} range, or None for an unparsable CIDR

    Returns:
        str: 'first - last', or '' when no range is available
    """
    if not ip_range:
        return ''

    return f"{ip_range[IpamOverviewKey.FIRST]}{IpamExport.IP_RANGE_SEPARATOR}{ip_range[IpamOverviewKey.LAST]}"


def _subnet_export_row(row: dict[str, Any], include_usage: bool) -> list[Any]:
    """
    Maps one overview subnet row to its export cell values, matching the chosen header set

    Args:
        row (dict[str, Any]): A subnet overview row (see compute_subnet_row)
        include_usage (bool): Whether to append the IPv4-only usage-percent cell

    Returns:
        list[Any]: [cidr, ip_range, used_ips, free_ips] (+ usage_percent when include_usage)
    """
    cells: list[Any] = [
        row.get(IpamOverviewKey.CIDR),
        _format_ip_range(row.get(IpamOverviewKey.IP_RANGE)),
        row.get(IpamOverviewKey.USED_IPS),
        row.get(IpamOverviewKey.FREE_IPS),
    ]

    if include_usage:
        cells.append(row.get(IpamOverviewKey.USAGE_PERCENT))

    return cells


def build_supernet_subnets_xlsx(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    supernet_public_id: int,
) -> bytes:
    """
    Builds an XLSX workbook listing all assigned subnets of a supernet and returns its bytes

    Validation of the supernet (exists / is a SUPERNET) is delegated to load_assigned_subnet_rows,
    which aborts on a bad id exactly like the overview routes.

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        supernet_public_id (int): public_id of the SUPERNET whose subnets are exported

    Returns:
        bytes: The serialized .xlsx workbook
    """
    is_ipv6: bool = resolve_supernet_family(
        objects_manager, types_manager, supernet_public_id,
    ) == IpAddressFamily.IPV6
    rows: list[dict[str, Any]] = load_assigned_subnet_rows(objects_manager, types_manager, supernet_public_id)

    workbook: Workbook = Workbook()
    sheet = workbook.active
    sheet.title = IpamExport.SHEET_TITLE

    # IPv4 sheets carry the trailing 'Usage (%)' column; IPv6 sheets omit it
    headers: list[str] = IpamExport.HEADERS if is_ipv6 else IpamExport.HEADERS + [IpamExport.USAGE_HEADER]
    sheet.append(headers)

    for row in rows:
        sheet.append(_subnet_export_row(row, include_usage=not is_ipv6))

    buffer: BytesIO = BytesIO()
    workbook.save(buffer)

    return buffer.getvalue()


def _subnet_ip_export_row(row: dict[str, Any]) -> list[Any]:
    """
    Maps one overview IP row to its export cell values, matching IpamSubnetIpsExport.HEADERS

    The type and assigned-to columns carry the human-readable label / summary line (the same text
    the UI shows); a free row leaves type, assigned-to and MAC blank. The status enum is written as
    its plain value ('assigned' / 'free') - openpyxl would otherwise stringify the enum member to
    'IpamRowStatus.ASSIGNED'.

    Args:
        row (dict[str, Any]): An IP-table row (assigned / free shape as produced by _compose_ip_row)

    Returns:
        list[Any]: [ip, type_label, status, assigned_to_summary, mac]
    """
    type_info: dict[str, Any] | None = row.get(IpamOverviewKey.TYPE_INFO)
    assigned_to: dict[str, Any] | None = row.get(IpamOverviewKey.ASSIGNED_TO)
    status: Any = row.get(IpamOverviewKey.STATUS)

    return [
        row.get(IpamOverviewKey.IP),
        type_info.get(IpamOverviewKey.LABEL) if type_info else '',
        status.value if isinstance(status, IpamRowStatus) else status,
        assigned_to.get(IpamOverviewKey.SUMMARY_LINE) if assigned_to else '',
        row.get(IpamOverviewKey.MAC_ADDRESS) or '',
    ]


def build_subnet_ips_xlsx(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    subnet_public_id: int,
) -> bytes:
    """
    Builds an XLSX workbook listing a subnet's IP rows and returns its bytes

    Validation of the subnet (exists / is a SUBNET / has a parsable range) and the oversized-export
    guard (IpamSubnetIpsExport.MAX_EXPORT_ROWS) are delegated to ``build_subnet_ip_export_rows``,
    which aborts before this function builds any workbook. IPv4 subnets export all assignable
    addresses (free + assigned); IPv6 subnets export only the assigned ones. The column set is the
    same for both families.

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        subnet_public_id (int): public_id of the SUBNET whose IPs are exported

    Returns:
        bytes: The serialized .xlsx workbook

    Raises:
        HTTPException: 404 / 400 propagated from ``build_subnet_ip_export_rows`` (bad id,
            unparsable range, or an export exceeding the row limit)
    """
    rows: list[dict[str, Any]] = build_subnet_ip_export_rows(objects_manager, types_manager, subnet_public_id)

    workbook: Workbook = Workbook()
    sheet = workbook.active
    sheet.title = IpamSubnetIpsExport.SHEET_TITLE

    sheet.append(IpamSubnetIpsExport.HEADERS)

    for row in rows:
        sheet.append(_subnet_ip_export_row(row))

    buffer: BytesIO = BytesIO()
    workbook.save(buffer)

    return buffer.getvalue()
