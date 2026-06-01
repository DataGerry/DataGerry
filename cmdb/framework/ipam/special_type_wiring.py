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
Cross-wiring of the IPAM SpecialType reference fields

Whenever a SUPERNET, SUBNET or VLAN SpecialType is created, the reference fields linking them
(Subnet -> Supernet, VLAN -> Subnet) and the 'dg-ipam-interface' section template (-> Subnet) must
have their 'ref_types' lists populated with the new type's public_id. This module owns that wiring
so both the CmdbType REST routes and the DataGerry assistant can apply identical behavior without
the framework layer depending on the interface/route layer.
"""
from logging import Logger, getLogger
from typing import Any
import copy

from cmdb.manager import TypesManager, SectionTemplatesManager

from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import (
    SubnetField,
    VlanField,
    InterfaceField,
    IpamSection,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

def ensure_ref_type(fields: list[dict[str, Any]], field_name: str, ref_id: int) -> bool:
    """
    Ensures 'ref_id' is present in the named field's 'ref_types' list

    Mutates the matching field's 'ref_types' in place, creating an empty list when missing.
    Idempotent: returns False when the field does not exist or the id is already present, so
    callers can branch on the return to decide whether a persist is required

    Args:
        fields (list[dict[str, Any]]): The CmdbType / section-template field list to mutate
        field_name (str): The target field's 'name'
        ref_id (int): The CmdbType public_id to add to 'ref_types'

    Returns:
        bool: True when 'ref_types' was modified, False otherwise
    """
    for field in fields:
        if field.get('name') == field_name:
            ref_types: list[int] = field.setdefault('ref_types', [])

            if ref_id not in ref_types:
                ref_types.append(ref_id)
                return True

            return False

    return False


def handle_special_types(
    types_manager: TypesManager,
    special_type: SpecialType,
    section_templates_manager: SectionTemplatesManager,
    special_type_id: int
) -> None:
    """
    Cross-wires the reference fields of IPAM SpecialTypes (SUPERNET, SUBNET, VLAN) and the
    'dg-ipam-interface' section template so their 'ref_types' lists include each newly created
    or updated SpecialType. Idempotent: no write happens when 'ref_types' is already correct

    When the SUBNET case mutates the 'dg-ipam-interface' section template, the propagation
    hook 'handle_section_template_changes' is invoked afterwards so every CmdbType that has
    already inlined the section gets its materialized 'dg-interface-subnet' field's
    'ref_types' refreshed. Without that step a SUBNET created (or recreated) after a user
    type already attached the IPAM interface section would never reach the type's stored
    field definition, since section templates are copied at apply-time and not linked

    Args:
        types_manager (TypesManager): db interface for CmdbTypes
        special_type (SpecialType): The SpecialType of the CmdbType that triggered the wiring
        section_templates_manager (SectionTemplatesManager): db interface for section templates
        special_type_id (int): public_id of the CmdbType carrying 'special_type'
    """
    if special_type == SpecialType.SUPERNET:
        subnet_type: dict[str, Any] | None = types_manager.get_one_by({'special_type': SpecialType.SUBNET})

        if not subnet_type:
            return

        updated: bool = ensure_ref_type(subnet_type['fields'], SubnetField.PARENT_SUPERNET, special_type_id)

        if updated:
            types_manager.update_type(subnet_type['public_id'], subnet_type)

    elif special_type == SpecialType.SUBNET:
        interface_template: dict[str, Any] | None = section_templates_manager.get_one_by(
            {'name': IpamSection.INTERFACE}
        )

        if interface_template:
            # Snapshot the pre-mutation state so handle_section_template_changes can diff
            # the template against its prior version when propagating into user types
            current_template_model: CmdbSectionTemplate = CmdbSectionTemplate.from_data(
                copy.deepcopy(interface_template),
            )

            tpl_updated: bool = ensure_ref_type(interface_template['fields'], InterfaceField.SUBNET, special_type_id)

            if tpl_updated:
                section_templates_manager.update_section_template(interface_template["public_id"], interface_template)
                # Propagate the new ref_types into every CmdbType that has already
                # inlined the 'dg-ipam-interface' section; section templates are
                # copied at apply-time, so without this call the materialized
                # 'dg-interface-subnet' field on those types keeps the stale
                # (or empty) ref_types from the moment the section was added
                section_templates_manager.handle_section_template_changes(
                    interface_template, current_template_model,
                )

        vlan_type: dict[str, Any] | None = types_manager.get_one_by({'special_type': SpecialType.VLAN})

        if vlan_type:
            vlan_updated: bool = ensure_ref_type(vlan_type['fields'], VlanField.SUBNET_REF, special_type_id)

            if vlan_updated:
                types_manager.update_type(vlan_type['public_id'], vlan_type)

        supernet_type: dict[str, Any] | None = types_manager.get_one_by({'special_type': SpecialType.SUPERNET})

        if not supernet_type:
            return

        subnet_type: dict[str, Any] | None = types_manager.get_one_by({'public_id': special_type_id})

        if not subnet_type:
            return

        if ensure_ref_type(subnet_type['fields'], SubnetField.PARENT_SUPERNET, supernet_type['public_id']):
            types_manager.update_type(special_type_id, subnet_type)

    elif special_type == SpecialType.VLAN:
        subnet_type: dict[str, Any] | None = types_manager.get_one_by({'special_type': SpecialType.SUBNET})

        if not subnet_type:
            return

        vlan_type: dict[str, Any] | None = types_manager.get_one_by({'public_id': special_type_id})

        if not vlan_type:
            return

        updated = ensure_ref_type(vlan_type['fields'], VlanField.SUBNET_REF, subnet_type['public_id'])

        if updated:
            types_manager.update_type(vlan_type['public_id'], vlan_type)
