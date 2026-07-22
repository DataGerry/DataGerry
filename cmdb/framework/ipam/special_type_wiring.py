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

from cmdb.models.object_model import CmdbObjectKey
from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.models.section_template_model.section_template_constants import SectionTemplateKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import (
    SubnetField,
    VlanField,
    InterfaceField,
    IpamSection,
)
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.section_key_enum import SectionKey
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
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
        if field.get(FieldKey.NAME) == field_name:
            ref_types: list[int] = field.setdefault(FieldKey.REF_TYPES, [])

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
        subnet_type: dict[str, Any] | None = types_manager.get_one_by(
            {TypeSchemaKey.SPECIAL_TYPE: SpecialType.SUBNET},
        )

        if not subnet_type:
            return

        updated: bool = ensure_ref_type(
            subnet_type[TypeSchemaKey.FIELDS], SubnetField.PARENT_SUPERNET, special_type_id,
        )

        if updated:
            types_manager.update_type(subnet_type[CmdbObjectKey.PUBLIC_ID], subnet_type)

    elif special_type == SpecialType.SUBNET:
        interface_template: dict[str, Any] | None = section_templates_manager.get_one_by(
            {SectionKey.NAME: IpamSection.INTERFACE}
        )

        if interface_template:
            # Snapshot the pre-mutation state so handle_section_template_changes can diff
            # the template against its prior version when propagating into user types
            current_template_model: CmdbSectionTemplate = CmdbSectionTemplate.from_data(
                copy.deepcopy(interface_template),
            )

            tpl_updated: bool = ensure_ref_type(
                interface_template[SectionKey.FIELDS], InterfaceField.SUBNET, special_type_id,
            )

            if tpl_updated:
                section_templates_manager.update_section_template(
                    interface_template[CmdbObjectKey.PUBLIC_ID], interface_template,
                )
                # Propagate the new ref_types into every CmdbType that has already
                # inlined the 'dg-ipam-interface' section; section templates are
                # copied at apply-time, so without this call the materialized
                # 'dg-interface-subnet' field on those types keeps the stale
                # (or empty) ref_types from the moment the section was added
                section_templates_manager.handle_section_template_changes(
                    interface_template, current_template_model,
                )

        vlan_type: dict[str, Any] | None = types_manager.get_one_by(
            {TypeSchemaKey.SPECIAL_TYPE: SpecialType.VLAN},
        )

        if vlan_type:
            vlan_updated: bool = ensure_ref_type(
                vlan_type[TypeSchemaKey.FIELDS], VlanField.SUBNET_REF, special_type_id,
            )

            if vlan_updated:
                types_manager.update_type(vlan_type[CmdbObjectKey.PUBLIC_ID], vlan_type)

        supernet_type: dict[str, Any] | None = types_manager.get_one_by(
            {TypeSchemaKey.SPECIAL_TYPE: SpecialType.SUPERNET},
        )

        if not supernet_type:
            return

        subnet_type: dict[str, Any] | None = types_manager.get_one_by(
            {CmdbObjectKey.PUBLIC_ID: special_type_id},
        )

        if not subnet_type:
            return

        if ensure_ref_type(
            subnet_type[TypeSchemaKey.FIELDS],
            SubnetField.PARENT_SUPERNET,
            supernet_type[CmdbObjectKey.PUBLIC_ID],
        ):
            types_manager.update_type(special_type_id, subnet_type)

    elif special_type == SpecialType.VLAN:
        subnet_type: dict[str, Any] | None = types_manager.get_one_by(
            {TypeSchemaKey.SPECIAL_TYPE: SpecialType.SUBNET},
        )

        if not subnet_type:
            return

        vlan_type: dict[str, Any] | None = types_manager.get_one_by(
            {CmdbObjectKey.PUBLIC_ID: special_type_id},
        )

        if not vlan_type:
            return

        updated = ensure_ref_type(
            vlan_type[TypeSchemaKey.FIELDS], VlanField.SUBNET_REF, subnet_type[CmdbObjectKey.PUBLIC_ID],
        )

        if updated:
            types_manager.update_type(vlan_type[CmdbObjectKey.PUBLIC_ID], vlan_type)

# --------------------------------------------------- UN-WIRING (CLEANUP) -------------------------------------------- #

def remove_ref_type(fields: list[dict[str, Any]], field_name: str, ref_id: int) -> bool:
    """
    Removes ref_id from field.ref_types if present

    Mirror of ensure_ref_type for cleanup paths. Idempotent: returns False when the field
    does not exist on the given list, when the field has no 'ref_types' list, or when
    'ref_id' is not in 'ref_types'

    Args:
        fields (list[dict[str, Any]]): The CmdbType / section-template field list to mutate
        field_name (str): The target field's 'name'
        ref_id (int): The CmdbType public_id to drop from 'ref_types'

    Returns:
        bool: True when 'ref_types' was modified, False otherwise
    """
    for field in fields:
        if field.get(FieldKey.NAME) == field_name:
            ref_types: Any = field.get(FieldKey.REF_TYPES)

            if isinstance(ref_types, list) and ref_id in ref_types:
                ref_types.remove(ref_id)
                return True

            return False

    return False


