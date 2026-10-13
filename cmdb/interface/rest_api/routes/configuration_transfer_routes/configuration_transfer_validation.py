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
The import checks of a configuration transfer file - every problem of a file, before anything is written

`find_import_problems` runs, in order: the envelope (`transfer_file`), the version (exact match), then per component
the shared public_id rule and the component's own rules, which are the ones its write routes apply:

    section templates   the route's text and field rules (`require_text`, `guard_template_fields`); not predefined
    types               the type import's rules (special type + licence, structure, flags, `uses_ports` licence,
                        name) on the entry without its acl
    categories          the model schema; `types` real ids, each once, in the file, one category per type; `parent`
    relations           the model schema and the relation structure guard

**Every entry is judged as an unchanged save of itself.** The exporting system kept these documents, so a value it
may keep - a relation name, a field or section identifier, a field pattern stored before the rule that now refuses a
new one - passes here too: the rules that judge only what a write changes get nothing to judge (the identifier and
pattern rules, the relation name rule). Everything a save always judges is judged in full.

Beyond the routes, the file has to hold together on its own: names unique per component, and every reference -
a type's reference fields and reference sections, a category's types and parent, a relation's types - resolves to
an entry of the file. A rule that aborts in its route is reused as it is, its 400 turned into a problem
(`collect_refusal`), so the import cannot drift from the route.

