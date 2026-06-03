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
Excel (.xlsx) export of all assigned subnets of a supernet

Builds a single-sheet workbook listing every subnet referencing the supernet, one row each, with
the columns CIDR, IP range (first - last), used IPs and free IPs. An IPv4 supernet's sheet also
carries a trailing 'Usage (%)' column; an IPv6 supernet omits it, since a used/total ratio against
a 2**n address space is meaningless. The subnet rows come from the same overview pipeline that
powers the supernet view, so the exported figures match what the UI shows.
"""
from logging import Logger, getLogger
from typing import Any
from io import BytesIO

from openpyxl import Workbook

from cmdb.manager import ObjectsManager, TypesManager

from cmdb.models.special_type_model.ipam_constants import IpamOverviewKey, IpamExport, IpAddressFamily
from cmdb.framework.ipam.supernet_overview import load_assigned_subnet_rows, resolve_supernet_family
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
