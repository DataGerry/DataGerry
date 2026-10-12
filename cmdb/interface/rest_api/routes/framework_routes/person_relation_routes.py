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
API routes around persons and person groups - the CmdbObjects of the PERSON / PERSON_GROUP SpecialTypes

* ``GET /types`` - the CmdbType carrying each person SpecialType (null while it was not created)
* ``GET /candidates?kind=`` - what a person field of that PersonRefKind may select
* ``GET /<object_id>`` - a person's group memberships, a group's members, and the objects either is assigned
  to through a person field
* ``POST /<group_id>/members`` / ``DELETE /<group_id>/members/<person_id>`` - add a person to a group or remove
  them. Membership is stored in the group's MEMBERS field, so both are an ordinary update of the group and run
  the full object update pipeline (validation, version, webhook, edit log)

Persons are a standard feature: the routes are guarded by the object rights and the type ACLs, not by a
licence. An object of a type the caller may not read is left out of every list
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort, request
from werkzeug import Response

from cmdb.manager import ObjectsManager, TypesManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.object_model import CmdbObject
from cmdb.models.object_model.cmdb_object_helpers import extract_field_value
from cmdb.models.right_model.right_constants import ObjectRightName
from cmdb.models.special_type_model.person_constants import PersonGroupField, PersonRefKind, PersonValueKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser

from cmdb.framework.person.directory import (
    get_assignments,
    get_member_ids,
    get_memberships,
    get_person_type_ids,
    list_candidates,
    resolve_person_kinds,
    object_label,
)
from cmdb.framework.person.person_values import is_public_id, selections_of
from cmdb.security.acl.builder import resolve_denied_type_ids
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import handle_route_errors, insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import DefaultResponse
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_helper import apply_object_update
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_write_context import ObjectWriteContext
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_patch_helper import (
    build_patched_object_data,
    validate_object_patch_payload,
)
from cmdb.errors.security import AccessDeniedError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

person_relations_blueprint = APIBlueprint('person_relations', __name__)

KIND_PARAM: str = 'kind'
PERSON_ID_KEY: str = 'person_id'


def _managers(request_user: CmdbUser) -> tuple[ObjectsManager, TypesManager, list[int]]:
    """
    The managers of a request and the CmdbTypes the caller may not read

    Args:
        request_user (CmdbUser): The CmdbUser making the request

    Returns:
        tuple[ObjectsManager, TypesManager, list[int]]: The managers and the denied type ids
    """
    return (
        ManagerProvider.get_manager(ManagerType.OBJECTS, request_user),
        ManagerProvider.get_manager(ManagerType.TYPES, request_user),
        resolve_denied_type_ids(request_user, AccessControlPermission.READ),
    )


def _read_person_object(
        objects_manager: ObjectsManager,
        types_manager: TypesManager,
        object_id: int,
        request_user: CmdbUser) -> tuple[dict[str, Any], str]:
    """
    Reads a person or group object the caller may read, and its kind

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        object_id (int): public_id of the object
        request_user (CmdbUser): The CmdbUser making the request

    Raises:
        HTTPException: 403 when the caller may not read it, 404 when it is missing or no person or group

    Returns:
        tuple[dict[str, Any], str]: The object document and 'PERSON' | 'PERSON_GROUP'
    """
    try:
        document: dict[str, Any] | None = objects_manager.get_object(
            object_id, request_user, AccessControlPermission.READ, as_dict=True,
        )
    except AccessDeniedError:
        abort(403, "Access denied: You do not have sufficient permissions to read this Object!")

    kind: str | None = resolve_person_kinds(objects_manager, types_manager, [object_id]).get(object_id)

    if not document or kind is None:
        abort(404, f"No person or person group with ID:{object_id} was found!")

    return document, kind