The component rules live here and not on the framework's components: the type rules belong to the type import, in
the transport layer, which the framework may not import. `COMPONENT_VALIDATORS` maps every registered component to
its rules - a census test fails for a component without one
"""
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable

from cerberus import Validator
from werkzeug.exceptions import HTTPException

from cmdb.manager import TypesManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.user_model import CmdbUser
from cmdb.framework.section_templates import SectionTemplateCreator
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.models.category_model import CmdbCategory
from cmdb.models.category_model.category_constants import CategoryKey
from cmdb.models.category_model.category_types import is_type_id
from cmdb.models.relation_model import CmdbRelation
from cmdb.models.relation_model.relation_constants import RelationKey
from cmdb.models.section_template_model.section_template_constants import SectionTemplateKey
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.section_key_enum import SectionKey
from cmdb.models.type_model.section_reference_key_enum import SectionReferenceKey
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.models.type_model.type_structure_rules import TypeStructure, read_type_structure, validate_type_structure
from cmdb.framework.section_templates import claimed_template_names, reconcile_type_with_global_templates
from cmdb.framework.configuration_transfer import (
    TRANSFER_COMPONENT_NAMES,
    TransferComponentName,
    TransferFileKey,
    TransferSectionKey,
    db_version_mismatch,
    db_version_too_new,
    find_transfer_file_problems,
)
from cmdb.framework.configuration_transfer.transfer_file import is_strict_int
from cmdb.utils import duplicate_names
from cmdb.interface.blueprints.schema_error_format import describe_schema_errors
from cmdb.interface.rest_api.routes.framework_routes.cmdb_categories.categories_helper import find_repeated_type_ids
from cmdb.interface.rest_api.routes.framework_routes.cmdb_section_templates.section_template_helper import (
    guard_template_fields,
    require_text,
)
from cmdb.interface.rest_api.routes.importer_routes.importer_type_rules import (
    missing_type_name_error,
    normalize_boolean_flags,
    type_name_conflict_error,
    uses_ports_license_error,
    validate_create_special_type,
)
from cmdb.interface.rest_api.routes.cmdb_license.license_guard import feature_locked
from cmdb.interface.rest_api.routes.relation_routes.relation_structure_helper import relation_structure_blocker
from cmdb.interface.rest_api.routes.configuration_transfer_routes.configuration_transfer_validation_constants import (
    ENTRY_PROBLEM,
    ENTRY_POSITION,
    COMPONENT_PROBLEM,
    PUBLIC_ID_NOT_A_NUMBER,
    PUBLIC_ID_REPEATED,
    VALUE_REPEATED,
    PREDEFINED_TEMPLATE_IN_FILE,
    TEMPLATE_NAME_IS_PREDEFINED,
    TEMPLATE_FIELDS_NOT_A_LIST,
    TEMPLATE_FIELD_NOT_AN_OBJECT,
    TYPE_REFERENCES_UNKNOWN_TYPES,
    SPECIAL_TYPE_REPEATED,
    CATEGORY_TYPES_NOT_IDS,
    CATEGORY_TYPES_REPEATED,
    CATEGORY_TYPES_UNKNOWN,
    CATEGORY_PARENT_UNKNOWN,
    TYPE_IN_SEVERAL_CATEGORIES,
    RELATION_TYPES_UNKNOWN,
    TEMPLATE_COPY_CONFLICT,
)
# -------------------------------------------------------------------------------------------------------------------- #

PUBLIC_ID_KEY: str = 'public_id'
ItemProblems = Callable[[list[dict[str, Any]], dict[str, list[dict[str, Any]]], 'ImportContext'], list[str]]


@dataclass(frozen=True)
class ImportContext:
    """
    What the import checks need from the importing system

    Attributes:
        types_manager (TypesManager): The tenant's types manager - the type create rules look up stored types
        ipam_locked (bool): Whether the IPAM licence is missing, which refuses the gated special types and ports
        predefined_templates (tuple[dict[str, Any], ...]): The predefined section templates the import seeds
    """
    types_manager: TypesManager
    ipam_locked: bool
    predefined_templates: tuple[dict[str, Any], ...]


    @property
    def predefined_template_names(self) -> frozenset[str]:
        """
        The names of the predefined section templates the import seeds

        Returns:
            frozenset[str]: The names
        """
        return frozenset(template[SectionTemplateKey.NAME.value] for template in self.predefined_templates)



def build_import_context(request_user: CmdbUser) -> ImportContext:
    """
    Gathers what the import checks need from the requesting tenant

    The predefined templates come from the code that seeds them, not from the database: the import replaces the stored
    predefined templates with freshly seeded ones, so those are the names a file's template may not take and the
    templates a type's copies are reconciled with

    Args:
        request_user (CmdbUser): The importing user

    Returns:
        ImportContext: The tenant's types manager, the IPAM licence state and the predefined templates
    """
    return ImportContext(
        types_manager=ManagerProvider.get_manager(ManagerType.TYPES, request_user),
        ipam_locked=feature_locked(LicenseFeature.IPAM, request_user),
        predefined_templates=tuple(SectionTemplateCreator().get_predefined_templates()),
    )

# -------------------------------------------------------------------------------------------------------------------- #
#                                                    shared helpers                                                    #
# -------------------------------------------------------------------------------------------------------------------- #

def collect_refusal(rule: Callable[..., Any], *args: Any) -> str | None:
    """
    Runs a route rule that aborts and answers its refusal as a problem instead

    Args:
        rule (Callable[..., Any]): The rule - it aborts with an HTTPException when the value breaks it
        *args (Any): The rule's arguments

    Returns:
        str | None: The refusal's message, None when the rule passed
    """
    try:
        rule(*args)
    except HTTPException as err:
        return str(err.description)

    return None


def entry_name(item: dict[str, Any], index: int) -> str:
    """
    Names an entry for a problem message: its public_id, or its position when it carries no usable one

    Args:
        item (dict[str, Any]): The entry
        index (int): Its position in the component's items

    Returns:
        str: The name
    """
    public_id: Any = item.get(PUBLIC_ID_KEY)

    return str(public_id) if is_strict_int(public_id) and public_id > 0 else ENTRY_POSITION.format(index=index)


def entry_problems(component: str, item: dict[str, Any], index: int, problems: list[str | None]) -> list[str]:
    """
    Prefixes one entry's problems with the component and the entry, leaving out the rules that passed

    Args:
        component (str): The component's name
        item (dict[str, Any]): The entry
        index (int): Its position in the component's items
        problems (list[str | None]): The answers of the entry's rules, None for a rule that passed

    Returns:
        list[str]: The entry's problems
    """
    name: str = entry_name(item, index)

    return [ENTRY_PROBLEM.format(component=component, entry=name, problem=problem) for problem in problems if problem]


def component_problem(component: str, problem: str) -> str:
    """
    Prefixes a problem of a component as a whole

    Args:
        component (str): The component's name
        problem (str): The problem

    Returns:
        str: The prefixed problem
    """
    return COMPONENT_PROBLEM.format(component=component, problem=problem)


def repeated_values(items: list[dict[str, Any]], key: str) -> list[Any]:
    """
    Answers the values of one key that more than one entry carries - unhashable values are left to the entry rules

    Args:
        items (list[dict[str, Any]]): The entries
        key (str): The key

    Returns:
        list[Any]: Each repeated value once, in first-seen order
    """
    return duplicate_names(item[key] for item in items if isinstance(item.get(key), (str, int)))


def unique_value_problems(component: str, items: list[dict[str, Any]], key: str) -> list[str]:
    """
    Refuses entries of one component sharing a value that identifies them

    Args:
        component (str): The component's name
        items (list[dict[str, Any]]): The entries
        key (str): The identifying key

    Returns:
        list[str]: One problem naming the shared values, or none
    """
    repeated: list[Any] = repeated_values(items, key)

    return [component_problem(component, VALUE_REPEATED.format(key=key, values=repeated))] if repeated else []


def public_id_problems(component: str, items: list[dict[str, Any]]) -> list[str]:
    """
    The rule every component shares: each entry carries a positive whole public_id, no two the same

    Args:
        component (str): The component's name
        items (list[dict[str, Any]]): The entries

    Returns:
        list[str]: The problems
    """
    problems: list[str] = []

    for index, item in enumerate(items):
        public_id: Any = item.get(PUBLIC_ID_KEY)

        if not (is_strict_int(public_id) and public_id > 0):
            problems += entry_problems(component, item, index, [PUBLIC_ID_NOT_A_NUMBER])

    repeated: list[Any] = repeated_values(items, PUBLIC_ID_KEY)

    if repeated:
        problems.append(component_problem(component, PUBLIC_ID_REPEATED.format(values=repeated)))

    return problems


def schema_problem(schema: dict[str, Any], item: dict[str, Any]) -> str | None:
    """
    Judges an entry against a model schema the way the write routes do - unknown keys purged, not refused

    Args:
        schema (dict[str, Any]): The Cerberus schema
        item (dict[str, Any]): The entry

    Returns:
        str | None: The schema's refusal, None when the entry conforms
    """
    validator: Validator = Validator(schema, purge_unknown=True)

    return None if validator.validate(item) else describe_schema_errors(validator.errors)


def file_public_ids(file_items: dict[str, list[dict[str, Any]]], component: TransferComponentName) -> set[int]:
    """
    The public_ids one component of the file carries - what a reference into it resolves against

    Args:
        file_items (dict[str, list[dict[str, Any]]]): Every component's entries
        component (TransferComponentName): The referenced component

    Returns:
        set[int]: Its usable public_ids
    """
    return {item[PUBLIC_ID_KEY] for item in file_items.get(component.value, [])
            if is_strict_int(item.get(PUBLIC_ID_KEY))}


def unknown_ids(values: Any, known: set[int]) -> list[int]:
    """
    Answers the ids of a reference list the file does not carry; what is no id is left to the schema rules

    Args:
        values (Any): The reference list (None or anything else than a list counts as empty)
        known (set[int]): The ids the file carries

    Returns:
        list[int]: The unknown ids, sorted, each once
    """
    if not isinstance(values, list):
        return []

    return sorted({value for value in values if is_strict_int(value) and value not in known})

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   section templates                                                  #
# -------------------------------------------------------------------------------------------------------------------- #

def template_fields_problem(fields: Any) -> str | None:
    """
    Judges a section template's fields by the template routes' field rules

    Args:
        fields (Any): The entry's `fields`

    Returns:
        str | None: The first problem, None when the fields are usable
    """
    if not isinstance(fields, list):
        return TEMPLATE_FIELDS_NOT_A_LIST

    if not all(isinstance(field, dict) for field in fields):
        return TEMPLATE_FIELD_NOT_AN_OBJECT

    # An unchanged save: the stored fields are the fields, so only a pattern the template never had would be judged
    return collect_refusal(guard_template_fields, fields, fields)


def section_template_problems(items: list[dict[str, Any]], file_items: dict[str, list[dict[str, Any]]],
                              context: 'ImportContext') -> list[str]:
    """
    Judges the file's section templates: the route rules, not predefined, names unique and not taken by DataGerry

    Args:
        items (list[dict[str, Any]]): The section template entries
        file_items (dict[str, list[dict[str, Any]]]): Every component's entries (unused - templates reference none)
        context (ImportContext): The importing system

    Returns:
        list[str]: The problems
    """
    del file_items
    component: str = TransferComponentName.SECTION_TEMPLATES.value
    problems: list[str] = []

    for index, item in enumerate(items):
        name: Any = item.get(SectionTemplateKey.NAME.value)
        problems += entry_problems(component, item, index, [
            PREDEFINED_TEMPLATE_IN_FILE if item.get(SectionTemplateKey.PREDEFINED.value) is True else None,
            collect_refusal(require_text, name, SectionTemplateKey.NAME.value),
            collect_refusal(require_text, item.get(SectionTemplateKey.LABEL.value), SectionTemplateKey.LABEL.value),
            TEMPLATE_NAME_IS_PREDEFINED.format(name=name) if name in context.predefined_template_names else None,
            template_fields_problem(item.get(SectionTemplateKey.FIELDS.value)),
        ])

    return problems + unique_value_problems(component, items, SectionTemplateKey.NAME.value)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                         types                                                        #
# -------------------------------------------------------------------------------------------------------------------- #

def flatten_ids(values: Any) -> list[Any]:
    """
    Flattens a `ref_types` list, whose entries are ids or lists of ids

    Args:
        values (Any): The `ref_types` value

    Returns:
        list[Any]: Every entry, nested ones included
    """
    if not isinstance(values, list):
        return []

    return [nested for value in values for nested in (value if isinstance(value, list) else [value])]


def referenced_type_ids(type_entry: dict[str, Any]) -> list[Any]:
    """
    The type ids a type entry references: its reference fields' `ref_types` and its reference sections' `type_id`

    Read through `read_type_structure`, the reader the structure rules use, so the sections are found where a
    type keeps them (`render_meta.sections`) and junk entries are skipped the same way

    Args:
        type_entry (dict[str, Any]): The type entry

    Returns:
        list[Any]: The referenced ids, as stored
    """
    structure: TypeStructure = read_type_structure(type_entry)
    ids: list[Any] = [type_id for _, field in structure.fields
                      for type_id in flatten_ids(field.get(FieldKey.REF_TYPES.value))]

    for _, section in structure.sections:
        reference: Any = section.get(SectionKey.REFERENCE.value)

        if isinstance(reference, dict):
            ids.append(reference.get(SectionReferenceKey.TYPE_ID.value))

    return ids


def unchanged_type_save_problem(type_entry: dict[str, Any], types_manager: TypesManager,
                                ipam_locked: bool) -> str | None:
    """
    Judges a type entry by the type import's rules as an unchanged save - first finding wins

    The create sequence (`validate_create_entry`) without the two rules that judge only what a write changes: the
    identifier rule and the field-pattern rule have nothing new to judge when the stored type is the entry itself.
    The acl rule is left out because the import drops the acl

    Args:
        type_entry (dict[str, Any]): A copy of the type entry - `normalize_boolean_flags` writes its defaults into it
        types_manager (TypesManager): The importing tenant's types manager - the special type and the name are
                                      judged against the stored types
        ipam_locked (bool): Whether the IPAM licence is missing

    Returns:
        str | None: The first rule broken, None when the entry may be stored
    """
    return (
        validate_create_special_type(type_entry, types_manager, ipam_locked)
        or validate_type_structure(type_entry)
        or normalize_boolean_flags(type_entry)
        # After normalisation, so the lenient spellings are already real booleans
        or uses_ports_license_error(type_entry, ipam_locked)
        or missing_type_name_error(type_entry)
        or type_name_conflict_error(type_entry, types_manager)
    )


def type_save_problem(type_entry: dict[str, Any], context: 'ImportContext') -> str | None:
    """
    Judges a type entry as an unchanged save, on a copy without its acl (the import drops it)

    Args:
        type_entry (dict[str, Any]): The type entry - left untouched, the rules normalise a copy
        context (ImportContext): The importing system

    Returns:
        str | None: The first rule broken, None when the entry may be stored
    """
    candidate: dict[str, Any] = deepcopy(type_entry)
    candidate.pop(TypeSchemaKey.ACL.value, None)

    return unchanged_type_save_problem(candidate, context.types_manager, context.ipam_locked)


def type_problems(items: list[dict[str, Any]], file_items: dict[str, list[dict[str, Any]]],
                  context: 'ImportContext') -> list[str]:
    """
    Judges the file's types: the create rules, references into the file, names and special types unique

    Args:
        items (list[dict[str, Any]]): The type entries
        file_items (dict[str, list[dict[str, Any]]]): Every component's entries
        context (ImportContext): The importing system

    Returns:
        list[str]: The problems
    """
    component: str = TransferComponentName.TYPES.value
    known: set[int] = file_public_ids(file_items, TransferComponentName.TYPES)
    problems: list[str] = []

    for index, item in enumerate(items):
        unknown: list[int] = unknown_ids(referenced_type_ids(item), known)
        problems += entry_problems(component, item, index, [
            type_save_problem(item, context),
            TYPE_REFERENCES_UNKNOWN_TYPES.format(type_ids=unknown) if unknown else None,
        ])

    special: list[Any] = repeated_values([item for item in items if item.get(TypeSchemaKey.SPECIAL_TYPE.value)],
                                         TypeSchemaKey.SPECIAL_TYPE.value)

    if special:
        problems.append(component_problem(component, SPECIAL_TYPE_REPEATED.format(values=special)))

    return problems + unique_value_problems(component, items, TypeSchemaKey.NAME.value)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                      categories                                                      #
# -------------------------------------------------------------------------------------------------------------------- #

def category_types_problem(type_ids: Any, known: set[int]) -> str | None:
    """
    Judges a category's `types`: real ids, each named once, each a type of the file

    Args:
        type_ids (Any): The entry's `types`
        known (set[int]): The type ids the file carries

    Returns:
        str | None: The first problem, None when the list is usable
    """
    ids: list[Any] = type_ids if isinstance(type_ids, list) else []
    not_ids: list[Any] = [value for value in ids if not is_type_id(value)]

    if not_ids:
        return CATEGORY_TYPES_NOT_IDS.format(values=not_ids)

    repeated: list[int] = find_repeated_type_ids(ids)

    if repeated:
        return CATEGORY_TYPES_REPEATED.format(type_ids=repeated)

    unknown: list[int] = unknown_ids(ids, known)

    return CATEGORY_TYPES_UNKNOWN.format(type_ids=unknown) if unknown else None


def category_parent_problem(item: dict[str, Any], categories: set[int]) -> str | None:
    """
    Judges a category's `parent`: none, or another category of the file

    Args:
        item (dict[str, Any]): The category entry
        categories (set[int]): The category ids the file carries

    Returns:
        str | None: The problem, None when the parent is usable
    """
    parent: Any = item.get(CategoryKey.PARENT.value)

    if parent is None:
        return None

    if parent in categories and parent != item.get(PUBLIC_ID_KEY):
        return None

    return CATEGORY_PARENT_UNKNOWN.format(parent=parent)


def category_problems(items: list[dict[str, Any]], file_items: dict[str, list[dict[str, Any]]],
                      context: 'ImportContext') -> list[str]:
    """
    Judges the file's categories: the schema, the types and the parent, names unique, one category per type

    Args:
        items (list[dict[str, Any]]): The category entries
        file_items (dict[str, list[dict[str, Any]]]): Every component's entries
        context (ImportContext): The importing system (unused - categories need nothing from it)

    Returns:
        list[str]: The problems
    """
    del context
    component: str = TransferComponentName.CATEGORIES.value
    types: set[int] = file_public_ids(file_items, TransferComponentName.TYPES)
    categories: set[int] = file_public_ids(file_items, TransferComponentName.CATEGORIES)
    problems: list[str] = []

    for index, item in enumerate(items):
        problems += entry_problems(component, item, index, [
            schema_problem(CmdbCategory.SCHEMA, item),
            category_types_problem(item.get(CategoryKey.TYPES.value), types),
            category_parent_problem(item, categories),
        ])

    held: list[Any] = duplicate_names(type_id for item in items
                                      for type_id in set(item.get(CategoryKey.TYPES.value) or [])
                                      if is_type_id(type_id))

    if held:
        problems.append(component_problem(component, TYPE_IN_SEVERAL_CATEGORIES.format(type_ids=sorted(held))))

    return problems + unique_value_problems(component, items, CategoryKey.NAME.value)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                       relations                                                      #
# -------------------------------------------------------------------------------------------------------------------- #

def relation_types_problems(item: dict[str, Any], known: set[int]) -> list[str | None]:
    """
    Judges a relation's two type lists against the types of the file

    Args:
        item (dict[str, Any]): The relation entry
        known (set[int]): The type ids the file carries

    Returns:
        list[str | None]: One answer per side, None for a side that resolves
    """
    answers: list[str | None] = []

    for key in (RelationKey.PARENT_TYPE_IDS.value, RelationKey.CHILD_TYPE_IDS.value):
        unknown: list[int] = unknown_ids(item.get(key), known)
        answers.append(RELATION_TYPES_UNKNOWN.format(key=key, type_ids=unknown) if unknown else None)

    return answers


def relation_problems(items: list[dict[str, Any]], file_items: dict[str, list[dict[str, Any]]],
                      context: 'ImportContext') -> list[str]:
    """
    Judges the file's relations: the schema, the structure guard, the types, names unique

    Args:
        items (list[dict[str, Any]]): The relation entries
        file_items (dict[str, list[dict[str, Any]]]): Every component's entries
        context (ImportContext): The importing system (unused - relations need nothing from it)

    Returns:
        list[str]: The problems
    """
    del context
    component: str = TransferComponentName.RELATIONS.value
    types: set[int] = file_public_ids(file_items, TransferComponentName.TYPES)
    problems: list[str] = []

    for index, item in enumerate(items):
        schema_answer: str | None = schema_problem(CmdbRelation.SCHEMA, item)
        problems += entry_problems(component, item, index, [
            schema_answer,
            # The structure guard reads the shape the schema guarantees - only asked of an entry that has it
            None if schema_answer else relation_structure_blocker(item),
            # The name's shape rule judges only a changed name - an unchanged save keeps a name stored before it
            *relation_types_problems(item, types),
        ])

    return problems + unique_value_problems(component, items, RelationKey.RELATION_NAME.value)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                       the file                                                       #
# -------------------------------------------------------------------------------------------------------------------- #

# Every registered component's rules - a component without an entry fails `test_every_component_has_a_validator`
COMPONENT_VALIDATORS: dict[str, ItemProblems] = {
    TransferComponentName.SECTION_TEMPLATES.value: section_template_problems,
    TransferComponentName.TYPES.value: type_problems,
    TransferComponentName.CATEGORIES.value: category_problems,
    TransferComponentName.RELATIONS.value: relation_problems,
}


def find_import_problems(data: Any, target_db_version: int, context: ImportContext) -> list[str]:
    """
    Judges an uploaded transfer file completely, without writing anything

    The envelope is judged first and stops the check when it fails - the entries cannot be read reliably; so does
    a version mismatch - the entries carry another version's shape. Otherwise every component's entries are judged
    and every problem is answered at once

    Args:
        data (Any): The parsed upload
        target_db_version (int): The importing database's updater version
        context (ImportContext): The importing system

    Raises:
        TypesManagerGetError: When the type rules could not read the stored types

    Returns:
        list[str]: The problems, empty when the file may be imported
    """
    problems: list[str] = find_transfer_file_problems(data, TRANSFER_COMPONENT_NAMES)

    if problems:
        return problems

    mismatch: str | None = db_version_mismatch(data[TransferFileKey.DB_VERSION.value], target_db_version)

    if mismatch:
        return [mismatch]

    sections: dict[str, Any] = data[TransferFileKey.COMPONENTS.value]
    file_items: dict[str, list[dict[str, Any]]] = {
        name: sections[name][TransferSectionKey.ITEMS.value] for name in TRANSFER_COMPONENT_NAMES
    }

    for name in TRANSFER_COMPONENT_NAMES:
        problems += public_id_problems(name, file_items[name])
        problems += COMPONENT_VALIDATORS[name](file_items[name], file_items, context)

    return problems


def find_file_problems(data: Any, target_version: int) -> list[str]:
    """
    Judges what has to hold before a file can be migrated: its envelope, and a version not newer than the target's

    Args:
        data (Any): The parsed upload
        target_version (int): The importing database's updater version

    Returns:
        list[str]: The problems, empty when the file can be migrated
    """
    problems: list[str] = find_transfer_file_problems(data, TRANSFER_COMPONENT_NAMES)

    if problems:
        return problems

    too_new: str | None = db_version_too_new(data[TransferFileKey.DB_VERSION.value], target_version)

    return [too_new] if too_new else []


def reconcile_template_copies(transfer_file: dict[str, Any], context: ImportContext) -> list[str]:
    """
    Puts every type's copies of its global section templates in line with the templates it will meet - in place

    The templates are the predefined ones the import seeds and the file's own global templates; a claim naming
    neither is dropped, as every type write drops it. A field a template does not own, found inside that template's
    section, is a conflict: the type cannot be stored without losing the field's place, so it is a problem

    Args:
        transfer_file (dict[str, Any]): The checked file - its type entries are reconciled in place
        context (ImportContext): The importing system

    Returns:
        list[str]: One problem per conflicting field, empty when every copy could be reconciled
    """
    sections: dict[str, Any] = transfer_file[TransferFileKey.COMPONENTS.value]
    file_templates: list[dict[str, Any]] = sections[TransferComponentName.SECTION_TEMPLATES.value][
        TransferSectionKey.ITEMS.value]
    templates_by_name: dict[str, dict[str, Any]] = {
        **{template[SectionTemplateKey.NAME.value]: template for template in context.predefined_templates},
        **{template[SectionTemplateKey.NAME.value]: template for template in file_templates
           if template.get(SectionTemplateKey.IS_GLOBAL.value) is True},
    }
    component: str = TransferComponentName.TYPES.value
    problems: list[str] = []

    for index, item in enumerate(sections[component][TransferSectionKey.ITEMS.value]):
        if not claimed_template_names(item):
            continue

        conflicts = reconcile_type_with_global_templates(item, templates_by_name).conflicts
        problems += entry_problems(component, item, index, [
            TEMPLATE_COPY_CONFLICT.format(field=conflict.field_name, template=conflict.template_name)
            for conflict in conflicts
        ])

    return problems