def cleanup_type_references_from_all_types(
    types_manager: TypesManager,
    deleted_type_id: int,
) -> int:
    """
    Strips 'deleted_type_id' from every CmdbType field whose 'ref_types' contains it

    Runs after a CmdbType has been deleted: walks every other CmdbType that still
    has the deleted id in any of its fields' 'ref_types' arrays, removes the id
    in place, and persists the change. Uses a targeted Mongo query so only types
    that actually reference the deleted id are pulled from the database

    Covers both 'ref' and 'ref-section-field' fields as well as any fields
    materialized from section templates (e.g. the IPAM 'dg-ipam-interface'
    section's 'dg-interface-subnet'), because section templates are copied into
    the host CmdbType's 'fields' list at the moment the section is added

    Idempotent: when no candidate CmdbTypes still hold the id, returns 0 and
    writes nothing

    Args:
        types_manager (TypesManager): db interface for CmdbTypes
        deleted_type_id (int): public_id of the CmdbType that was just deleted

    Returns:
        int: Number of CmdbTypes whose 'fields' were modified and persisted
    """
    candidates: list[dict[str, Any]] = types_manager.find(
        criteria={f'{TypeSchemaKey.FIELDS.value}.{FieldKey.REF_TYPES.value}': deleted_type_id},
    )

    updated_count: int = 0

    for candidate in candidates:
        changed: bool = False

        for field in candidate.get(TypeSchemaKey.FIELDS, []) or []:
            ref_types: Any = field.get(FieldKey.REF_TYPES)

            if isinstance(ref_types, list) and deleted_type_id in ref_types:
                ref_types.remove(deleted_type_id)
                changed = True

        if changed:
            types_manager.update_type(candidate[TypeSchemaKey.PUBLIC_ID], candidate)
            updated_count += 1

    return updated_count


def cleanup_special_type_references(
    types_manager: TypesManager,
    section_templates_manager: SectionTemplatesManager,
    special_type: str,
    deleted_type_id: int,
) -> None:
    """
    Inverse of handle_special_types: removes 'deleted_type_id' from any 'ref_types' arrays
    that handle_special_types would have populated for the given SpecialType

    SUPERNET: drops the id from SUBNET's 'dg-supernet-ref'.
    SUBNET:   drops the id from VLAN's 'dg-subnet-ref' and the 'dg-ipam-interface' section
              template's 'dg-interface-subnet'.
    VLAN:     no schema points at VLAN, no cleanup required.

    Idempotent: silently no-ops when the cross-wired CmdbTypes / section template do not
    exist, or when 'deleted_type_id' is not present in their 'ref_types'

    Args:
        types_manager (TypesManager): db interface for CmdbTypes
        section_templates_manager (SectionTemplatesManager): db interface for section templates
        special_type (str): SpecialType marker of the CmdbType that was just deleted
        deleted_type_id (int): public_id of the CmdbType that was just deleted
    """
    if special_type == SpecialType.SUPERNET:
        subnet_type: dict[str, Any] | None = types_manager.get_one_by(
            {TypeSchemaKey.SPECIAL_TYPE: SpecialType.SUBNET},
        )

        if subnet_type and remove_ref_type(
            subnet_type[TypeSchemaKey.FIELDS], SubnetField.PARENT_SUPERNET, deleted_type_id,
        ):
            types_manager.update_type(subnet_type[TypeSchemaKey.PUBLIC_ID], subnet_type)

    elif special_type == SpecialType.SUBNET:
        vlan_type: dict[str, Any] | None = types_manager.get_one_by(
            {TypeSchemaKey.SPECIAL_TYPE: SpecialType.VLAN},
        )

        if vlan_type and remove_ref_type(vlan_type[TypeSchemaKey.FIELDS], VlanField.SUBNET_REF, deleted_type_id):
            types_manager.update_type(vlan_type[TypeSchemaKey.PUBLIC_ID], vlan_type)

        interface_template: dict[str, Any] | None = section_templates_manager.get_one_by(
            {SectionTemplateKey.NAME: IpamSection.INTERFACE},
        )

        if interface_template and remove_ref_type(
            interface_template[SectionTemplateKey.FIELDS], InterfaceField.SUBNET, deleted_type_id,
        ):
            section_templates_manager.update_section_template(
                interface_template[SectionTemplateKey.PUBLIC_ID],
                interface_template,
            )
