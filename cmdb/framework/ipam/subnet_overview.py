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
Builds the data payload for the SUBNET 'IP-Übersicht' view

The frontend renders KPI counters (total / used / free) plus a paginated, IP-sorted table
where each address of the subnet appears as either an 'assigned' or 'free' row. This module
exposes pure helpers (CIDR math, page slicing, row shaping) plus a thin DB orchestrator that
loads the subnet, the interface rows that reference it, and the type labels / summary lines
needed for the page slice
"""
from ipaddress import IPv4Address, IPv4Network
from typing import Any

from flask import abort

from cmdb.manager import ObjectsManager, TypesManager
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import (
    SubnetField,
    InterfaceField,
    IpamSection,
)
from cmdb.framework.ipam.cidr import parse_cidr, parse_ipv4, ip_in_network
from cmdb.framework.ipam.references import resolve_special_type_id
from cmdb.framework.ipam.subnet_validator import extract_field_value
# -------------------------------------------------------------------------------------------------------------------- #


DEFAULT_PAGE_SIZE: int = 50
MAX_PAGE_SIZE: int = 500


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  PURE HELPERS                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def _usable_count(network: IPv4Network) -> int:
    """
    Returns the number of usable host addresses in a network

    /31 and /32 networks report 0 to match the supernet-overview policy (network and broadcast
    are excluded for /30 and shorter; /31 and /32 have no usable hosts under this scheme)

    Args:
        network (IPv4Network): The parsed network

    Returns:
        int: Usable host count, with /31 and /32 zeroed
    """
    if network.prefixlen >= 31:
        return 0

    return network.num_addresses - 2


def _first_usable_int(network: IPv4Network) -> int | None:
    """
    Returns the integer value of the network's first usable host, or None for /31 and /32

    Args:
        network (IPv4Network): The parsed network

    Returns:
        int | None: The integer of the first usable address, or None when no usable host exists
    """
    if network.prefixlen >= 31:
        return None

    return int(network.network_address) + 1


def _clamp_page(page: int, page_size: int, total: int) -> tuple[int, int]:
    """
    Clamps page / page_size into safe values given the total item count

    Args:
        page (int): Requested 1-based page number
        page_size (int): Requested page size
        total (int): Total number of available items

    Returns:
        tuple[int, int]: (clamped_page, clamped_page_size); page is at least 1 and at most the
            last page that contains items, page_size is in [1, MAX_PAGE_SIZE]
    """
    safe_size: int = max(1, min(page_size, MAX_PAGE_SIZE))

    if total <= 0:
        return 1, safe_size

    last_page: int = max(1, (total + safe_size - 1) // safe_size)
    safe_page: int = max(1, min(page, last_page))

    return safe_page, safe_size


def _page_slice_ips(network: IPv4Network, page: int, page_size: int) -> list[str]:
    """
    Returns the IP strings for one page of a subnet's usable addresses

    Computes the slice in O(page_size) without iterating the whole subnet, so /16 and larger
    subnets paginate cheaply. Network and broadcast addresses are excluded

    Args:
        network (IPv4Network): The parsed subnet network
        page (int): 1-based page number
        page_size (int): Number of IPs per page

    Returns:
        list[str]: IP strings for the requested page; empty when the subnet has no usable
            addresses or the page is past the end
    """
    first: int | None = _first_usable_int(network)

    if first is None:
        return []

    total: int = _usable_count(network)
    start_offset: int = (page - 1) * page_size

    if start_offset >= total:
        return []

    end_offset: int = min(start_offset + page_size, total)

    return [str(IPv4Address(first + i)) for i in range(start_offset, end_offset)]


def _compose_assigned_row(
    ip_str: str,
    type_info: dict[str, Any] | None,
    assigned_to: dict[str, Any],
    mac_address: str | None,
) -> dict[str, Any]:
    """
    Shapes one 'assigned' row of the IP table

    'type_info' carries the owning CmdbObject's CmdbType as a {public_id, label}
    pair so two distinct types sharing the same label remain distinguishable on
    the frontend. The pair is built by the orchestrator: public_id is the raw
    type_id stored on the CmdbObject, label comes from the bulk type lookup and
    may be None when the type can no longer be resolved (e.g. it was deleted
    after the interface row was written)

    Args:
        ip_str (str): The IP address as canonical string
        type_info (dict[str, Any] | None): {'public_id', 'label'} for the
            owning CmdbObject's CmdbType, or None when the type_id is missing
        assigned_to (dict[str, Any]): {'public_id', 'summary_line'} for the owning CmdbObject
        mac_address (str | None): MAC stored on the interface row, or None when absent

    Returns:
        dict[str, Any]: Row with keys ip, status, type_info, assigned_to, mac_address
    """
    return {
        'ip': ip_str,
        'status': 'assigned',
        'type_info': type_info,
        'assigned_to': assigned_to,
        'mac_address': mac_address,
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
        'ip': ip_str,
        'status': 'free',
        'type_info': None,
        'assigned_to': None,
        'mac_address': None,
    }


def _extract_row_fields(row: dict[str, Any]) -> tuple[Any, Any, Any]:
    """
    Reads the (subnet_ref, ip, mac) triple from one dg-ipam-interface MDS row

    Args:
        row (dict[str, Any]): One entry from an MDS section's 'values' list

    Returns:
        tuple[Any, Any, Any]: (subnet ref, ip value, mac value); any field absent from the row
            comes back as None
    """
    subnet_ref: Any = None
    ip_value: Any = None
    mac_value: Any = None

    for entry in row.get('data', []) or []:
        name: Any = entry.get('name')

        if name == InterfaceField.SUBNET:
            subnet_ref = entry.get('value')
        elif name == InterfaceField.IP:
            ip_value = entry.get('value')
        elif name == InterfaceField.MAC:
            mac_value = entry.get('value')

    return subnet_ref, ip_value, mac_value


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   DATA LOADING                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def _load_subnet_object(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    public_id: int,
) -> dict[str, Any]:
    """
    Loads the SUBNET CmdbObject by public_id, aborting with structured HTTP errors when the
    SUBNET CmdbType is undefined, the object does not exist, or the object exists but is of a
    different CmdbType

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        public_id (int): public_id of the candidate subnet object

    Returns:
        dict[str, Any]: The subnet CmdbObject document
    """
    subnet_type_id: int | None = resolve_special_type_id(types_manager, SpecialType.SUBNET)

    if subnet_type_id is None:
        abort(400, "No SUBNET CmdbType is defined; cannot build subnet overview!")

    candidates: list[dict[str, Any]] = objects_manager.find_objects(
        {'public_id': public_id},
        as_dict=True,
    )

    if not candidates:
        abort(404, f"Subnet with public_id {public_id} was not found!")

    candidate: dict[str, Any] = candidates[0]

    if candidate.get('type_id') != subnet_type_id:
        abort(400, f"Object with public_id {public_id} is not a SUBNET!")

    return candidate


def _load_assigned_rows_map(
    objects_manager: ObjectsManager,
    subnet_object_id: int,
    network: IPv4Network,
) -> dict[str, dict[str, Any]]:
    """
    Loads every dg-ipam-interface row referencing the subnet and indexes them by canonical IP

    Returns one entry per assigned IP. Rows whose IP is unparsable or falls outside the given
    network are skipped (defensive against legacy / drifted state). Per the interface
    validator's pre-save uniqueness check there is at most one row per IP within a subnet, so
    the map is well-defined

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        subnet_object_id (int): public_id of the subnet
        network (IPv4Network): The parsed subnet network, used to filter out-of-range rows

    Returns:
        dict[str, dict[str, Any]]: {ip_str: {'object_id', 'type_id', 'mac'}}; mac is None when
            the field is absent or empty
    """
    criteria: dict[str, Any] = {
        'multi_data_sections': {
            '$elemMatch': {
                'name': IpamSection.INTERFACE,
                'values': {
                    '$elemMatch': {
                        'data': {
                            '$elemMatch': {
                                'name': InterfaceField.SUBNET,
                                'value': subnet_object_id,
                            },
                        },
                    },
                },
            },
        },
    }

    candidates: list[dict[str, Any]] = objects_manager.find_objects(criteria, as_dict=True)

    out: dict[str, dict[str, Any]] = {}

    for candidate in candidates:
        candidate_id: Any = candidate.get('public_id')
        candidate_type_id: Any = candidate.get('type_id')

        for section in candidate.get('multi_data_sections', []) or []:
            if section.get('name') != IpamSection.INTERFACE:
                continue

            for row in section.get('values', []) or []:
                row_subnet, row_ip, row_mac = _extract_row_fields(row)

                if row_subnet != subnet_object_id or not isinstance(row_ip, str):
                    continue

                parsed_ip: IPv4Address | None = parse_ipv4(row_ip)

                if parsed_ip is None or not ip_in_network(parsed_ip, network):
                    continue

                out[str(parsed_ip)] = {
                    'object_id': candidate_id,
                    'type_id': candidate_type_id,
                    'mac': row_mac if isinstance(row_mac, str) and row_mac else None,
                }

    return out


def _resolve_type_labels(
    types_manager: TypesManager,
    type_ids: list[int],
) -> dict[int, str]:
    """
    Bulk-resolves a list of CmdbType public_ids to their labels

    Args:
        types_manager (TypesManager): db interface for CmdbTypes
        type_ids (list[int]): The CmdbType ids to resolve (duplicates allowed)

    Returns:
        dict[int, str]: {type_id: type_label}; types that no longer exist are absent
    """
    if not type_ids:
        return {}

    lookup = types_manager.get_types_lookup(list(set(type_ids)))

    return {tid: t.label for tid, t in lookup.items()}


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   ORCHESTRATOR                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def build_subnet_overview(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    public_id: int,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> dict[str, Any]:
    """
    Builds the full IP-Übersicht payload for the SUBNET CmdbObject identified by public_id

    Aborts HTTP 404 when the subnet does not exist and HTTP 400 when the public_id refers to a
    non-subnet CmdbObject or no SUBNET CmdbType is defined. When the subnet's
    'dg-network-range' is missing or unparsable, returns the KPI block with zeroed counters and
    an empty page (broken state is observable but does not 500)

    Summary lines are resolved only for the assigned rows on the requested page, never for the
    whole subnet, so the cost is bounded by page_size

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        public_id (int): public_id of the subnet to summarise
        page (int): 1-based page number (clamped into the valid range)
        page_size (int): Page size (clamped to [1, MAX_PAGE_SIZE])

    Returns:
        dict[str, Any]: {'subnet': {public_id, cidr, ip_range, total_ips, used_ips, free_ips},
            'ips': {page, page_size, total, rows: [...]}}
    """
    subnet_obj: dict[str, Any] = _load_subnet_object(objects_manager, types_manager, public_id)

    raw_cidr: Any = extract_field_value(subnet_obj, SubnetField.NETWORK_RANGE)
    network: IPv4Network | None = parse_cidr(raw_cidr) if isinstance(raw_cidr, str) else None

    if network is None:
        safe_page, safe_size = _clamp_page(page, page_size, 0)
        return {
            'subnet': {
                'public_id': subnet_obj.get('public_id'),
                'cidr': raw_cidr if isinstance(raw_cidr, str) else None,
                'ip_range': None,
                'total_ips': 0,
                'used_ips': 0,
                'free_ips': 0,
            },
            'ips': {
                'page': safe_page,
                'page_size': safe_size,
                'total': 0,
                'rows': [],
            },
        }

    total: int = _usable_count(network)
    assigned: dict[str, dict[str, Any]] = _load_assigned_rows_map(objects_manager, public_id, network)
    used_ips: int = len(assigned)
    free_ips: int = max(0, total - used_ips)

    safe_page, safe_size = _clamp_page(page, page_size, total)
    page_ips: list[str] = _page_slice_ips(network, safe_page, safe_size)

    page_type_ids: list[int] = [
        assigned[ip]['type_id']
        for ip in page_ips
        if ip in assigned and isinstance(assigned[ip].get('type_id'), int)
    ]
    type_labels: dict[int, str] = _resolve_type_labels(types_manager, page_type_ids)

    rows: list[dict[str, Any]] = []

    for ip in page_ips:
        info: dict[str, Any] | None = assigned.get(ip)

        if info is None:
            rows.append(_compose_free_row(ip))
            continue

        summary_line: str = objects_manager.get_summary_line(info['object_id'], with_type=True)

        type_id: Any = info['type_id']
        type_info: dict[str, Any] | None = (
            {'public_id': type_id, 'label': type_labels.get(type_id)}
            if type_id is not None
            else None
        )

        rows.append(_compose_assigned_row(
            ip,
            type_info,
            {'public_id': info['object_id'], 'summary_line': summary_line},
            info['mac'],
        ))

    return {
        'subnet': {
            'public_id': subnet_obj.get('public_id'),
            'cidr': str(network),
            'ip_range': {
                'first': str(network.network_address),
                'last': str(network.broadcast_address),
            },
            'total_ips': total,
            'used_ips': used_ips,
            'free_ips': free_ips,
        },
        'ips': {
            'page': safe_page,
            'page_size': safe_size,
            'total': total,
            'rows': rows,
        },
    }
