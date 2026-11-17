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
The old ``/persons`` and ``/person_groups`` routes as a layer over the person and group objects

Every read and write goes to the objects of the Types carrying PERSON / PERSON_GROUP, through the object pipeline -
its rules, its ACL, its logs and webhooks; a record is an object in the old document shape
(``person_types.person_records``):

  - **reads** list the objects of every Type carrying the marker the caller may READ, the client's filter and sort run
    on the record keys; a single read is a 404 for an object that is no person / group and a 403 for one the caller
    may not read
  - **creates** go into the default Type of the marker (the system Type), the record keys becoming its base fields
  - **updates** set the record keys the body carries, every other field kept
  - **a person's groups** are the groups whose ``members`` hold it. A person write carrying ``groups`` edits those
    members: every group added or removed must be a group object the writer may READ and UPDATE - judged for all of
    them before anything is written (400 / 403) - then each changed group is written through the object pipeline. A
    group the writer cannot see keeps its membership. A write failing midway leaves the earlier ones (ruled)
  - **deletes** are the object delete (``delete_object_with_cleanup``): every guard and clean-up, the person taken out
    of every group's members and out of the ISMS documents
"""
from http import HTTPStatus
from typing import Any

from flask import abort

from cmdb.manager import ObjectsManager, TypesManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager.query_builder import BuilderParameters
from cmdb.models.object_model import CmdbObject
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey, CmdbObjectFieldKey
from cmdb.models.type_model import CmdbType, TypeSchemaKey
from cmdb.models.user_model import CmdbUser
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.person_type_constants import PersonGroupField
from cmdb.security.acl.builder import resolve_denied_type_ids
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.utils import Builder
from cmdb.framework.ipam.reference_disclosure import hidden_types_of
from cmdb.framework.person_types.person_object_references import MarkedObjects, resolve_marked_objects
from cmdb.framework.person_types.person_records import (
    GROUP_MEMBERS_KEY,
    PERSON_GROUPS_KEY,
    field_entries,
    groups_of_persons,
    record_of,
    record_stages,
)
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.rest_api.routes.routes_helper import UNKNOWN_REFERENCES_MSG
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_helper import (
    apply_object_insert,
    apply_object_update,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_patch_helper import build_patched_object_data
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_single_delete import (
    delete_object_with_cleanup,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_write_context import ObjectWriteContext
from cmdb.interface.rest_api.routes.user_management_routes.person_constants import (
    DEFAULT_TYPE_MISSING_MESSAGE,
    MEMBERSHIP_NOT_UPDATABLE_MESSAGE,
    MEMBERSHIP_NOT_READABLE_MESSAGE,
    PERSON_GROUP_LABEL,
    RECORD_LABELS,
    RECORD_NOT_FOUND_MESSAGE,
)
# -------------------------------------------------------------------------------------------------------------------- #

# The base fields a new record's object starts empty in, by marker - those the body does not carry
_EMPTY_BASE_FIELDS: dict[SpecialType, dict[str, Any]] = {
    SpecialType.PERSON: {},
    SpecialType.PERSON_GROUP: {PersonGroupField.MEMBERS.value: []},
}


def _objects(request_user: CmdbUser) -> ObjectsManager:
    """The caller's objects manager"""
    return ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)


def _denied(request_user: CmdbUser, permission: AccessControlPermission = AccessControlPermission.READ) -> list[int]:
    """The Types the caller may not access with the permission"""
    return resolve_denied_type_ids(request_user, permission)


def with_groups(records: list[dict[str, Any]], marker: SpecialType, objects_manager: ObjectsManager,
                request_user: CmdbUser) -> list[dict[str, Any]]:
    """
    Adds each person record's ``groups`` - the readable groups holding it; group records are returned as they are

    Args:
        records (list[dict[str, Any]]): The records, changed in place
        marker (SpecialType): The records' marker
        objects_manager (ObjectsManager): db interface for CmdbObjects
        request_user (CmdbUser): The reader

    Returns:
        list[dict[str, Any]]: The records
    """
    if marker != SpecialType.PERSON or not records:
        return records

    groups: dict[int, list[int]] = groups_of_persons(
        objects_manager, [record[CmdbObjectKey.PUBLIC_ID.value] for record in records], _denied(request_user),
    )

    for record in records:
        record[PERSON_GROUPS_KEY] = groups[record[CmdbObjectKey.PUBLIC_ID.value]]

    return records


def list_records(marker: SpecialType, params: CollectionParameters,
                 request_user: CmdbUser) -> tuple[list[dict[str, Any]], int]:
    """
    One page of the records of every Type carrying the marker the caller may READ, and their total

    The client's filter (a document or a pipeline) and sort run on the record keys, after the reshape

    Args:
        marker (SpecialType): PERSON or PERSON_GROUP
        params (CollectionParameters): The page, filter and sort
        request_user (CmdbUser): The reader

    Raises:
        BaseManagerIterationError: When the read fails

    Returns:
        tuple[list[dict[str, Any]], int]: The records and the total
    """
    objects_manager: ObjectsManager = _objects(request_user)
    client: Any = params.filter

    if isinstance(client, dict):
        client = [Builder.match_(client)] if client else []

    builder_params = BuilderParameters(**{
        **CollectionParameters.get_builder_params(params),
        'criteria': [*record_stages(marker, _denied(request_user)), *(client or [])],
    })
    records, total = objects_manager.iterate_query(builder_params)

    return with_groups(records, marker, objects_manager, request_user), total


