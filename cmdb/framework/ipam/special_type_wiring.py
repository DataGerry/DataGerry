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
Cross-wiring (and un-wiring) of the IPAM SpecialType reference fields

Whenever a SUPERNET, SUBNET or VLAN SpecialType is created, the reference fields linking them
(Subnet -> Supernet, VLAN -> Subnet) and the 'dg-ipam-interface' section template (-> Subnet) must
have their 'ref_types' lists populated with the new type's public_id. This module owns that wiring
so both the CmdbType REST routes and the DataGerry assistant can apply identical behavior without
the framework layer depending on the interface/route layer.

Deleting a type needs the inverse, split across two functions with no overlap:

* ``cleanup_type_references_from_all_types`` strips the deleted id from **every CmdbType** field that
  references it - one server-side statement, and it covers the materialized copies of section-template
  fields (e.g. 'dg-interface-subnet') because a section template is copied into its host type when the
  section is added;
* ``cleanup_special_type_template_references`` strips it from the **'dg-ipam-interface' section
  template itself**, the one document the type-level sweep cannot reach.

Both the wiring and the un-wiring of that template propagate the change through
``handle_section_template_changes``, so a type that already inlined the section has its stored field
definition refreshed either way.

Only one CmdbType may carry a given SpecialType (enforced by the type routes and the type import), so
looking a SpecialType up with ``get_one_by`` always addresses the one type that exists.
"""
from typing import Any, Callable
import copy

from cmdb.manager import TypesManager, SectionTemplatesManager

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
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
# -------------------------------------------------------------------------------------------------------------------- #

# Mongo path of a field-level 'ref_types' entry inside a CmdbType's 'fields' array, used to select and
# to strip the referencing types in one statement
TYPE_FIELD_REF_TYPES_PATH: str = f'{TypeSchemaKey.FIELDS.value}.{FieldKey.REF_TYPES.value}'
ALL_TYPE_FIELDS_REF_TYPES_PATH: str = f'{TypeSchemaKey.FIELDS.value}.$[].{FieldKey.REF_TYPES.value}'

# -------------------------------------------------------------------------------------------------------------------- #
#                                                     PURE HELPERS                                                     #
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

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   WIRING PRIMITIVES                                                  #
# -------------------------------------------------------------------------------------------------------------------- #

def apply_type_ref_type(
    types_manager: TypesManager,
    criteria: dict[str, Any],
    field_name: str,
    ref_id: int,
) -> bool:
    """
    Adds 'ref_id' to one CmdbType's named reference field and persists the type when it changed

    The single read-mutate-persist step every wiring case is built from. A criteria matching no type,
    a type without that field, or a 'ref_types' list that already carries the id all leave the database
    untouched

    Args:
        types_manager (TypesManager): db interface for CmdbTypes
        criteria (dict[str, Any]): Selects the CmdbType to wire (by SpecialType or by public_id)
        field_name (str): Name of the reference field whose 'ref_types' is extended
        ref_id (int): The CmdbType public_id to add

    Returns:
        bool: True when the type was modified and written, False when nothing had to change
    """
    target_type: dict[str, Any] | None = types_manager.get_one_by(criteria)

    if not target_type:
        return False

    if not ensure_ref_type(target_type[TypeSchemaKey.FIELDS], field_name, ref_id):
        return False

    types_manager.update_type(target_type[TypeSchemaKey.PUBLIC_ID], target_type)

    return True


def get_special_type_id(types_manager: TypesManager, special_type: SpecialType) -> int | None:
    """
    Returns the public_id of the CmdbType carrying the given SpecialType, if one exists

    Args:
        types_manager (TypesManager): db interface for CmdbTypes
        special_type (SpecialType): The SpecialType to look up

    Returns:
        int | None: public_id of the one type carrying it, or None when it does not exist yet
    """
    special_type_document: dict[str, Any] | None = types_manager.get_one_by(
        {TypeSchemaKey.SPECIAL_TYPE: special_type},
    )

    return special_type_document[TypeSchemaKey.PUBLIC_ID] if special_type_document else None


def apply_interface_template_ref_change(
    section_templates_manager: SectionTemplatesManager,
    mutate_fields: Callable[[list[dict[str, Any]]], bool],
) -> bool:
    """
    Applies a 'ref_types' change to the 'dg-ipam-interface' section template and propagates it

    Shared by the wiring and the un-wiring side so both behave identically: the pre-mutation state is
    snapshotted, ``mutate_fields`` decides whether anything changes, and only then is the template
    written and ``handle_section_template_changes`` invoked. That propagation is what refreshes the
    materialized 'dg-interface-subnet' field on every CmdbType that already inlined the section -
    section templates are copied at apply-time and not linked, so without it those types keep the
    stale ref_types

    Args:
        section_templates_manager (SectionTemplatesManager): db interface for section templates
        mutate_fields (Callable[[list[dict[str, Any]]], bool]): Applies the change to the template's
            field list and reports whether it modified anything (see ensure_ref_type / remove_ref_type)

    Returns:
        bool: True when the template was modified and written, False when there was nothing to do
    """
    interface_template: dict[str, Any] | None = section_templates_manager.get_one_by(
        {SectionTemplateKey.NAME: IpamSection.INTERFACE},
    )

    if not interface_template:
        return False

    # Snapshot the pre-mutation state so handle_section_template_changes can diff the template
    # against its prior version when propagating into user types
    current_template_model: CmdbSectionTemplate = CmdbSectionTemplate.from_data(
        copy.deepcopy(interface_template),
    )

    if not mutate_fields(interface_template[SectionTemplateKey.FIELDS]):
        return False

    section_templates_manager.update_section_template(
        interface_template[SectionTemplateKey.PUBLIC_ID], interface_template,
    )
    section_templates_manager.handle_section_template_changes(interface_template, current_template_model)

    return True

# -------------------------------------------------------------------------------------------------------------------- #
#                                                        WIRING                                                        #
# -------------------------------------------------------------------------------------------------------------------- #

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

    Wiring is applied in both directions, because the types can be created in any order: creating a
    SUPERNET points the existing SUBNET at it, and creating a SUBNET points itself at the existing
    SUPERNET. A counterpart that does not exist yet is simply skipped - it will do the wiring itself
    when it is created

    Args:
        types_manager (TypesManager): db interface for CmdbTypes
        special_type (SpecialType): The SpecialType of the CmdbType that triggered the wiring
        section_templates_manager (SectionTemplatesManager): db interface for section templates
        special_type_id (int): public_id of the CmdbType carrying 'special_type'

    Raises:
        TypesManagerGetError / TypesManagerUpdateError / SectionTemplatesManager*Error: Manager errors
            are not handled here; they propagate to the calling route, which maps them to a response
    """
    if special_type == SpecialType.SUPERNET:
        # The existing SUBNET may now reference this SUPERNET
        apply_type_ref_type(
            types_manager,
            {TypeSchemaKey.SPECIAL_TYPE: SpecialType.SUBNET},
            SubnetField.PARENT_SUPERNET,
            special_type_id,
        )

    elif special_type == SpecialType.SUBNET:
        # Interface rows of every type using the IPAM section may now reference this SUBNET
        apply_interface_template_ref_change(
            section_templates_manager,
            lambda fields: ensure_ref_type(fields, InterfaceField.SUBNET, special_type_id),
        )

        # The existing VLAN may now reference this SUBNET
        apply_type_ref_type(
            types_manager,
            {TypeSchemaKey.SPECIAL_TYPE: SpecialType.VLAN},
            VlanField.SUBNET_REF,
            special_type_id,
        )

        # ... and this SUBNET may reference the existing SUPERNET
        supernet_id: int | None = get_special_type_id(types_manager, SpecialType.SUPERNET)

        if supernet_id is not None:
            apply_type_ref_type(
                types_manager,
                {TypeSchemaKey.PUBLIC_ID: special_type_id},
                SubnetField.PARENT_SUPERNET,
                supernet_id,
            )

    elif special_type == SpecialType.VLAN:
        # This VLAN may reference the existing SUBNET
        subnet_id: int | None = get_special_type_id(types_manager, SpecialType.SUBNET)

        if subnet_id is not None:
            apply_type_ref_type(
                types_manager,
                {TypeSchemaKey.PUBLIC_ID: special_type_id},
                VlanField.SUBNET_REF,
                subnet_id,
            )