def _relations_payload(
        objects_manager: ObjectsManager,
        types_manager: TypesManager,
        document: dict[str, Any],
        kind: str,
        denied: list[int]) -> dict[str, Any]:
    """
    The relations of one person or group, as GET /<object_id> answers them

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        document (dict[str, Any]): The person or group object
        kind (str): 'PERSON' or 'PERSON_GROUP'
        denied (list[int]): The CmdbTypes the caller may not read

    Returns:
        dict[str, Any]: {'ref_type', 'memberships', 'members', 'assignments'}
    """
    object_id: int = document['public_id']
    memberships: list[dict[str, Any]] = []
    members: list[dict[str, Any]] = []

    if kind == SpecialType.PERSON.value:
        memberships = get_memberships(objects_manager, types_manager, object_id, denied)
    else:
        # Resolved through the readable persons, so a member of a type the caller may not read is left out
        persons_by_id: dict[int, dict[str, Any]] = {
            candidate[PersonValueKey.ID.value]: candidate
            for candidate in list_candidates(objects_manager, types_manager, PersonRefKind.PERSON.value, denied)
        }
        members = sorted(
            (persons_by_id[member_id] for member_id in get_member_ids(document) if member_id in persons_by_id),
            key=lambda entry: (entry['label'].casefold(), entry[PersonValueKey.ID.value]),
        )

    return {
        PersonValueKey.REF_TYPE.value: kind,
        'label': object_label(document, kind),
        'memberships': memberships,
        'members': members,
        'assignments': get_assignments(objects_manager, types_manager, object_id, denied),
    }


