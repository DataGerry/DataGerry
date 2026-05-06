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
Validator for VLAN CmdbObjects

Currently confirms only that the referenced subnet object exists and has SpecialType SUBNET
"""
from typing import Any

from cmdb.manager import ObjectsManager, TypesManager
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.framework.ipam.references import resolve_special_type_id
from cmdb.framework.ipam.subnet_validator import build_error
# -------------------------------------------------------------------------------------------------------------------- #


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  ERROR CODES                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class VlanErrorCode:
    """Stable codes for structured vlan validation errors"""
    SUBNET_TYPE_MISSING = 'subnet_type_missing'
    SUBNET_NOT_FOUND = 'subnet_not_found'


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  ORCHESTRATOR                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def validate_vlan(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    subnet_object_id: int,
) -> list[dict[str, Any]]:
    """
    Validates that the subnet referenced by a vlan object actually exists as a SUBNET CmdbObject

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        subnet_object_id (int): public_id of the subnet the vlan references

    Returns:
        list[dict[str, Any]]: Structured validation errors; empty when the reference is valid
    """
    subnet_type_id: int | None = resolve_special_type_id(types_manager, SpecialType.SUBNET)

    if subnet_type_id is None:
        return [build_error(
            VlanErrorCode.SUBNET_TYPE_MISSING,
            "No SUBNET CmdbType is defined; cannot validate vlan subnet reference",
        )]

    matches: list[dict[str, Any]] = objects_manager.find_objects(
        {'public_id': subnet_object_id, 'type_id': subnet_type_id},
        as_dict=True,
    )

    if not matches:
        return [build_error(
            VlanErrorCode.SUBNET_NOT_FOUND,
            f"Subnet object with id {subnet_object_id} does not exist",
            {'subnet_object_id': subnet_object_id},
        )]

    return []