# --------------------------------------------------- UN-WIRING (CLEANUP) -------------------------------------------- #

def cleanup_type_references_from_all_types(
    types_manager: TypesManager,
    deleted_type_id: int,
) -> int:
    """
    Strips 'deleted_type_id' from every CmdbType field whose 'ref_types' contains it

    Runs after a CmdbType has been deleted. One server-side statement does the whole sweep: the filter
    selects only the types that actually reference the deleted id, and the all-positional ``$[]``
    operator pulls the id out of every field's 'ref_types' array of each matched document - no type is
    loaded into the process and no document is rewritten in full

    Covers both 'ref' and 'ref-section-field' fields as well as any fields materialized from section
    templates (e.g. the IPAM 'dg-ipam-interface' section's 'dg-interface-subnet'), because section
    templates are copied into the host CmdbType's 'fields' list at the moment the section is added. The
    template document itself is not a CmdbType and is handled by
    ``cleanup_special_type_template_references``

    Idempotent: when no CmdbType holds the id, nothing is written and 0 is returned

    Args:
        types_manager (TypesManager): db interface for CmdbTypes
        deleted_type_id (int): public_id of the CmdbType that was just deleted

    Returns:
        int: Number of CmdbTypes whose 'fields' were modified

    Raises:
        BaseManagerUpdateError: If the update fails (propagates to the calling route)
    """
    result = types_manager.update_many_raw(
        filter_query={TYPE_FIELD_REF_TYPES_PATH: deleted_type_id},
        update={'$pull': {ALL_TYPE_FIELDS_REF_TYPES_PATH: deleted_type_id}},
    )

    return result.modified_count


def cleanup_special_type_template_references(
    section_templates_manager: SectionTemplatesManager,
    special_type: SpecialType,
    deleted_type_id: int,
) -> None:
    """
    Removes a deleted SpecialType's id from the 'dg-ipam-interface' section template

    The template is the only document ``cleanup_type_references_from_all_types`` cannot reach (it is
    not a CmdbType), so this is deliberately **template-only**: the CmdbType-level arrays - SUBNET's
    'dg-supernet-ref' and VLAN's 'dg-subnet-ref' - are already covered by that sweep, and doing them
    here again would only repeat the work.

    Only a deleted SUBNET is referenced by the template ('dg-interface-subnet'); SUPERNET and VLAN
    need nothing here. Mirrors the wiring side exactly, propagation included, so a type that inlined
    the IPAM section has its stored field definition refreshed

    Idempotent: no-ops when the template does not exist or does not reference the id

    Args:
        section_templates_manager (SectionTemplatesManager): db interface for section templates
        special_type (SpecialType): SpecialType marker of the CmdbType that was just deleted
        deleted_type_id (int): public_id of the CmdbType that was just deleted

    Raises:
        SectionTemplatesManagerUpdateError: If the template update fails (propagates to the route)
    """
    if special_type != SpecialType.SUBNET:
        return

    apply_interface_template_ref_change(
        section_templates_manager,
        lambda fields: remove_ref_type(fields, InterfaceField.SUBNET, deleted_type_id),
    )
