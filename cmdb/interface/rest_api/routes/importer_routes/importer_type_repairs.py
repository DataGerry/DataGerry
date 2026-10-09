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
presentation state that is replaced rather than refused, and ids / names that belonged to the system
the type was exported from and mean nothing here.
`normalize_imported_type` runs all of them, on the create and the update path alike, after the rules
in `importer_type_rules` have passed and before the entry is written

Three of them read the database - cross-type references, ACL groups and global section templates -
each with a single query per entry
"""
from typing import Any
from logging import Logger, getLogger

from cmdb.manager import TypesManager, SectionTemplatesManager

from cmdb.models.type_model import (
    CmdbType,
    DEFAULT_PORT_SECTION_INDEX,
    MIN_PORT_SECTION_INDEX,
    TypeSchemaKey,
    FieldKey,
    SectionKey,
    SectionReferenceKey,
)
from cmdb.models.group_model import CmdbUserGroup
from cmdb.utils import coerce_whole_number, random_hex_color, is_non_blank_string
from cmdb.framework.ci_explorer.label_field import label_field_error
from cmdb.framework.section_templates.global_template_reconcile import (
    GlobalTemplateReconcile,
    claimed_template_names,
    first_template_conflict,
    reconcile_type_with_global_templates,
    resolve_global_templates,
)
from cmdb.framework.object_field_value_rules import find_default_value_errors
from cmdb.security.acl.acl_constants import AclKey
from cmdb.security.acl.access_control_list import AccessControlList
from cmdb.interface.rest_api.routes.importer_routes.importer_type_rules import (
    TypeStructure,
    read_type_structure,
)
from cmdb.interface.rest_api.routes.importer_routes.importer_type_constants import (
    DEFAULT_TYPE_ICON,
    TypeImportError,
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
    * `ci_explorer_label` - None, i.e. the CI Explorer draws its nodes with no label until a field is
      nominated (a nomination the upload DOES bring is checked by clear_dangling_ci_explorer_label)
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
        type_entry[TypeSchemaKey.ACL.value] = AccessControlList.default_json()


def apply_port_section_index_default(type_entry: Any) -> None:
    """
    Settles the 'port_section_index' of an uploaded type, in place

    The index is where the frontend draws the ports section among the type's own sections. It says
    nothing about the quality of an upload, so - unlike `POST`/`PUT /types/`, which refuses an
    unusable value with a 400 - every unusable value here is simply replaced by
    DEFAULT_PORT_SECTION_INDEX: an absent key, a null, a negative index, a fraction, a boolean or
    anything that is not a number at all. An export of a type that predates the key is the ordinary
    case, and losing a cosmetic position is never worth failing an import entry over

    A type that does not use ports is forced back to the default as well, matching the route rule: the
    index is only read while `uses_ports` is on. Runs after the rules, so that flag is already the
    real boolean `normalize_boolean_flags` parsed

    Args:
        type_entry (Any): A single entry of the uploaded payload, modified in place
    """
    if not isinstance(type_entry, dict):
        return

    coerced: int | None = coerce_whole_number(type_entry.get(TypeSchemaKey.PORT_SECTION_INDEX.value))

    usable: bool = coerced is not None \
                   and coerced >= MIN_PORT_SECTION_INDEX \
                   and bool(type_entry.get(TypeSchemaKey.USES_PORTS.value))

    type_entry[TypeSchemaKey.PORT_SECTION_INDEX.value] = coerced if usable else DEFAULT_PORT_SECTION_INDEX


def clear_invalid_field_defaults(type_entry: Any) -> list[str]:
    """
    Drops every field default the uploaded type's own value rules refuse, in place

    A default is what every new object of the Type starts from, and it has to pass its field's own rules
    (the text / textarea cap, the field's ``regex``) - the type routes refuse one that does not. An upload
    is repaired instead of refused: the default belonged to the system the type came from, and a field
    without a default is an ordinary state to start in. Only the default is dropped; the field and its
    rules stay

    Args:
        type_entry (Any): A single entry of the uploaded payload, modified in place

    Returns:
        list[str]: The names of the fields whose default was dropped, in field order; empty when nothing
            had to be repaired
    """
    if not isinstance(type_entry, dict):
        return []

    fields: Any = type_entry.get(TypeSchemaKey.FIELDS.value)

    if not isinstance(fields, list):
        return []

    readable: list[dict[str, Any]] = [field for field in fields if isinstance(field, dict)]
    errors: dict[str, list[str]] = find_default_value_errors(readable)
    cleared: list[str] = []

    for field in readable:
        name: Any = field.get(FieldKey.NAME.value)

        if name in errors:
            LOGGER.warning("[clear_invalid_field_defaults] Dropping an unusable default: %s", '; '.join(errors[name]))
            field[FieldKey.VALUE.value] = None
            cleared.append(name)

    return cleared


def clear_dangling_ci_explorer_label(type_entry: Any) -> str | None:
    """
    Drops a CI Explorer label nomination the uploaded type cannot honour, in place

    ``ci_explorer_label`` is the NAME of one of the Type's own fields - the CI Explorer shows that
    field's value on every node of the Type. An upload can carry one that this Type no longer has (a
    field removed before the export, or an export from a Type whose fields were edited afterwards),
    and a multi-data-section field is not usable either.

    A repair rather than a blocker, for the same reason `clear_dangling_type_references` is one: the
    name belonged to the system the type came from, it says nothing about the quality of the upload,
    and a Type that imports with no nomination is exactly the state a Type starts in. The two type
    routes DO refuse an unusable nomination - there the caller chose it just now and can be told

    Args:
        type_entry (Any): A single entry of the uploaded payload, modified in place

    Returns:
        str | None: The nomination that was dropped, or None when nothing had to be repaired
    """
    if not isinstance(type_entry, dict):
        return None

    nominated: Any = type_entry.get(TypeSchemaKey.CI_EXPLORER_LABEL.value)

    if not label_field_error(type_entry, nominated):
        # Also normalises the frontend's empty-string "cleared" to the stored None
        type_entry[TypeSchemaKey.CI_EXPLORER_LABEL.value] = nominated or None

        return None

    type_entry[TypeSchemaKey.CI_EXPLORER_LABEL.value] = None

    LOGGER.debug(
        "[clear_dangling_ci_explorer_label] Dropped the CI Explorer label field %s of the uploaded "
        "Type %s", repr(nominated), type_entry.get(TypeSchemaKey.NAME.value),
    )

    return nominated if isinstance(nominated, str) else None


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
        criteria={TypeSchemaKey.PUBLIC_ID.value: {'$in': sorted(set(wanted.values()))}},
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
) -> str | None:
    """
    Puts the uploaded type's copies of the global section templates it claims back in line with them, in place

    The same reconcile every type write runs (``reconcile_type_with_global_templates``): across systems the two
    sides drift, and the template - the one stored HERE - wins:

    * a template that does not exist here is dropped from `global_template_ids` - the inlined section and its
      fields stay, they are real data, but the type stops claiming a template nobody has
    * a template that exists makes its section and its field definitions the type's: a missing field is added, a
      locally rewritten one replaced, a template field sitting in another section moved back, and the section
      created from the template when the type does not carry it
    * a field the template does not own, inside the template's section, refuses the entry

    Args:
        type_entry (Any): A single entry of the uploaded payload, modified in place
        section_templates_manager (SectionTemplatesManager): Manager used to read the templates

    Raises:
        BaseManagerGetError: If the template lookup fails

    Returns:
        str | None: The refusal of a foreign field inside a template's section, else None
    """
    if not isinstance(type_entry, dict):
        return None

    claims: list[str] = claimed_template_names(type_entry)

    if not claims:
        return None

    outcome = reconcile_type_with_global_templates(
        type_entry, resolve_global_templates(section_templates_manager, claims),
    )

    if outcome.dropped_claims:
        LOGGER.info(
            "[reconcile_global_templates] Dropped unknown global section template(s) %s while importing '%s'",
            sorted(outcome.dropped_claims), type_entry.get(TypeSchemaKey.NAME.value),
        )

    return template_section_conflict_message(outcome)


def template_section_conflict_message(outcome: GlobalTemplateReconcile) -> str | None:
    """
    Words the first template's foreign fields as the import refusal

    Args:
        outcome (GlobalTemplateReconcile): What the reconcile found

    Returns:
        str | None: The refusal, or None when the reconcile found no conflict
    """
    conflict: tuple[str, list[str]] | None = first_template_conflict(outcome)

    if not conflict:
        return None

    return TypeImportError.FOREIGN_FIELD_IN_TEMPLATE_SECTION.format(template=conflict[0], names=conflict[1])


def normalize_imported_type(
    type_entry: Any,
    types_manager: TypesManager,
    section_templates_manager: SectionTemplatesManager,
) -> str | None:
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

    Returns:
        str | None: The one refusal a repair can raise - a field the template does not own inside a claimed
            global template's section - else None
    """
    apply_type_defaults(type_entry)
    apply_port_section_index_default(type_entry)
    apply_render_meta_defaults(type_entry)
    clear_dangling_type_references(type_entry, types_manager)
    clear_dangling_acl_groups(type_entry, types_manager)
    deactivate_empty_acl(type_entry)
    template_conflict: str | None = reconcile_global_templates(type_entry, section_templates_manager)

    if template_conflict:
        return template_conflict

    # After the template reconcile: it can add fields, whose defaults are judged like the rest
    clear_invalid_field_defaults(type_entry)
    # LAST: the template repair above can add fields to the entry, and a nomination pointing at one
    # of those is perfectly usable - dropping it before they exist would be wrong
    clear_dangling_ci_explorer_label(type_entry)

    return None
