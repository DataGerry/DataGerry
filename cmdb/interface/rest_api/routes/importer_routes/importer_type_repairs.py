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
The repairs a CmdbType import applies to an uploaded entry instead of refusing it

These cover the parts of an upload that say nothing about its quality: values a type simply may omit,
and ids / names that belonged to the system the type was exported from and mean nothing here.
`normalize_imported_type` runs all of them, on the create and the update path alike, after the rules
in `importer_type_rules` have passed and before the entry is written

Three of them read the database - cross-type references, ACL groups and global section templates -
each with a single query per entry
"""
from copy import deepcopy
from typing import Any
from logging import Logger, getLogger

from cmdb.manager import TypesManager, SectionTemplatesManager

from cmdb.models.type_model import (
    CmdbType,
    TypeSchemaKey,
    FieldKey,
    SectionKey,
    SectionReferenceKey,
    SectionType,
)
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.section_template_model.section_template_constants import SectionTemplateKey
from cmdb.utils import random_hex_color, is_non_blank_string
from cmdb.security.acl.acl_constants import AclKey
from cmdb.interface.rest_api.routes.importer_routes.importer_type_rules import (
    TypeStructure,
    read_type_structure,
)
from cmdb.interface.rest_api.routes.importer_routes.importer_type_constants import (
    DEFAULT_TYPE_ICON,
    DEFAULT_TYPE_ACL,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #


def strip_uploaded_public_id(type_entry: Any) -> None:
    """
    Drops the public_id an uploaded type carries, in place

    On the create path the public_id is server-owned: a fresh one is assigned from this system's
    counter, so the id of the system the type was exported from is meaningless here and is removed
    before anything else looks at the entry. The update path keeps it - there it identifies the type
    being replaced

    Args:
        type_entry (Any): A single entry of the uploaded payload, modified in place
    """
    if isinstance(type_entry, dict):
        type_entry.pop(TypeSchemaKey.PUBLIC_ID.value, None)


def apply_type_defaults(type_entry: Any) -> None:
    """
    Fills in the optional top-level values an upload may omit, in place

    None of these say anything about the quality of the upload, so they are defaulted rather than
    reported:

    * `label` - always shown in the UI, so a type without one falls back to a title-cased name
      (what CmdbType itself does)
    * `version` - server-owned, forced to the initial version like the object import does. On the
      update path the stored version wins instead: the field is in IMPORT_UPDATE_PRESERVED_FIELDS,
      so it is dropped from the payload again and the `$set` never touches it
    * `ci_explorer_label` - None, i.e. the CI Explorer falls back to the type label
    * `ci_explorer_color` - a random '#RRGGBB' color, so the type is distinguishable in the graph
    * `acl` - the "no access control" ACL every newly created type starts with

    Args:
        type_entry (Any): A single entry of the uploaded payload, modified in place
    """
    if not isinstance(type_entry, dict):
        return

    if not is_non_blank_string(type_entry.get(TypeSchemaKey.LABEL.value)):
        name = type_entry.get(TypeSchemaKey.NAME.value)
        type_entry[TypeSchemaKey.LABEL.value] = name.title() if isinstance(name, str) else name

    type_entry[TypeSchemaKey.VERSION.value] = CmdbType.DEFAULT_VERSION

    type_entry.setdefault(TypeSchemaKey.CI_EXPLORER_LABEL.value, None)

    if not type_entry.get(TypeSchemaKey.CI_EXPLORER_COLOR.value):
        type_entry[TypeSchemaKey.CI_EXPLORER_COLOR.value] = random_hex_color()

    if not type_entry.get(TypeSchemaKey.ACL.value):
        type_entry[TypeSchemaKey.ACL.value] = deepcopy(DEFAULT_TYPE_ACL)


def apply_render_meta_defaults(type_entry: Any) -> None:
    """
    Fills in the presentation values an upload may omit, in place

    Currently only the icon: a type without one is rendered with no symbol at all in the type list,
    the object tables and the CI explorer, so DEFAULT_TYPE_ICON is stamped in as a neutral placeholder
    the user can change afterwards. An icon the upload does bring is never touched

    Args:
        type_entry (Any): A single entry of the uploaded payload, modified in place
    """
    if not isinstance(type_entry, dict):
        return

    render_meta = type_entry.get(TypeSchemaKey.RENDER_META.value)

    if not isinstance(render_meta, dict):
        render_meta = {}
        type_entry[TypeSchemaKey.RENDER_META.value] = render_meta

    if not is_non_blank_string(render_meta.get(TypeSchemaKey.ICON.value)):
        render_meta[TypeSchemaKey.ICON.value] = DEFAULT_TYPE_ICON


def _referenced_type_ids(structure: TypeStructure) -> set[int]:
    """
    Collects the public_ids of the other CmdbTypes an uploaded type points at

    Two places reference a type by public_id: a ref-section's `reference.type_id`, and the `ref_types`
    list of a reference field

    Args:
        structure (TypeStructure): The resolved structure of the uploaded type

    Returns:
        set[int]: The referenced CmdbType public_ids (empty when the type references none)
    """
    referenced: set[int] = set()

    for _, section in structure.sections:
        reference = section.get(SectionKey.REFERENCE.value)

        if isinstance(reference, dict):
            type_id = reference.get(SectionReferenceKey.TYPE_ID.value)

            if isinstance(type_id, int) and not isinstance(type_id, bool):
                referenced.add(type_id)

    for _, field in structure.fields:
        for type_id in field.get(FieldKey.REF_TYPES.value) or []:
            if isinstance(type_id, int) and not isinstance(type_id, bool):
                referenced.add(type_id)

    return referenced


def clear_dangling_type_references(type_entry: Any, types_manager: TypesManager) -> list[int]:
    """
    Clears cross-type references pointing at a CmdbType that does not exist on this system, in place

    A `reference.type_id` and the entries of a reference field's `ref_types` are public_ids of the
    system the type was exported from, so after a cross-system import they usually point at a
    different type or at nothing at all. Rather than refusing the whole type - which would make almost
    every exported type with a reference unimportable - the dangling ids are dropped: a ref-section is
    reset to the unconfigured shape the type builder creates for a new one, and unresolvable entries
    are removed from `ref_types`. The user then re-points them here

    All ids are resolved with a single existence query, so a type with references costs one extra read

    Args:
        type_entry (Any): A single entry of the uploaded payload, modified in place
        types_manager (TypesManager): Manager used to resolve the referenced public_ids

    Raises:
        TypesManagerGetError: If the existence lookup fails

    Returns:
        list[int]: The dangling public_ids that were cleared, sorted (empty when all of them resolved)
    """
    if not isinstance(type_entry, dict):
        return []

    structure = read_type_structure(type_entry)
    referenced = _referenced_type_ids(structure)

    if not referenced:
        return []

    dangling = referenced - types_manager.get_existing_type_ids(sorted(referenced))

    if not dangling:
        return []

    for _, section in structure.sections:
        reference = section.get(SectionKey.REFERENCE.value)

        if isinstance(reference, dict) and reference.get(SectionReferenceKey.TYPE_ID.value) in dangling:
            section[SectionKey.REFERENCE.value] = {
                SectionReferenceKey.TYPE_ID.value: None,
                SectionReferenceKey.SECTION_NAME.value: None,
                SectionReferenceKey.SELECTED_FIELDS.value: [],
            }

    for _, field in structure.fields:
        ref_types = field.get(FieldKey.REF_TYPES.value)

        if isinstance(ref_types, list):
            field[FieldKey.REF_TYPES.value] = [
                type_id for type_id in ref_types if type_id not in dangling
            ]

    LOGGER.info(
        "[clear_dangling_type_references] Cleared references to unknown Type(s) %s while importing '%s'",
        sorted(dangling), type_entry.get(TypeSchemaKey.NAME.value),
    )

    return sorted(dangling)


def clear_dangling_acl_groups(type_entry: Any, types_manager: TypesManager) -> list[Any]:
    """
    Drops ACL entries naming a CmdbUserGroup that does not exist on this system, in place

    `acl.groups.includes` is keyed by group public_id, and those ids belong to the system the type was
    exported from. Left as they are, an entry would silently grant (or withhold) access to whichever
    group happens to hold that id here - a permission decision nobody made. Unresolvable ids are
    therefore dropped; the groups that do exist keep their permissions

    Args:
        type_entry (Any): A single entry of the uploaded payload, modified in place
        types_manager (TypesManager): Manager used to read the groups collection

    Raises:
        BaseManagerGetError: If the group lookup fails

    Returns:
        list[Any]: The dropped group keys, sorted (empty when every group resolved)
    """
    if not isinstance(type_entry, dict):
        return []

    acl = type_entry.get(TypeSchemaKey.ACL.value)
    groups = acl.get(AclKey.GROUPS.value) if isinstance(acl, dict) else None
    includes = groups.get(AclKey.INCLUDES.value) if isinstance(groups, dict) else None

    if not isinstance(includes, dict) or not includes:
        return []

    # The keys are group public_ids, stringified by JSON / BSON; anything unparsable cannot resolve
    wanted: dict[Any, int] = {}

    for key in includes:
        try:
            wanted[key] = int(key)
        except (TypeError, ValueError):
            wanted[key] = -1  # never a public_id, so the entry is dropped below

    existing_rows = types_manager.get_many_from_other_collection(
        CmdbUserGroup.COLLECTION,
        **{TypeSchemaKey.PUBLIC_ID.value: {'$in': sorted(set(wanted.values()))}},
    )
    existing_ids = {row.get(TypeSchemaKey.PUBLIC_ID.value) for row in existing_rows}
    dangling = sorted(str(key) for key, group_id in wanted.items() if group_id not in existing_ids)

    if not dangling:
        return []

    for key in list(includes):
        if wanted[key] not in existing_ids:
            includes.pop(key)

    LOGGER.info(
        "[clear_dangling_acl_groups] Dropped ACL entries for unknown group(s) %s while importing '%s'",
        dangling, type_entry.get(TypeSchemaKey.NAME.value),
    )

    return dangling


def deactivate_empty_acl(type_entry: Any) -> bool:
    """
    Switches an access control list that grants nothing off, in place

    An ACL with `activated: true` and no group in `includes` denies EVERY group: `has_access_control`
    asks the list whether the user's group is granted the permission, and an empty list answers no to
    all of them. A Type imported that way would be invisible to everyone. That state is reached
    without anybody deciding it - either the upload already carried it, or
    `clear_dangling_acl_groups` just dropped the last grant because it named a group of the exporting
    system - so the list is switched off instead, which is what "no access rules" means everywhere
    else in DataGerry

    Args:
        type_entry (Any): A single entry of the uploaded payload, modified in place

    Returns:
        bool: True when the ACL was switched off, False when it was left as it is
    """
    if not isinstance(type_entry, dict):
        return False

    acl = type_entry.get(TypeSchemaKey.ACL.value)

    if not isinstance(acl, dict) or not acl.get(AclKey.ACTIVATED.value):
        return False

    groups = acl.get(AclKey.GROUPS.value)
    includes = groups.get(AclKey.INCLUDES.value) if isinstance(groups, dict) else None

    if includes:
        return False

    acl[AclKey.ACTIVATED.value] = False

    LOGGER.info(
        "[deactivate_empty_acl] Switched off the access control list of '%s': it granted no group",
        type_entry.get(TypeSchemaKey.NAME.value),
    )

    return True


def reconcile_global_templates(
    type_entry: Any,
    section_templates_manager: SectionTemplatesManager,
) -> None:
    """
    Aligns the uploaded type with the global section templates it claims, in place

    `global_template_ids` holds the NAMES of the global section templates a type inlined, and each of
    them owns the section of the same name plus that section's field definitions. Across systems the
    two sides drift, so both directions are repaired:

    * a template that does not exist here is dropped from `global_template_ids` - the inlined section
      and its fields stay, they are real data, but the type stops claiming a template nobody has
    * a template that does exist tops the type up with the template fields it is missing: the field
      definition is added to `fields` and its name to the template's section (the section is created
      from the template when the type does not carry it at all)

    A field the type already defines under that name is never touched - a name identifies exactly one
    field, so the type's own definition wins and the template's copy is skipped. A claim listed twice
    is kept once

    Note the section is only ever created alongside a field that was just added: when the type already
    carries every field of a template it claims but no section named after it, those fields are by
    definition assigned to some other section (an unassigned field never gets this far - the rules
    reject it), so adding the template's section would claim them twice

    Args:
        type_entry (Any): A single entry of the uploaded payload, modified in place
        section_templates_manager (SectionTemplatesManager): Manager used to read the templates

    Raises:
        BaseManagerGetError: If the template lookup fails
    """
    if not isinstance(type_entry, dict):
        return

    # dict.fromkeys keeps the first occurrence of a name and drops the repeats, order intact
    claimed = list(dict.fromkeys(
        name for name in type_entry.get(TypeSchemaKey.GLOBAL_TEMPLATE_IDS.value) or []
        if isinstance(name, str)
    ))

    if not claimed:
        return

    templates_by_name = resolve_global_templates(section_templates_manager, claimed)
    resolved = [name for name in claimed if name in templates_by_name]

    if len(resolved) != len(claimed):
        LOGGER.info(
            "[reconcile_global_templates] Dropped unknown global section template(s) %s while importing '%s'",
            sorted(set(claimed) - set(resolved)), type_entry.get(TypeSchemaKey.NAME.value),
        )

    type_entry[TypeSchemaKey.GLOBAL_TEMPLATE_IDS.value] = resolved

    for template_name in resolved:
        _add_missing_template_fields(type_entry, templates_by_name[template_name])


def resolve_global_templates(
    section_templates_manager: SectionTemplatesManager,
    names: list[str],
) -> dict[str, dict[str, Any]]:
    """
    Looks the given global section templates up in a single query

    Shared with the update side effects, which have to tell a template the user dropped from a Type
    apart from one this repair dropped because it does not exist here

    Args:
        section_templates_manager (SectionTemplatesManager): Manager used to read the templates
        names (list[str]): The template names to resolve

    Raises:
        BaseManagerGetError: If the template lookup fails

    Returns:
        dict[str, dict[str, Any]]: The templates that exist here, keyed by name
    """
    if not names:
        return {}

    templates = section_templates_manager.find({
        SectionTemplateKey.NAME.value: {'$in': sorted(set(names))},
        SectionTemplateKey.IS_GLOBAL.value: True,
    })

    return {
        template[SectionTemplateKey.NAME.value]: template
        for template in templates
        if template.get(SectionTemplateKey.NAME.value)
    }


def _add_missing_template_fields(type_entry: dict[str, Any], template: dict[str, Any]) -> None:
    """
    Adds the fields of one global section template that the uploaded type does not define, in place

    Args:
        type_entry (dict[str, Any]): The uploaded type entry, modified in place
        template (dict[str, Any]): The stored global section template the type claims
    """
    template_fields = [
        field for field in template.get(SectionTemplateKey.FIELDS.value) or [] if isinstance(field, dict)
    ]

    if not template_fields:
        return

    type_fields = type_entry.setdefault(TypeSchemaKey.FIELDS.value, [])

    if not isinstance(type_fields, list):
        return

    known_names = {
        field.get(FieldKey.NAME.value) for field in type_fields if isinstance(field, dict)
    }
    missing = [
        field for field in template_fields
        if is_non_blank_string(field.get(FieldKey.NAME.value)) and field.get(FieldKey.NAME.value) not in known_names
    ]

    if not missing:
        return

    type_fields.extend(deepcopy(field) for field in missing)
    _assign_to_template_section(type_entry, template, [field[FieldKey.NAME.value] for field in missing])

    LOGGER.info(
        "[reconcile_global_templates] Added missing field(s) %s of template '%s' while importing '%s'",
        [field[FieldKey.NAME.value] for field in missing],
        template.get(SectionTemplateKey.NAME.value),
        type_entry.get(TypeSchemaKey.NAME.value),
    )


def _assign_to_template_section(
    type_entry: dict[str, Any],
    template: dict[str, Any],
    field_names: list[str],
) -> None:
    """
    Puts the added template fields into the template's section, creating that section when needed

    A type that inlines a global template carries a section named after it; the fields have to land
    there or they would end up assigned to no section at all

    Args:
        type_entry (dict[str, Any]): The uploaded type entry, modified in place
        template (dict[str, Any]): The stored global section template
        field_names (list[str]): The field names that were just added to the type
    """
    template_name = template.get(SectionTemplateKey.NAME.value)
    render_meta = type_entry.setdefault(TypeSchemaKey.RENDER_META.value, {})

    if not isinstance(render_meta, dict):
        render_meta = {}
        type_entry[TypeSchemaKey.RENDER_META.value] = render_meta

    sections = render_meta.setdefault(TypeSchemaKey.SECTIONS.value, [])

    if not isinstance(sections, list):
        return

    for section in sections:
        if isinstance(section, dict) and section.get(SectionKey.NAME.value) == template_name:
            section_fields = section.setdefault(SectionKey.FIELDS.value, [])

            if isinstance(section_fields, list):
                section_fields.extend(field_names)

            return

    # The type claims the template but carries no section for it - rebuild it from the template
    sections.append({
        SectionKey.TYPE.value: template.get(SectionTemplateKey.TYPE.value) or SectionType.SECTION.value,
        SectionKey.NAME.value: template_name,
        SectionKey.LABEL.value: template.get(SectionTemplateKey.LABEL.value) or template_name,
        SectionKey.FIELDS.value: list(field_names),
    })


def normalize_imported_type(
    type_entry: Any,
    types_manager: TypesManager,
    section_templates_manager: SectionTemplatesManager,
) -> None:
    """
    Applies every in-place repair an uploaded type gets before it is written

    Repairs are the counterpart of the validation rules: they cover the parts of an upload that say
    nothing about its quality, so refusing the entry would only get in the way. Both are applied on
    the create and the update path. The three that consult the database (cross-type references, ACL
    groups, global section templates) all clean up ids and names that belonged to the system the type
    was exported from

    Args:
        type_entry (Any): A single entry of the uploaded payload, modified in place
        types_manager (TypesManager): Manager used to resolve cross-type references and ACL groups
        section_templates_manager (SectionTemplatesManager): Manager used to resolve global templates

    Raises:
        TypesManagerGetError: If the reference existence lookup fails
        BaseManagerGetError: If the group or template lookup fails
    """
    apply_type_defaults(type_entry)
    apply_render_meta_defaults(type_entry)
    clear_dangling_type_references(type_entry, types_manager)
    clear_dangling_acl_groups(type_entry, types_manager)
    deactivate_empty_acl(type_entry)
    reconcile_global_templates(type_entry, section_templates_manager)
