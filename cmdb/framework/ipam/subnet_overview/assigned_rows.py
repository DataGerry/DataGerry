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
Subnet loading and assigned-row indexing for the subnet IP-Übersicht

Owns the DB-facing primitives every subnet_overview module shares: loading and validating
the SUBNET CmdbObject, indexing the dg-ipam-interface rows that reference it by canonical
IP (``load_assigned_rows_map``), bulk type-metadata and summary-line resolution, and the
sorted views over the assigned map
"""
from typing import Any

from flask import abort

from cmdb.manager import ObjectsManager, TypesManager
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import (
    SubnetField,
    InterfaceField,
    IpamSection,
    IpamOverviewKey,
)
from cmdb.models.object_model import (
    CmdbObjectKey,
    CmdbObjectFieldKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
    extract_field_value,
)
from cmdb.framework.ipam.cidr import (
    Network,
    Address,
    parse_cidr,
    parse_ip,
    ip_in_network,
)
from cmdb.framework.ipam.references import field_value_expr, resolve_special_type_id
# -------------------------------------------------------------------------------------------------------------------- #


class AssignedField:
    """
    Internal dict keys for the per-IP map produced by load_assigned_rows_map

    Not part of the JSON output shape (the orchestrator translates these into the
    IpamOverviewKey-keyed wire format at the assembly step) so they don't belong in
    IpamOverviewKey. Kept here to avoid bare string literals in this package. ``IP`` is not
    part of the map values - it is the projection key the load aggregation ships each row's
    raw IP under before the map is keyed by canonical IP
    """
    OBJECT_ID: str = 'object_id'
    TYPE_ID: str = 'type_id'
    MAC: str = 'mac'
    IS_VALID: str = 'is_valid'
    IP: str = 'ip'


def load_subnet_object(
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
        {CmdbObjectKey.PUBLIC_ID: public_id},
        as_dict=True,
    )

    if not candidates:
        abort(404, f"Subnet with public_id {public_id} was not found!")

    candidate: dict[str, Any] = candidates[0]

    if candidate.get(CmdbObjectKey.TYPE_ID) != subnet_type_id:
        abort(400, f"Object with public_id {public_id} is not a SUBNET!")

    return candidate


def load_assigned_rows_map(
    objects_manager: ObjectsManager,
    subnet_object_id: int,
    network: Network,
) -> dict[str, dict[str, Any]]:
    """
    Loads every dg-ipam-interface row referencing the subnet and indexes them by canonical IP

    A single aggregation matches the carrier documents, unwinds their dg-ipam-interface rows
    and projects only the per-row payload (owner public_id, owner type_id, IP, MAC) - the
    full CmdbObject documents never leave the database. Compatible with the project-wide
    MongoDB 6.0 floor

    Returns one entry per assigned IP. Rows whose IP value is unparsable as an IPv4
    dotted-quad or IPv6 address are dropped (corrupted state). Rows whose parsed IP falls
    outside ``network`` are kept and tagged ``is_valid=False`` so the overview can surface
    them as conflicts after a CIDR change; rows inside the network are tagged
    ``is_valid=True``. Per the interface validator's pre-save uniqueness check there is at
    most one row per IP within a subnet, so the map is well-defined

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        subnet_object_id (int): public_id of the subnet
        network (Network): The parsed subnet network, used to compute the per-row
            is_valid flag (rows whose IP is outside the network become is_valid=False)

    Returns:
        dict[str, dict[str, Any]]: {ip_str: {'object_id', 'type_id', 'mac', 'is_valid'}};
            mac is None when the field is absent or empty; is_valid is False for rows whose
            parsed IP falls outside ``network``
    """
    mds_key: str = CmdbObjectKey.MULTI_DATA_SECTIONS.value
    rows_path: str = f'{mds_key}.{CmdbObjectMdsKey.VALUES.value}'
    data_path: str = f'{rows_path}.{CmdbObjectMdsRowKey.DATA.value}'

    subnet_ref_match: dict[str, Any] = {
        '$elemMatch': {
            CmdbObjectFieldKey.NAME: InterfaceField.SUBNET,
            CmdbObjectFieldKey.VALUE: subnet_object_id,
        },
    }

    pipeline: list[dict[str, Any]] = [
        {'$match': {
            CmdbObjectKey.MULTI_DATA_SECTIONS: {
                '$elemMatch': {
                    CmdbObjectMdsKey.SECTION_ID: IpamSection.INTERFACE,
                    CmdbObjectMdsKey.VALUES: {
                        '$elemMatch': {CmdbObjectMdsRowKey.DATA: subnet_ref_match},
                    },
                },
            },
        }},
        {'$unwind': f'${mds_key}'},
        {'$match': {f'{mds_key}.{CmdbObjectMdsKey.SECTION_ID.value}': IpamSection.INTERFACE}},
        {'$unwind': f'${rows_path}'},
        {'$match': {data_path: subnet_ref_match}},
        {'$project': {
            '_id': 0,
            AssignedField.OBJECT_ID: f'${CmdbObjectKey.PUBLIC_ID.value}',
            AssignedField.TYPE_ID: f'${CmdbObjectKey.TYPE_ID.value}',
            AssignedField.IP: field_value_expr(InterfaceField.IP, data_path),
            AssignedField.MAC: field_value_expr(InterfaceField.MAC, data_path),
        }},
    ]

    out: dict[str, dict[str, Any]] = {}

    for row in objects_manager.aggregate_objects(pipeline):
        row_ip: Any = row.get(AssignedField.IP)

        if not isinstance(row_ip, str):
            continue

        parsed_ip: Address | None = parse_ip(row_ip)

        if parsed_ip is None:
            continue

        row_mac: Any = row.get(AssignedField.MAC)

        out[str(parsed_ip)] = {
            AssignedField.OBJECT_ID: row.get(AssignedField.OBJECT_ID),
            AssignedField.TYPE_ID: row.get(AssignedField.TYPE_ID),
            AssignedField.MAC: row_mac if isinstance(row_mac, str) and row_mac else None,
            AssignedField.IS_VALID: ip_in_network(parsed_ip, network),
        }

    return out


def resolve_type_meta(
    types_manager: TypesManager,
    type_ids: list[int],
) -> dict[int, dict[str, Any]]:
    """
    Bulk-resolves a list of CmdbType public_ids to the metadata the overview needs

    Returns the label plus the CI-Explorer color so the frontend can render type chips and
    pie-chart slices with the same colour the user picked under 'Type Settings'. A single bulk
    lookup is issued and the projection happens client-side, so this stays cheap even when a
    subnet has assignments across dozens of distinct types

    Args:
        types_manager (TypesManager): db interface for CmdbTypes
        type_ids (list[int]): The CmdbType ids to resolve (duplicates allowed)

    Returns:
        dict[int, dict[str, Any]]: {type_id: {'label': str, 'ci_explorer_color': str | None}};
            types that no longer exist are absent so callers can route them into the Unknown
            bucket
    """
    if not type_ids:
        return {}

    lookup = types_manager.get_types_lookup(list(set(type_ids)))

    return {
        tid: {IpamOverviewKey.LABEL: t.label, IpamOverviewKey.CI_EXPLORER_COLOR: t.ci_explorer_color}
        for tid, t in lookup.items()
    }


def parse_subnet_network(subnet_obj: dict[str, Any]) -> Network | None:
    """
    Returns the parsed IPv4Network of a SUBNET CmdbObject, or None when unparsable / missing

    Reads the subnet's 'dg-network-range' field via ``extract_field_value`` and runs
    ``parse_cidr`` over it only when the value is a string, so a degenerate field value
    (None / non-string) does not crash the orchestrator

    Args:
        subnet_obj (dict[str, Any]): The SUBNET CmdbObject document

    Returns:
        IPv4Network | None: Parsed network, or None when the CIDR is missing or unparsable
    """
    raw_cidr: Any = extract_field_value(subnet_obj, SubnetField.NETWORK_RANGE)

    if not isinstance(raw_cidr, str):
        return None

    return parse_cidr(raw_cidr)


def sorted_assigned_ips(assigned: dict[str, dict[str, Any]], valid: bool) -> list[str]:
    """
    Returns the canonical IP strings of the assigned map's rows matching the ``valid`` flag

    Sorted by ascending integer IP (family-agnostic via ``parse_ip``) so the IP table has a
    deterministic order for both IPv4 and IPv6 subnets. ``valid=True`` selects the in-CIDR
    rows, ``valid=False`` the out-of-CIDR (invalid) rows

    Args:
        assigned (dict[str, dict[str, Any]]): {ip_str: row_info} as produced by
            ``load_assigned_rows_map``
        valid (bool): Select rows whose ``is_valid`` flag equals this value

    Returns:
        list[str]: Matching IPs in ascending IP order
    """
    return sorted(
        (ip for ip, info in assigned.items() if bool(info[AssignedField.IS_VALID]) is valid),
        key=lambda ip: int(parse_ip(ip)),
    )


def sorted_invalid_ips(assigned: dict[str, dict[str, Any]]) -> list[str]:
    """
    Returns the canonical IP strings of the assigned map's invalid (out-of-CIDR) rows

    Thin wrapper over ``sorted_assigned_ips`` for the invalid rows. Empty list when no row in
    the assigned map is tagged invalid - the common steady-state case before any CIDR edit

    Args:
        assigned (dict[str, dict[str, Any]]): {ip_str: row_info} as produced by
            ``load_assigned_rows_map``

    Returns:
        list[str]: Invalid IPs in ascending IP order
    """
    return sorted_assigned_ips(assigned, valid=False)


def resolve_summary_lines_for_ips(
    candidate_ips: list[str],
    assigned: dict[str, dict[str, Any]],
    objects_manager: ObjectsManager,
) -> dict[str, str]:
    """
    Batch-resolves summary lines for the assigned IPs among the candidates, keyed by IP

    The single summary-line batch every row consumer goes through: the ips-block / sector /
    export shapers call it once per page (or export set) and the assigned_to sort calls it
    over the full candidate list. Collects the distinct owner public_ids referenced by the
    assigned candidates and forwards them to ``ObjectsManager.get_summary_lines_lookup`` in
    one round-trip pair, then maps the resolved summary line back onto every IP that pointed
    at the same owner. Free IPs are skipped silently. Owners that no longer resolve (deleted
    / drifted) leave the IP out of the returned mapping; row shaping renders those as an
    empty summary line while the NULLS-LAST sort treats the missing key as "no value"

    Args:
        candidate_ips (list[str]): Canonical IP strings under consideration
        assigned (dict[str, dict[str, Any]]): {ip_str: row_info} as produced by
            ``load_assigned_rows_map``
        objects_manager (ObjectsManager): db interface for CmdbObjects

    Returns:
        dict[str, str]: {ip_str: summary_line} for every candidate IP whose owner resolved
    """
    owner_ids: list[int] = [
        assigned[ip][AssignedField.OBJECT_ID]
        for ip in candidate_ips
        if ip in assigned and isinstance(assigned[ip].get(AssignedField.OBJECT_ID), int)
    ]

    if not owner_ids:
        return {}

    summaries: dict[int, str] = objects_manager.get_summary_lines_lookup(owner_ids, with_type=True)

    return {
        ip: summaries[assigned[ip][AssignedField.OBJECT_ID]]
        for ip in candidate_ips
        if ip in assigned and assigned[ip].get(AssignedField.OBJECT_ID) in summaries
    }
