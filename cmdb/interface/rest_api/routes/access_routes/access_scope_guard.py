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
Keeps the stored scope conditions valid (phase 9 step 3, ruled R11) - the route side of
``scope_compiler.scope_staleness``

Three writes change what a stored condition compares: a Type update (and the type import), a global section template
update (copied into every Type carrying its section) and a scope role update (its Types). Each is refused with a 400
naming the assignments when it would leave a condition comparing a field its Types no longer carry with that kind.
Reads one projected list of the conditional assignments first and nothing more while there is none - the common case.
``GET /access/types/<id>/assignments`` answers every assignment with its scope: the pre-check of the type editor
"""
from typing import Any

from flask import abort

from cmdb.manager import AccessAssignmentsManager, ScopeRolesManager, SectionTemplatesManager, TypesManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.access_model import ALL_TYPES, AccessAssignmentKey, ScopeRoleKey
from cmdb.models.section_template_model import CmdbSectionTemplate
from cmdb.models.section_template_model.section_template_constants import SectionTemplateKey
from cmdb.models.type_model import CmdbType, FieldKey, SectionType, TypeSchemaKey
from cmdb.models.user_model import CmdbUser
from cmdb.framework.scope_compiler import (
    ScopeField,
    field_views,
    field_views_of_document,
    role_change_problems,
    type_change_problems,
)
from cmdb.interface.rest_api.routes.routes_helper import abort_on_problems
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'scope_field_change_blocker',
    'guard_scope_field_change',
    'guard_template_scope_change',
    'guard_role_scope_change',
]

# The parts of a Type a scope condition reads
_TYPE_FIELDS_PROJECTION: dict[str, int] = {'_id': 0, TypeSchemaKey.PUBLIC_ID.value: 1, TypeSchemaKey.FIELDS.value: 1,
                                           TypeSchemaKey.RENDER_META.value: 1}


def _conditional_assignments(request_user: CmdbUser) -> list[dict[str, Any]]:
    """
    The stored conditional assignments

    Args:
        request_user (CmdbUser): The caller - names the database

    Raises:
        AccessAssignmentsManagerGetError: When the read fails

    Returns:
        list[dict[str, Any]]: The assignments as stored
    """
    manager: AccessAssignmentsManager = ManagerProvider.get_manager(ManagerType.ACCESS_ASSIGNMENTS, request_user)

    return manager.conditional_assignments()


def _covering(request_user: CmdbUser, assignments: list[dict[str, Any]], type_ids: set[int]) -> list[dict[str, Any]]:
    """
    The assignments whose role covers one of the Types

    Args:
        request_user (CmdbUser): The caller
        assignments (list[dict[str, Any]]): Conditional assignments
        type_ids (set[int]): The Types

    Raises:
        ScopeRolesManagerGetError: When the roles could not be read

    Returns:
        list[dict[str, Any]]: Those covering any of the Types
    """
    roles_manager: ScopeRolesManager = ManagerProvider.get_manager(ManagerType.SCOPE_ROLES, request_user)
    roles: dict[int, Any] = {role[ScopeRoleKey.PUBLIC_ID.value]: role[ScopeRoleKey.TYPES.value]
                             for role in roles_manager.roles_by_ids(
                                 sorted({a[AccessAssignmentKey.ROLE_ID.value] for a in assignments}))}

    def covers(role_types: Any) -> bool:
        return role_types == ALL_TYPES or bool(type_ids & set(role_types or []))

    return [assignment for assignment in assignments
            if covers(roles.get(assignment[AccessAssignmentKey.ROLE_ID.value], []))]


def scope_field_change_blocker(request_user: CmdbUser, old_type: CmdbType, new_type: CmdbType) -> str | None:
    """
    Reports why a Type update would leave stored scope conditions comparing a field it no longer carries as they do

    Args:
        request_user (CmdbUser): The caller
        old_type (CmdbType): The stored Type
        new_type (CmdbType): The Type the update would store

    Raises:
        AccessAssignmentsManagerGetError | ScopeRolesManagerGetError: When a read fails

    Returns:
        str | None: The problems joined, or None when the update keeps every condition valid
    """
    assignments: list[dict[str, Any]] = _conditional_assignments(request_user)

    if not assignments:
        return None

    problems: list[str] = type_change_problems(
        old_type.public_id,
        field_views(old_type.get_fields(), old_type.get_all_mds_fields()),
        field_views(new_type.get_fields(), new_type.get_all_mds_fields()),
        _covering(request_user, assignments, {old_type.public_id}),
    )

    return ' '.join(problems) or None


def guard_scope_field_change(request_user: CmdbUser, old_type: CmdbType, new_type: CmdbType) -> None:
    """
    Aborts a Type update that would leave stored scope conditions invalid

    Args:
        request_user (CmdbUser): The caller
        old_type (CmdbType): The stored Type
        new_type (CmdbType): The Type the update would store

    Raises:
        HTTPException: 400 naming the fields and the assignments
    """
    if blocker := scope_field_change_blocker(request_user, old_type, new_type):
        abort(400, blocker)


def guard_template_scope_change(request_user: CmdbUser, section_templates_manager: SectionTemplatesManager,
                                current_template: CmdbSectionTemplate, params: dict[str, Any]) -> None:
    """
    Aborts a global section template update that would leave stored scope conditions invalid - the update is copied
    into every Type carrying the section, past the Type routes' guard

    Args:
        request_user (CmdbUser): The caller
        section_templates_manager (SectionTemplatesManager): Reads the Types using the template
        current_template (CmdbSectionTemplate): The stored template
        params (dict[str, Any]): The validated update payload, its ``fields`` parsed

    Raises:
        HTTPException: 400 naming the fields and the assignments
    """
    if not current_template.is_global:
        return

    assignments: list[dict[str, Any]] = _conditional_assignments(request_user)

    if not assignments:
        return

    name: str = params[SectionTemplateKey.NAME]
    in_rows: bool = current_template.type == SectionType.MDS_SECTION.value
    before: dict[str, ScopeField] = _template_views(current_template.fields, in_rows)
    after: dict[str, ScopeField] = _template_views(params.get(SectionTemplateKey.FIELDS) or [], in_rows)
    problems: list[str] = []

    for a_type in section_templates_manager.get_types_using_template(name):
        if a_type.get_section(name) is not None:
            problems.extend(type_change_problems(a_type.public_id, before, after,
                                                 _covering(request_user, assignments, {a_type.public_id})))

    abort_on_problems(problems)


def _template_views(fields: list[Any], in_rows: bool) -> dict[str, ScopeField]:
    """
    A template's fields as a scope condition sees them

    Args:
        fields (list[Any]): The template's field definitions
        in_rows (bool): Whether the template is a multi-data section

    Returns:
        dict[str, ScopeField]: By field name
    """
    if not in_rows:
        return field_views(fields, [])

    names: list[Any] = [field.get(FieldKey.NAME.value) for field in fields if isinstance(field, dict)]

    return field_views(fields, [name for name in names if isinstance(name, str)])


def guard_role_scope_change(request_user: CmdbUser, role_id: int, written_role: dict[str, Any]) -> None:
    """
    Aborts a scope role update that would leave the conditions of its assignments unresolvable on its new Types

    Args:
        request_user (CmdbUser): The caller
        role_id (int): The role's public_id
        written_role (dict[str, Any]): The role as it would be stored

    Raises:
        HTTPException: 400 naming the assignments and why
        AccessAssignmentsManagerGetError | TypesManagerGetError: When a read fails
    """
    assignments: list[dict[str, Any]] = [assignment for assignment in _conditional_assignments(request_user)
                                         if assignment[AccessAssignmentKey.ROLE_ID.value] == role_id]

    if not assignments:
        return

    types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
    role_types: Any = written_role.get(ScopeRoleKey.TYPES.value)
    criteria: dict[str, Any] = {} if role_types == ALL_TYPES else \
        {TypeSchemaKey.PUBLIC_ID.value: {'$in': list(role_types or [])}}
    documents: list[dict[str, Any]] = types_manager.find(criteria=criteria, projection=_TYPE_FIELDS_PROJECTION)

    abort_on_problems(role_change_problems(role_id, assignments,
                                           [field_views_of_document(document) for document in documents]))