def read_record_object(marker: SpecialType, public_id: int, request_user: CmdbUser) -> CmdbObject:
    """
    The object behind a record - 404 when it is no object of the marker, 403 when the caller may not read it

    Args:
        marker (SpecialType): PERSON or PERSON_GROUP
        public_id (int): The record's id
        request_user (CmdbUser): The caller

    Raises:
        HTTPException: 404 / 403
        ObjectsManagerGetError: When the read fails

    Returns:
        CmdbObject: The object
    """
    stored: CmdbObject | None = _objects(request_user).get_object(
        public_id, request_user, AccessControlPermission.READ, as_dict=False,
    )

    if stored is None or stored.special_type != marker.value:
        abort(HTTPStatus.NOT_FOUND, RECORD_NOT_FOUND_MESSAGE.format(label=RECORD_LABELS[marker], public_id=public_id))

    return stored


def read_record(marker: SpecialType, public_id: int, request_user: CmdbUser) -> dict[str, Any]:
    """
    One record

    Args:
        marker (SpecialType): PERSON or PERSON_GROUP
        public_id (int): The record's id
        request_user (CmdbUser): The reader

    Raises:
        HTTPException: 404 / 403 (``read_record_object``)

    Returns:
        dict[str, Any]: The record
    """
    record: dict[str, Any] = record_of(CmdbObject.to_json(read_record_object(marker, public_id, request_user)), marker)

    return with_groups([record], marker, _objects(request_user), request_user)[0]


def _default_type(marker: SpecialType, request_user: CmdbUser) -> CmdbType:
    """
    The default Type of the marker - the system Type the migration of the old records stored

    Raises:
        HTTPException: 400 when the system has none - a new system, or one whose configuration was reset

    Returns:
        CmdbType: The Type
    """
    types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
    found: dict[str, Any] | None = types_manager.get_one_by({
        TypeSchemaKey.SPECIAL_TYPE.value: marker.value, TypeSchemaKey.SYSTEM_TYPE.value: True,
    })

    if found is None:
        abort(HTTPStatus.BAD_REQUEST, DEFAULT_TYPE_MISSING_MESSAGE.format(label=RECORD_LABELS[marker]))

    return CmdbType.from_data(found)


def create_record(marker: SpecialType, body: dict[str, Any], request_user: CmdbUser) -> int:
    """
    Creates the record's object in the default Type of the marker, then - for a person - its memberships

    Args:
        marker (SpecialType): PERSON or PERSON_GROUP
        body (dict[str, Any]): The validated record body
        request_user (CmdbUser): The writer

    Raises:
        HTTPException: what the object create and the membership check answer
        ObjectsManagerInsertError | ObjectsManagerGetError | AccessDeniedError: from the object create

    Returns:
        int: The new object id
    """
    object_type: CmdbType = _default_type(marker, request_user)
    entries: list[dict[str, Any]] = field_entries(marker, body)
    named: set[str] = {entry[CmdbObjectFieldKey.NAME.value] for entry in entries}
    entries += [{CmdbObjectFieldKey.NAME.value: name, CmdbObjectFieldKey.VALUE.value: value}
                for name, value in _EMPTY_BASE_FIELDS[marker].items() if name not in named]
    selected: set[int] | None = _selected_groups(marker, body)
    context: ObjectWriteContext = ObjectWriteContext.for_request(request_user)

    if selected:
        _judge_membership(context, None, selected)

    public_id: int = apply_object_insert({
        CmdbObjectKey.TYPE_ID.value: object_type.public_id,
        CmdbObjectKey.AUTHOR_ID.value: request_user.public_id,
        CmdbObjectKey.ACTIVE.value: True,
        CmdbObjectKey.FIELDS.value: entries,
    }, request_user, context.objects_manager, context.types_manager)

    if selected:
        _write_membership(context, public_id, set(), selected)

    return public_id


def update_record(marker: SpecialType, public_id: int, body: dict[str, Any], request_user: CmdbUser) -> None:
    """
    Sets the record keys the body carries on the object, every other field kept; for a person also its memberships

    Args:
        marker (SpecialType): PERSON or PERSON_GROUP
        public_id (int): The record's id
        body (dict[str, Any]): The validated record body
        request_user (CmdbUser): The writer

    Raises:
        HTTPException: 404 / 403 (``read_record_object``), what the object update and the membership check answer
        ObjectsManagerGetError | ObjectsManagerUpdateError | AccessDeniedError: from the object update
    """
    stored: CmdbObject = read_record_object(marker, public_id, request_user)
    context: ObjectWriteContext = ObjectWriteContext.for_request(request_user)
    selected: set[int] | None = _selected_groups(marker, body)
    current: set[int] = set()

    if selected is not None:
        current = set(groups_of_persons(context.objects_manager, [public_id], _denied(request_user))[public_id])
        _judge_membership(context, current, selected)

    _patch_fields(context, stored, field_entries(marker, body))

    if selected is not None:
        _write_membership(context, public_id, current, selected)


