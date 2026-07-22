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
Row provider for the subnet IPs Excel export

Builds every IP-table row of a subnet in ascending IP order, guarded by the
IpamSubnetIpsExport.MAX_EXPORT_ROWS cap before any address space is enumerated
"""
from typing import Any

from flask import abort

from cmdb.manager import ObjectsManager, TypesManager
from cmdb.models.special_type_model.ipam_constants import IpAddressFamily, IpamSubnetIpsExport
from cmdb.framework.ipam.cidr import Network, network_family, assignable_address_count
from cmdb.framework.ipam.subnet_overview.assigned_rows import (
    AssignedField,
    load_assigned_rows_map,
    load_subnet_object,
    parse_subnet_network,
    resolve_summary_lines_for_ips,
    resolve_type_meta,
    sorted_assigned_ips,
)
from cmdb.framework.ipam.subnet_overview.candidates import list_all_assignable_ips
from cmdb.framework.ipam.subnet_overview.rows import compose_ip_row
# -------------------------------------------------------------------------------------------------------------------- #


def _abort_if_export_too_big(public_id: int, row_count: int) -> None:
    """
    Aborts HTTP 400 when ``row_count`` exceeds IpamSubnetIpsExport.MAX_EXPORT_ROWS

    Guards the IP export so an oversized subnet is rejected before any workbook is built. The
    counted volume is the family-specific export size the caller computed cheaply (the IPv4
    assignable count or the IPv6 assigned count), never an enumerated address space

    Args:
        public_id (int): public_id of the subnet being exported (for the error message)
        row_count (int): Number of IP rows the export would emit

    Raises:
        HTTPException: 400 when ``row_count`` is over the export limit
    """
    if row_count > IpamSubnetIpsExport.MAX_EXPORT_ROWS:
        abort(
            400,
            f"Subnet with ID {public_id} is too big to export: {row_count} entries exceed the "
            f"{IpamSubnetIpsExport.MAX_EXPORT_ROWS}-row export limit!",
        )


def build_subnet_ip_export_rows(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    public_id: int,
) -> list[dict[str, Any]]:
    """
    Builds every IP-table row of a subnet for the Excel export, in ascending IP order

    Mirrors the default (unfiltered) IP table of ``build_subnet_overview``: an IPv4 subnet
    exports all in-CIDR assignable addresses (free + assigned), an IPv6 subnet exports only its
    in-CIDR assigned addresses. The out-of-CIDR (invalid) rows surfaced by the separate
    ``/invalid`` view are not part of the export.

    The export size is checked against IpamSubnetIpsExport.MAX_EXPORT_ROWS BEFORE any address
    space is enumerated - for IPv4 against the cheap ``assignable_address_count`` and for IPv6
    against the already-loaded assigned-row count - so an oversized subnet aborts 400 without
    materializing a multi-thousand-entry list

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        public_id (int): public_id of the subnet whose IPs are exported

    Returns:
        list[dict[str, Any]]: IP-table rows (assigned / free shapes as produced by
            ``compose_ip_row``) in ascending IP order

    Raises:
        HTTPException: 404 / 400 from ``load_subnet_object`` (missing or non-subnet object),
            400 when the subnet's network range is missing / unparsable, and 400 when the
            export would exceed IpamSubnetIpsExport.MAX_EXPORT_ROWS
    """
    subnet_obj: dict[str, Any] = load_subnet_object(objects_manager, types_manager, public_id)
    network: Network | None = parse_subnet_network(subnet_obj)

    if network is None:
        abort(400, f"Subnet with ID {public_id} has no exportable IPs: its network range is missing or invalid!")

    assigned: dict[str, dict[str, Any]] = load_assigned_rows_map(objects_manager, public_id, network)

    if network_family(network) == IpAddressFamily.IPV6:
        candidate_ips: list[str] = sorted_assigned_ips(assigned, valid=True)
        _abort_if_export_too_big(public_id, len(candidate_ips))
    else:
        _abort_if_export_too_big(public_id, assignable_address_count(network))
        candidate_ips = list_all_assignable_ips(network)

    type_meta: dict[int, dict[str, Any]] = resolve_type_meta(types_manager, [
        info[AssignedField.TYPE_ID]
        for info in assigned.values()
        if isinstance(info.get(AssignedField.TYPE_ID), int)
    ])

    summary_lines: dict[str, str] = resolve_summary_lines_for_ips(candidate_ips, assigned, objects_manager)

    return [compose_ip_row(ip, assigned, type_meta, summary_lines) for ip in candidate_ips]
