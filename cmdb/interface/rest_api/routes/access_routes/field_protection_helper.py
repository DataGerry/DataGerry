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
The reads and writes of the Field Protection routes (phase 12, D5, D6, D10)

The list reads every Type and every global section template once and answers each field where it is defined
(``field_protection_view``). An update changes one field's class, audit flag, required and pattern at its source: a
Type's own field on the Type, a global template's field on the template and on every Type carrying it - all or nothing
by compensation. The regex test runs a pattern against sample values on the write's time budget
"""
from typing import Any

from flask import abort

from cmdb.utils import BaseStrEnum

from cmdb.manager import (
    AccessAssignmentsManager,
    FieldClassesManager,
    GroupsManager,
    ScopeRolesManager,
    SectionTemplatesManager,
    TypesManager,
)
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.access_model import SYSTEM_FIELD_CLASS, HistoryAction, HistoryKind
from cmdb.models.section_template_model.section_template_constants import SectionTemplateKey
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.models.user_model import CmdbUser
from cmdb.framework.access_engine import AccessGrants
from cmdb.framework.access_engine.access_grants_reads import read_grants
from cmdb.framework.access_rules.field_protection_rules import PROTECTION_KEYS, template_owned_field_names
from cmdb.framework.access_rules.field_protection_view import (
    FieldProtectionKey,
    FieldSource,
    field_rows,
    group_field_access,
)
from cmdb.framework.field_pattern_rule import find_field_pattern_errors
from cmdb.framework.object_field_value_rules import (
    PatternBudget,
    build_field_value_rules,
    find_default_value_errors,
    match_field_pattern,
)
from cmdb.interface.rest_api.routes.routes_helper import abort_on_problems, undone_on_failure
from cmdb.interface.rest_api.routes.access_routes.access_history_helper import (
    ChangeContext,
    field_concerned_groups,
    record_change,
    take_comment,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'FIELD_PROTECTION_UPDATE_KEYS',
    'field_protection_rows',
    'update_field_protection',
    'fields_carrying_class',
    'group_grants',
    'test_pattern',
]

# What an update may change on a field - its class and flag, and its validation
FIELD_PROTECTION_UPDATE_KEYS: tuple[str, ...] = (*PROTECTION_KEYS, FieldKey.REQUIRED.value, FieldKey.REGEX.value)
# The id a field's history entries carry
FIELD_DOCUMENT_ID: str = '{source}:{source_id}:{name}'
UNKNOWN_SOURCE_MESSAGE: str = "There is no {source} with the ID {source_id}!"
NOT_GLOBAL_MESSAGE: str = "Section template {source_id} is not global - its fields belong to the Types it was used in!"
UNKNOWN_FIELD_MESSAGE: str = "The {source} {source_id} declares no field '{field}'!"
TEMPLATE_OWNED_MESSAGE: str = (
    "The field '{field}' of Type {source_id} belongs to a global section template - set it there!"
)
UNKNOWN_CLASS_MESSAGE: str = "There is no field class '{field_class}'!"
UNKNOWN_GROUP_MESSAGE: str = "User group {group_id} does not exist!"
UNDO_INCOMPLETE_MESSAGE: str = "The field protection update failed and could not be undone completely"
SAMPLE_FIELD_NAME: str = 'sample'
_TYPE_PROJECTION: dict[str, int] = {'_id': 0, TypeSchemaKey.PUBLIC_ID.value: 1, TypeSchemaKey.NAME.value: 1,
                                    TypeSchemaKey.FIELDS.value: 1, TypeSchemaKey.GLOBAL_TEMPLATE_IDS.value: 1,
                                    TypeSchemaKey.RENDER_META.value: 1}
_TEMPLATE_PROJECTION: dict[str, int] = {'_id': 0, SectionTemplateKey.PUBLIC_ID.value: 1,
                                        SectionTemplateKey.NAME.value: 1, SectionTemplateKey.FIELDS.value: 1}
_GLOBAL: dict[str, bool] = {SectionTemplateKey.IS_GLOBAL.value: True}


class PatternTestKey(BaseStrEnum):
    """The keys of one regex test result"""
    VALUE = 'value'
    VERDICT = 'verdict'


def field_protection_rows(request_user: CmdbUser, type_id: int | None = None,
                          group_id: int | None = None) -> list[dict[str, Any]]:
    """
    The Field Protection list - optionally the fields on one Type, optionally with a user group's view

    Args:
        request_user (CmdbUser): The caller
        type_id (int | None): Only the fields on this Type (its own and its templates'). Defaults to None (every field)
        group_id (int | None): Add per row what this user group may do. Defaults to None

    Raises:
        HTTPException: 404 for a user group that does not exist

    Returns:
        list[dict[str, Any]]: The rows
    """
    types: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
    templates: SectionTemplatesManager = ManagerProvider.get_manager(ManagerType.SECTION_TEMPLATES, request_user)
    rows: list[dict[str, Any]] = field_rows(types.find(criteria={}, projection=_TYPE_PROJECTION),
                                            templates.find(criteria=_GLOBAL, projection=_TEMPLATE_PROJECTION))

    if type_id is not None:
        rows = [row for row in rows if type_id in row[FieldProtectionKey.REACH.value]]

    if group_id is not None:
        grants: AccessGrants = group_grants(request_user, group_id)

        for row in rows:
            row[FieldProtectionKey.GROUP.value] = group_field_access(grants, row)

    return rows


def group_grants(request_user: CmdbUser, group_id: int) -> AccessGrants:
    """
    The grants a user group holds by itself

    Args:
        request_user (CmdbUser): The caller - names the tenant
        group_id (int): The group

    Raises:
        HTTPException: 404 when the group does not exist

    Returns:
        AccessGrants: Its grants
    """
    groups: GroupsManager = ManagerProvider.get_manager(ManagerType.GROUPS, request_user)

    if not groups.get_group(group_id):
        abort(404, UNKNOWN_GROUP_MESSAGE.format(group_id=group_id))

    assignments: AccessAssignmentsManager = ManagerProvider.get_manager(ManagerType.ACCESS_ASSIGNMENTS, request_user)
    roles: ScopeRolesManager = ManagerProvider.get_manager(ManagerType.SCOPE_ROLES, request_user)

    return read_grants(assignments, roles, [group_id])


def update_field_protection(request_user: CmdbUser, data: dict[str, Any]) -> dict[str, Any]:
    """
    Changes one field's class, audit flag, required and pattern where the field is defined

    Args:
        request_user (CmdbUser): The caller
        data (dict[str, Any]): ``{source, source_id, field, protection?, audit_relevant?, required?, regex?}``

    Raises:
        HTTPException: 404 for an unknown source or field; 400 for a template that is not global, a Type field a
            template owns, an unknown class, a pattern or default the rules refuse

    Returns:
        dict[str, Any]: The field's row as stored
    """
    change: ChangeContext = ChangeContext(request_user, HistoryKind.FIELD_PROTECTION, take_comment(data))
    source: str = data[FieldProtectionKey.SOURCE.value]
    source_id: int = data[FieldProtectionKey.SOURCE_ID.value]
    name: str = data[FieldProtectionKey.NAME.value]
    types: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
    templates: SectionTemplatesManager = ManagerProvider.get_manager(ManagerType.SECTION_TEMPLATES, request_user)
    manager: Any = types if source == FieldSource.TYPE.value else templates
    found: list[dict[str, Any]] = manager.find(criteria={TypeSchemaKey.PUBLIC_ID.value: source_id})

    if not found:
        abort(404, UNKNOWN_SOURCE_MESSAGE.format(source=source, source_id=source_id))

    document: dict[str, Any] = found[0]
    _abort_unless_editable(source, document, name)
    fields: list[dict[str, Any]] = document.get(TypeSchemaKey.FIELDS.value) or []
    stored: dict[str, Any] = next(field for field in fields if field.get(FieldKey.NAME.value) == name)
    changed: dict[str, Any] = _changed_field(request_user, stored, data)
    group_ids: set[int] = _concerned_groups(request_user, templates, document, (source, source_id, name),
                                            [stored.get(FieldKey.PROTECTION.value),
                                             changed.get(FieldKey.PROTECTION.value)])

    with undone_on_failure(UNDO_INCOMPLETE_MESSAGE) as ledger:
        ledger.updated(manager, source_id, document)
        manager.update({TypeSchemaKey.PUBLIC_ID.value: source_id},
                       {TypeSchemaKey.FIELDS.value: _replaced(fields, changed)})

        if source == FieldSource.TEMPLATE.value:
            _write_template_copies(types, ledger, document[SectionTemplateKey.NAME.value], changed)

        record_change(change, HistoryAction.UPDATE, FIELD_DOCUMENT_ID.format(source=source, source_id=source_id,
                                                                             name=name),
                      stored, changed, group_ids, ledger)

    return next(row for row in field_protection_rows(request_user)
                if (row[FieldProtectionKey.SOURCE.value], row[FieldProtectionKey.SOURCE_ID.value],
                    row[FieldProtectionKey.NAME.value]) == (source, source_id, name))


def _concerned_groups(request_user: CmdbUser, templates: SectionTemplatesManager, document: dict[str, Any],
                      field: tuple[str, int, str], field_classes: list[str | None]) -> set[int]:
    """
    The user groups a field's protection change concerns - those writing it, under its class before or after, on a
    Type carrying it

    Args:
        request_user (CmdbUser): The caller
        templates (SectionTemplatesManager): Reads the Types using a template
        document (dict[str, Any]): The field's source, as stored
        field (tuple[str, int, str]): The source kind, its id and the field's name
        field_classes (list[str | None]): The field's class before and after

    Raises:
        BaseManagerGetError: When a read fails

    Returns:
        set[int]: The group ids
    """
    source, source_id, name = field
    reach: list[int] = [source_id] if source == FieldSource.TYPE.value else [
        a_type.public_id for a_type in templates.get_types_using_template(document[SectionTemplateKey.NAME.value])]

    return field_concerned_groups(request_user, name, field_classes, reach)


def _abort_unless_editable(source: str, document: dict[str, Any], name: str) -> None:
    """
    Refuses a template that is not global, a field the source does not declare, and a Type field a template owns

    Args:
        source (str): ``type`` or ``template``
        document (dict[str, Any]): The source as stored
        name (str): The field

    Raises:
        HTTPException: 400 / 404 as named
    """
    source_id: Any = document.get(TypeSchemaKey.PUBLIC_ID.value)

    if source == FieldSource.TEMPLATE.value and document.get(SectionTemplateKey.IS_GLOBAL.value) is not True:
        abort(400, NOT_GLOBAL_MESSAGE.format(source_id=source_id))

    if not any(isinstance(field, dict) and field.get(FieldKey.NAME.value) == name
               for field in document.get(TypeSchemaKey.FIELDS.value) or []):
        abort(404, UNKNOWN_FIELD_MESSAGE.format(source=source, source_id=source_id, field=name))

    if source == FieldSource.TYPE.value and name in template_owned_field_names(document):
        abort(400, TEMPLATE_OWNED_MESSAGE.format(field=name, source_id=source_id))


def _changed_field(request_user: CmdbUser, stored: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """
    The field with the sent keys changed - judged: the class exists, the pattern and the default pass the rules

    Args:
        request_user (CmdbUser): The caller
        stored (dict[str, Any]): The field as stored
        data (dict[str, Any]): The update body

    Raises:
        HTTPException: 400 naming every problem

    Returns:
        dict[str, Any]: The new field definition
    """
    changed: dict[str, Any] = dict(stored)

    for key in FIELD_PROTECTION_UPDATE_KEYS:
        if key in data:
            changed[key] = data[key]

            if data[key] is None:
                changed.pop(key)

    problems: list[str] = find_field_pattern_errors([changed], [stored])
    problems += [message for messages in find_default_value_errors([changed]).values() for message in messages]
    field_class: Any = changed.get(FieldKey.PROTECTION.value)

    if field_class and field_class != SYSTEM_FIELD_CLASS:
        classes: FieldClassesManager = ManagerProvider.get_manager(ManagerType.FIELD_CLASSES, request_user)

        if not classes.find_existing_names([field_class]):
            problems.append(UNKNOWN_CLASS_MESSAGE.format(field_class=field_class))

    abort_on_problems(problems)

    return changed


def _replaced(fields: list[dict[str, Any]], changed: dict[str, Any]) -> list[dict[str, Any]]:
    """
    A field list with one field replaced by its name

    Args:
        fields (list[dict[str, Any]]): The stored fields
        changed (dict[str, Any]): The new definition

    Returns:
        list[dict[str, Any]]: The new list
    """
    return [changed if isinstance(field, dict) and field.get(FieldKey.NAME.value) == changed[FieldKey.NAME.value]
            else field for field in fields]


def _write_template_copies(types: TypesManager, ledger: Any, template_name: str, changed: dict[str, Any]) -> None:
    """
    Writes a template field's new definition into every Type carrying the template - each recorded first

    Args:
        types (TypesManager): The Types of the request's database
        ledger (Any): The write ledger of the update
        template_name (str): The template's name
        changed (dict[str, Any]): The field's new definition
    """
    for document in types.find(criteria={TypeSchemaKey.GLOBAL_TEMPLATE_IDS.value: template_name}):
        ledger.updated(types, document[TypeSchemaKey.PUBLIC_ID.value], document)
        types.update({TypeSchemaKey.PUBLIC_ID.value: document[TypeSchemaKey.PUBLIC_ID.value]},
                     {TypeSchemaKey.FIELDS.value: _replaced(document.get(TypeSchemaKey.FIELDS.value) or [], changed)})


def fields_carrying_class(request_user: CmdbUser, field_class: str) -> list[dict[str, Any]]:
    """
    The fields carrying a field class, where they are defined (phase 12, D10)

    Args:
        request_user (CmdbUser): The caller
        field_class (str): The class name

    Returns:
        list[dict[str, Any]]: ``{source, source_id, name}`` per field
    """
    return [{FieldProtectionKey.SOURCE.value: row[FieldProtectionKey.SOURCE.value],
             FieldProtectionKey.SOURCE_ID.value: row[FieldProtectionKey.SOURCE_ID.value],
             FieldProtectionKey.NAME.value: row[FieldProtectionKey.NAME.value]}
            for row in field_protection_rows(request_user) if row[FieldProtectionKey.PROTECTION.value] == field_class]


def test_pattern(regex: str, samples: list[str]) -> list[dict[str, Any]]:
    """
    Runs a field pattern against sample values the way an object write does - anchored, on the write's time budget

    Args:
        regex (str): The pattern as a field would declare it
        samples (list[str]): The sample values

    Raises:
        HTTPException: 400 when the pattern breaks the field pattern rule

    Returns:
        list[dict[str, Any]]: ``{value, verdict}`` per sample - ``match`` / ``mismatch`` / ``timed_out``
    """
    field: dict[str, Any] = {FieldKey.NAME.value: SAMPLE_FIELD_NAME, FieldKey.TYPE.value: FieldType.TEXT.value,
                             FieldKey.REGEX.value: regex}
    abort_on_problems(find_field_pattern_errors([field]))
    rule: Any = build_field_value_rules([field])[SAMPLE_FIELD_NAME]
    budget: PatternBudget = PatternBudget()

    return [{PatternTestKey.VALUE.value: sample,
             PatternTestKey.VERDICT.value: match_field_pattern(rule, sample, budget, SAMPLE_FIELD_NAME).value}
            for sample in samples]