def delete_record(marker: SpecialType, public_id: int, request_user: CmdbUser) -> dict[str, Any]:
    """
    Deletes the record's object with every guard and clean-up, answering the record as it was

    Args:
        marker (SpecialType): PERSON or PERSON_GROUP
        public_id (int): The record's id
        request_user (CmdbUser): The writer

    Raises:
        HTTPException: 404 / 403 (``read_record_object``), what the object delete answers

    Returns:
        dict[str, Any]: The deleted record
    """
    record: dict[str, Any] = read_record(marker, public_id, request_user)
    delete_object_with_cleanup(public_id, request_user)

    return record

# --------------------------------------------------- membership ----------------------------------------------------- #

def _selected_groups(marker: SpecialType, body: dict[str, Any]) -> set[int] | None:
    """A person body's groups as a set; None when it carries none or is no person"""
    if marker != SpecialType.PERSON or PERSON_GROUPS_KEY not in body:
        return None

    return set(body.get(PERSON_GROUPS_KEY) or [])


def _judge_membership(context: ObjectWriteContext, current: set[int] | None, selected: set[int]) -> None:
    """
    Refuses a membership change naming a group that is none, or one the writer may not read or update

    Args:
        context (ObjectWriteContext): The writer and the managers
        current (set[int] | None): The readable groups holding the person; None for a new person
        selected (set[int]): The groups the body names

    Raises:
        HTTPException: 400 for an id naming no group object, 403 for one the writer may not READ or UPDATE
    """
    changed: set[int] = selected ^ (current or set())
    marked: MarkedObjects = resolve_marked_objects(
        context.objects_manager, SpecialType.PERSON_GROUP, changed, hidden_types_of(context.request_user),
    )

    if marked.unknown:
        abort(HTTPStatus.BAD_REQUEST, UNKNOWN_REFERENCES_MSG.format(entity_label=PERSON_GROUP_LABEL,
                                                                     unknown=marked.unknown))

    if marked.unreadable:
        abort(HTTPStatus.FORBIDDEN, MEMBERSHIP_NOT_READABLE_MESSAGE.format(ids=marked.unreadable))

    not_updatable: set[int] = set(_denied(context.request_user, AccessControlPermission.UPDATE))
    refused: list[int] = sorted(
        document[CmdbObjectKey.PUBLIC_ID.value] for document in context.objects_manager.find(
            {CmdbObjectKey.PUBLIC_ID.value: {'$in': sorted(changed)}},
            projection={CmdbObjectKey.PUBLIC_ID.value: 1, CmdbObjectKey.TYPE_ID.value: 1},
        ) if document.get(CmdbObjectKey.TYPE_ID.value) in not_updatable
    ) if changed and not_updatable else []

    if refused:
        abort(HTTPStatus.FORBIDDEN, MEMBERSHIP_NOT_UPDATABLE_MESSAGE.format(ids=refused))


def _write_membership(context: ObjectWriteContext, person_id: int, current: set[int], selected: set[int]) -> None:
    """
    Adds the person to the groups it joins and takes it out of the groups it leaves - one object update per group

    Args:
        context (ObjectWriteContext): The writer and the managers
        person_id (int): The person
        current (set[int]): The readable groups holding it before
        selected (set[int]): The groups it is to be in
    """
    for group_id in sorted(selected ^ current):
        group: CmdbObject | None = context.objects_manager.get_object(group_id, as_dict=False)

        if group is None:
            continue

        members: list[int] = list(
            record_of(CmdbObject.to_json(group), SpecialType.PERSON_GROUP)[GROUP_MEMBERS_KEY] or [])
        members = [*members, person_id] if group_id in selected else [m for m in members if m != person_id]
        _patch_fields(context, group, [{CmdbObjectFieldKey.NAME.value: PersonGroupField.MEMBERS.value,
                                        CmdbObjectFieldKey.VALUE.value: members}])


def _patch_fields(context: ObjectWriteContext, stored: CmdbObject, entries: list[dict[str, Any]]) -> None:
    """
    Sets field values on a stored object through the object update pipeline, every other value kept

    Args:
        context (ObjectWriteContext): The writer and the managers
        stored (CmdbObject): The object as stored
        entries (list[dict[str, Any]]): The ``{name, value}`` entries to set
    """
    object_type: CmdbType | None = context.objects_manager.get_object_type(stored.get_type_id())
    merged: dict[str, Any] = build_patched_object_data(
        stored, {CmdbObjectKey.FIELDS.value: entries}, object_type.get_mds_section_ids() if object_type else set(),
    )
    apply_object_update(stored.get_public_id(), merged, None, context)
