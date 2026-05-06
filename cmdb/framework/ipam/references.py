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
Reference lookups used by the IPAM deletion guards

Each helper returns a list of lightweight dicts ({'public_id': int, 'type_id': int}) so the
caller can format a 400 response listing the blocking objects without needing to load full
CmdbObjects
"""
from typing import Any

from cmdb.manager import ObjectsManager, TypesManager
from cmdb.models.special_type_model.special_type_enum import SpecialType
# -------------------------------------------------------------------------------------------------------------------- #


def resolve_special_type_id(types_manager: TypesManager, special_type: SpecialType) -> int | None:
    """
    Returns the public_id of the CmdbType marked with the given SpecialType, or None if none exists

    Args:
        types_manager (TypesManager): db interface for CmdbTypes
        special_type (SpecialType): The SpecialType to resolve

    Returns:
        int | None: The CmdbType's public_id, or None if no such CmdbType is defined
    """
    type_doc: dict[str, Any] | None = types_manager.get_one_by({'special_type': special_type})

    if not type_doc:
        return None

    return type_doc.get('public_id')


def _find_objects_with_field_value(
    objects_manager: ObjectsManager,
    type_id: int,
    field_name: str,
    field_value: Any,
) -> list[dict[str, Any]]:
    """
    Returns lightweight dicts for every CmdbObject of the given type whose 'fields' array
    contains an entry with the given name + value

    Uses '$elemMatch' on the top-level 'fields' array

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        type_id (int): The CmdbType's public_id to scope the query to
        field_name (str): The field 'name' to match
        field_value (Any): The field 'value' to match

    Returns:
        list[dict[str, Any]]: One dict per matching CmdbObject with 'public_id' and 'type_id'
    """
    criteria: dict[str, Any] = {
        'type_id': type_id,
        'fields': {
            '$elemMatch': {
                'name': field_name,
                'value': field_value,
            },
        },
    }

    matches: list[dict[str, Any]] = objects_manager.find_objects(criteria, as_dict=True)

    return [{'public_id': m['public_id'], 'type_id': m['type_id']} for m in matches]


def find_subnets_referencing_supernet(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    supernet_object_id: int,
) -> list[dict[str, Any]]:
    """
    Returns subnet CmdbObjects whose 'dg-supernet-ref' points at the given supernet object

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        supernet_object_id (int): public_id of the SUPERNET CmdbObject being checked

    Returns:
        list[dict[str, Any]]: Matching subnet objects as {'public_id', 'type_id'} dicts; empty
            list when no SUBNET CmdbType exists or no subnet references the supernet
    """
    subnet_type_id: int | None = resolve_special_type_id(types_manager, SpecialType.SUBNET)

    if subnet_type_id is None:
        return []

    return _find_objects_with_field_value(objects_manager, subnet_type_id, 'dg-supernet-ref', supernet_object_id)


def find_subnets_referencing_parent_subnet(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    parent_subnet_object_id: int,
) -> list[dict[str, Any]]:
    """
    Returns subnet CmdbObjects whose 'dg-parent-subnet-ref' points at the given subnet object

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        parent_subnet_object_id (int): public_id of the SUBNET CmdbObject being checked

    Returns:
        list[dict[str, Any]]: Matching child subnet objects as {'public_id', 'type_id'} dicts;
            empty list when no SUBNET CmdbType exists or no child references this subnet
    """
    subnet_type_id: int | None = resolve_special_type_id(types_manager, SpecialType.SUBNET)

    if subnet_type_id is None:
        return []

    return _find_objects_with_field_value(
        objects_manager,
        subnet_type_id,
        'dg-parent-subnet-ref',
        parent_subnet_object_id,
    )


def find_vlans_referencing_subnet(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    subnet_object_id: int,
) -> list[dict[str, Any]]:
    """
    Returns vlan CmdbObjects whose 'dg-subnet-ref' points at the given subnet object

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        subnet_object_id (int): public_id of the SUBNET CmdbObject being checked

    Returns:
        list[dict[str, Any]]: Matching vlan objects as {'public_id', 'type_id'} dicts; empty
            list when no VLAN CmdbType exists or no vlan references the subnet
    """
    vlan_type_id: int | None = resolve_special_type_id(types_manager, SpecialType.VLAN)

    if vlan_type_id is None:
        return []

    return _find_objects_with_field_value(objects_manager, vlan_type_id, 'dg-subnet-ref', subnet_object_id)


def find_interfaces_referencing_subnet(
    objects_manager: ObjectsManager,
    subnet_object_id: int,
) -> list[dict[str, Any]]:
    """
    Returns CmdbObjects that have at least one 'dg-ipam-interface' MDS row whose
    'dg-interface-subnet' field points at the given subnet object

    Spans every CmdbType because the dg-ipam-interface section template is global

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        subnet_object_id (int): public_id of the SUBNET CmdbObject being checked

    Returns:
        list[dict[str, Any]]: Matching CmdbObjects as {'public_id', 'type_id'} dicts; empty
            list when no interface row references the subnet
    """
    criteria: dict[str, Any] = {
        'multi_data_sections': {
            '$elemMatch': {
                'values': {
                    '$elemMatch': {
                        'data': {
                            '$elemMatch': {
                                'name': 'dg-interface-subnet',
                                'value': subnet_object_id,
                            },
                        },
                    },
                },
            },
        },
    }

    matches: list[dict[str, Any]] = objects_manager.find_objects(criteria, as_dict=True)

    return [{'public_id': m['public_id'], 'type_id': m['type_id']} for m in matches]