@person_relations_blueprint.route('/types', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@person_relations_blueprint.protect(auth=True, right=ObjectRightName.VIEW.value)
@handle_route_errors("while retrieving the person types")
def get_person_types(request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route answering the CmdbType of each person SpecialType

    Args:
        request_user (CmdbUser): The CmdbUser making the request

    Returns:
        DefaultResponse: {'PERSON': type id | None, 'PERSON_GROUP': type id | None}
    """
    types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

    return DefaultResponse({
        kind: (sorted(type_ids)[0] if type_ids else None)
        for kind, type_ids in get_person_type_ids(types_manager).items()
    }).make_response()


@person_relations_blueprint.route('/candidates', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@person_relations_blueprint.protect(auth=True, right=ObjectRightName.VIEW.value)
@handle_route_errors("while retrieving the selectable persons")
def get_person_candidates(request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route answering what a person field of the given kind may select

    Args:
        request_user (CmdbUser): The CmdbUser making the request

    Raises:
        HTTPException: 400 for a 'kind' that is no PersonRefKind

    Returns:
        DefaultResponse: [{'ref_type', 'id', 'label', 'type_id'}], sorted by label
    """
    ref_kind: str = request.args.get(KIND_PARAM, default=PersonRefKind.BOTH.value)

    if not PersonRefKind.is_valid(ref_kind):
        abort(400, f"'{KIND_PARAM}' must be one of {[member.value for member in PersonRefKind]}!")

    objects_manager, types_manager, denied = _managers(request_user)

    return DefaultResponse(list_candidates(objects_manager, types_manager, ref_kind, denied)).make_response()


@person_relations_blueprint.route('/<int:object_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@person_relations_blueprint.protect(auth=True, right=ObjectRightName.VIEW.value)
@handle_route_errors("while retrieving the relations of the person with ID:{object_id}")
def get_person_relations(object_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route answering the memberships, members and assignments of a person or group

    Args:
        object_id (int): public_id of the person or group object
        request_user (CmdbUser): The CmdbUser making the request

    Returns:
        DefaultResponse: {'ref_type', 'label', 'memberships', 'members', 'assignments'}
    """
    objects_manager, types_manager, denied = _managers(request_user)
    document, kind = _read_person_object(objects_manager, types_manager, object_id, request_user)

    return DefaultResponse(_relations_payload(objects_manager, types_manager, document, kind, denied)).make_response()


def _write_members(group_id: int, change: Any, request_user: CmdbUser) -> Response:
    """
    Rewrites a group's MEMBERS field through the full object update pipeline

    Args:
        group_id (int): public_id of the group object
        change (Callable[[list[dict[str, Any]]], list[dict[str, Any]]]): Maps the stored selections to the new
        request_user (CmdbUser): The CmdbUser making the request

    Raises:
        HTTPException: 404 when the object is no group, 400 when the new value is refused, 403 without access

    Returns:
        Response: The group's relations, as GET /<group_id> answers them
    """
    objects_manager, types_manager, denied = _managers(request_user)
    document, kind = _read_person_object(objects_manager, types_manager, group_id, request_user)

    if kind != SpecialType.PERSON_GROUP.value:
        abort(404, f"The Object with ID:{group_id} is no person group!")

    current: list[Any] = selections_of(extract_field_value(document, PersonGroupField.MEMBERS.value))
    patch_data: dict[str, Any] = validate_object_patch_payload({
        'fields': [{'name': PersonGroupField.MEMBERS.value, 'value': change(current)}],
    })

    current_object: CmdbObject = CmdbObject.from_data(document)
    current_type: CmdbType | None = objects_manager.get_object_type(current_object.get_type_id())

    if not current_type:
        abort(500, "Type of Object not found in database!")

    merged_data: dict[str, Any] = build_patched_object_data(
        current_object, patch_data, current_type.get_mds_section_ids(),
    )

    try:
        apply_object_update(group_id, merged_data, None, ObjectWriteContext.for_request(request_user))
    except AccessDeniedError:
        abort(403, "Access denied: You do not have sufficient permissions to perform this action!")

    updated, _ = _read_person_object(objects_manager, types_manager, group_id, request_user)

    return DefaultResponse(_relations_payload(objects_manager, types_manager, updated, kind, denied)).make_response()


@person_relations_blueprint.route('/<int:group_id>/members', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@person_relations_blueprint.protect(auth=True, right=ObjectRightName.EDIT.value)
@handle_route_errors("while adding a member to the person group with ID:{group_id}")
def add_person_group_member(group_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route adding a person to a group; body ``{"person_id": <int>}``

    Adding a person the group already lists changes nothing. Whether the id names a person is judged by the
    person field enforcement of the update

    Args:
        group_id (int): public_id of the group object
        request_user (CmdbUser): The CmdbUser making the request

    Raises:
        HTTPException: 400 when 'person_id' is missing or no public_id

    Returns:
        DefaultResponse: The group's relations
    """
    body: Any = request.get_json(silent=True)
    person_id: Any = body.get(PERSON_ID_KEY) if isinstance(body, dict) else None

    if not is_public_id(person_id):
        abort(400, f"'{PERSON_ID_KEY}' must be the public_id of a person!")

    def add(current: list[Any]) -> list[Any]:
        if any(isinstance(entry, dict) and entry.get(PersonValueKey.ID.value) == person_id for entry in current):
            return current

        return [*current, {PersonValueKey.REF_TYPE.value: SpecialType.PERSON.value, PersonValueKey.ID.value: person_id}]

    return _write_members(group_id, add, request_user)


@person_relations_blueprint.route('/<int:group_id>/members/<int:person_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@person_relations_blueprint.protect(auth=True, right=ObjectRightName.EDIT.value)
@handle_route_errors("while removing a member from the person group with ID:{group_id}")
def remove_person_group_member(group_id: int, person_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route removing a person from a group

    Removing a person the group does not list changes nothing

    Args:
        group_id (int): public_id of the group object
        person_id (int): public_id of the person object
        request_user (CmdbUser): The CmdbUser making the request

    Returns:
        DefaultResponse: The group's relations
    """
    def remove(current: list[Any]) -> list[Any]:
        return [
            entry for entry in current
            if not (isinstance(entry, dict) and entry.get(PersonValueKey.ID.value) == person_id)
        ]

    return _write_members(group_id, remove, request_user)
