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
Guards that refuse a SUPERNET / SUBNET object 'dg-network-range' edit when the change would
orphan existing children (subnets) or interface IPs that no longer fit the new range
"""
from ipaddress import IPv4Network
from typing import Any

from cmdb.manager import ObjectsManager, TypesManager
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.framework.ipam.cidr import parse_cidr, parse_ipv4, contains, ip_in_network
from cmdb.framework.ipam.references import resolve_special_type_id
from cmdb.framework.ipam.subnet_validator import build_error, extract_field_value, SUBNET_RANGE_FIELD
from cmdb.framework.ipam.interface_validator import (
    INTERFACE_SECTION_NAME,
    INTERFACE_SUBNET_FIELD,
    INTERFACE_IP_FIELD,
)
# -------------------------------------------------------------------------------------------------------------------- #


SUBNET_PARENT_SUPERNET_FIELD: str = 'dg-supernet-ref'
SUBNET_PARENT_SUBNET_FIELD: str = 'dg-parent-subnet-ref'


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  ERROR CODES                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class RangeChangeErrorCode:
    """Stable codes for structured range-change guard errors"""
    CHILD_SUBNET_OUT_OF_RANGE = 'child_subnet_out_of_range'
    CHILD_INTERFACE_IP_OUT_OF_RANGE = 'child_interface_ip_out_of_range'


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  PURE HELPERS                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def range_changed(previous_value: Any, new_value: Any) -> bool:
    """
    Reports whether the candidate object's network range value differs from the previous one

    Args:
        previous_value (Any): The previously stored 'dg-network-range' value
        new_value (Any): The about-to-be-saved 'dg-network-range' value

    Returns:
        bool: True when the two values are not equal, False otherwise
    """
    return previous_value != new_value


# -------------------------------------------------------------------------------------------------------------------- #
#                                                CHILD ENUMERATIONS                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def _find_child_subnets_of_supernet(
    objects_manager: ObjectsManager,
    subnet_type_id: int,
    supernet_object_id: int,
) -> list[dict[str, Any]]:
    """
    Returns subnet documents whose 'dg-supernet-ref' is the given supernet

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        subnet_type_id (int): public_id of the SUBNET CmdbType
        supernet_object_id (int): public_id of the supernet whose children we enumerate

    Returns:
        list[dict[str, Any]]: Full subnet documents (with their 'fields' array)
    """
    return objects_manager.find_objects(
        {
            'type_id': subnet_type_id,
            'fields': {'$elemMatch': {'name': SUBNET_PARENT_SUPERNET_FIELD, 'value': supernet_object_id}},
        },
        as_dict=True,
    )


def _find_child_subnets_of_subnet(
    objects_manager: ObjectsManager,
    subnet_type_id: int,
    parent_subnet_object_id: int,
) -> list[dict[str, Any]]:
    """
    Returns subnet documents whose 'dg-parent-subnet-ref' is the given subnet

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        subnet_type_id (int): public_id of the SUBNET CmdbType
        parent_subnet_object_id (int): public_id of the parent subnet whose children we enumerate

    Returns:
        list[dict[str, Any]]: Full subnet documents (with their 'fields' array)
    """
    return objects_manager.find_objects(
        {
            'type_id': subnet_type_id,
            'fields': {'$elemMatch': {'name': SUBNET_PARENT_SUBNET_FIELD, 'value': parent_subnet_object_id}},
        },
        as_dict=True,
    )


def _find_objects_with_interface_to_subnet(
    objects_manager: ObjectsManager,
    subnet_object_id: int,
) -> list[dict[str, Any]]:
    """
    Returns full CmdbObject documents that have at least one dg-ipam-interface MDS row
    referencing the given subnet

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        subnet_object_id (int): public_id of the subnet whose attached interfaces we enumerate

    Returns:
        list[dict[str, Any]]: Full object documents (with their 'multi_data_sections' array)
    """
    return objects_manager.find_objects(
        {
            'multi_data_sections': {
                '$elemMatch': {
                    'name': INTERFACE_SECTION_NAME,
                    'values': {
                        '$elemMatch': {
                            'data': {
                                '$elemMatch': {
                                    'name': INTERFACE_SUBNET_FIELD,
                                    'value': subnet_object_id,
                                },
                            },
                        },
                    },
                },
            },
        },
        as_dict=True,
    )


# -------------------------------------------------------------------------------------------------------------------- #
#                                                FIT CHECKS                                                            #
# -------------------------------------------------------------------------------------------------------------------- #
def _check_subnet_children_fit(
    children: list[dict[str, Any]],
    new_range: IPv4Network,
    parent_object_id: int,
) -> list[dict[str, Any]]:
    """
    Reports each child subnet whose 'dg-network-range' is no longer contained in the new range

    Args:
        children (list[dict[str, Any]]): Full child subnet documents
        new_range (IPv4Network): The proposed new range of the parent
        parent_object_id (int): public_id of the parent (for error context)

    Returns:
        list[dict[str, Any]]: One error per child that no longer fits
    """
    errors: list[dict[str, Any]] = []

    for child in children:
        raw: Any = extract_field_value(child, SUBNET_RANGE_FIELD)
        child_net: IPv4Network | None = parse_cidr(raw) if isinstance(raw, str) else None

        if child_net is None or contains(new_range, child_net):
            continue

        errors.append(build_error(
            RangeChangeErrorCode.CHILD_SUBNET_OUT_OF_RANGE,
            f"Child subnet {child.get('public_id')} ({child_net}) would no longer fit in new range {new_range}",
            {
                'parent_object_id': parent_object_id,
                'child_subnet_id': child.get('public_id'),
                'child_range': str(child_net),
                'new_range': str(new_range),
            },
        ))

    return errors


def _check_interface_ips_fit(
    objects_with_interfaces: list[dict[str, Any]],
    new_range: IPv4Network,
    subnet_object_id: int,
) -> list[dict[str, Any]]:
    """
    Reports each interface row whose IP no longer fits the new range of the referenced subnet

    Args:
        objects_with_interfaces (list[dict[str, Any]]): Full CmdbObject docs holding interface rows
        new_range (IPv4Network): The proposed new range of the subnet
        subnet_object_id (int): public_id of the subnet being changed (for error context)

    Returns:
        list[dict[str, Any]]: One error per offending interface row
    """
    errors: list[dict[str, Any]] = []

    for obj in objects_with_interfaces:
        for section in obj.get('multi_data_sections', []) or []:
            if section.get('name') != INTERFACE_SECTION_NAME:
                continue

            for row_index, row in enumerate(section.get('values', []) or []):
                row_subnet, row_ip_raw = _extract_interface_subnet_and_ip(row)

                if row_subnet != subnet_object_id or not isinstance(row_ip_raw, str):
                    continue

                ip = parse_ipv4(row_ip_raw)

                if ip is None or ip_in_network(ip, new_range):
                    continue

                errors.append(build_error(
                    RangeChangeErrorCode.CHILD_INTERFACE_IP_OUT_OF_RANGE,
                    f"Interface IP {ip} on object {obj.get('public_id')} (row {row_index}) "
                    f"would no longer fit in new subnet range {new_range}",
                    {
                        'subnet_object_id': subnet_object_id,
                        'object_id': obj.get('public_id'),
                        'row_index': row_index,
                        'ip_address': str(ip),
                        'new_range': str(new_range),
                    },
                ))

    return errors


def _extract_interface_subnet_and_ip(row: dict[str, Any]) -> tuple[Any, Any]:
    """
    Reads the (subnet_ref, ip_address) pair from one dg-ipam-interface MDS row

    Args:
        row (dict[str, Any]): One entry from an MDS section's 'values' list

    Returns:
        tuple[Any, Any]: (subnet ref value, ip value); either may be None when absent
    """
    subnet_value: Any = None
    ip_value: Any = None

    for entry in row.get('data', []) or []:
        name: Any = entry.get('name')
        if name == INTERFACE_SUBNET_FIELD:
            subnet_value = entry.get('value')
        elif name == INTERFACE_IP_FIELD:
            ip_value = entry.get('value')

    return subnet_value, ip_value


# -------------------------------------------------------------------------------------------------------------------- #
#                                                ORCHESTRATORS                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
def check_supernet_range_change(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    supernet_object_id: int,
    new_range_value: Any,
) -> list[dict[str, Any]]:
    """
    Validates that changing a supernet's range to 'new_range_value' would not orphan existing
    child subnets

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        supernet_object_id (int): public_id of the supernet being edited
        new_range_value (Any): The proposed new 'dg-network-range' value

    Returns:
        list[dict[str, Any]]: Errors per orphaned child; empty when the change is safe
    """
    new_range: IPv4Network | None = parse_cidr(new_range_value) if isinstance(new_range_value, str) else None

    if new_range is None:
        return []

    subnet_type_id: int | None = resolve_special_type_id(types_manager, SpecialType.SUBNET)

    if subnet_type_id is None:
        return []

    children: list[dict[str, Any]] = _find_child_subnets_of_supernet(
        objects_manager, subnet_type_id, supernet_object_id,
    )

    return _check_subnet_children_fit(children, new_range, supernet_object_id)


def check_subnet_range_change(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    subnet_object_id: int,
    new_range_value: Any,
) -> list[dict[str, Any]]:
    """
    Validates that changing a subnet's range to 'new_range_value' would not orphan existing
    child subnets or interface IPs

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        subnet_object_id (int): public_id of the subnet being edited
        new_range_value (Any): The proposed new 'dg-network-range' value

    Returns:
        list[dict[str, Any]]: Errors per orphaned child or interface; empty when safe
    """
    new_range: IPv4Network | None = parse_cidr(new_range_value) if isinstance(new_range_value, str) else None

    if new_range is None:
        return []

    errors: list[dict[str, Any]] = []

    subnet_type_id: int | None = resolve_special_type_id(types_manager, SpecialType.SUBNET)

    if subnet_type_id is not None:
        children: list[dict[str, Any]] = _find_child_subnets_of_subnet(
            objects_manager, subnet_type_id, subnet_object_id,
        )
        errors.extend(_check_subnet_children_fit(children, new_range, subnet_object_id))

    interface_objs: list[dict[str, Any]] = _find_objects_with_interface_to_subnet(
        objects_manager, subnet_object_id,
    )
    errors.extend(_check_interface_ips_fit(interface_objs, new_range, subnet_object_id))

    return errors
