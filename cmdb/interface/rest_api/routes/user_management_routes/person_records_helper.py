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
    them before anything is written (400 / 403) - then the person and each changed group are written through the
    object pipeline, all of them or none (``objects_person_groups_helper.write_membership_change``). A group the
    writer cannot see keeps its membership. A create inserts the person first, then writes its groups
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
from cmdb.framework.person_types.person_records import (
    PERSON_GROUPS_KEY,
    field_entries,
    groups_of_persons,
    record_of,
    record_stages,
)
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_helper import apply_object_insert
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_patch_helper import build_patched_object_data
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_single_delete import (
    delete_object_with_cleanup,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_write_context import (
    ObjectPayloadBuilder,
    ObjectWriteContext,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_person_groups_helper import (
    MembershipChange,
    plan_membership_change,
    read_marked_object,
    write_membership_change,
)
from cmdb.interface.rest_api.routes.user_management_routes.person_constants import (
    DEFAULT_TYPE_MISSING_MESSAGE,
    RECORD_LABELS,
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


def read_record(marker: SpecialType, public_id: int, request_user: CmdbUser) -> dict[str, Any]:
    """
    One record

    Args:
        marker (SpecialType): PERSON or PERSON_GROUP
        public_id (int): The record's id
        request_user (CmdbUser): The reader

    Raises:
        HTTPException: 404 / 403 (``read_marked_object``)

    Returns:
        dict[str, Any]: The record
    """
    record: dict[str, Any] = record_of(CmdbObject.to_json(read_marked_object(marker, public_id, request_user)), marker)

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
    change: MembershipChange | None = (
        plan_membership_change(context, set(), selected, set()) if selected else None
    )

    public_id: int = apply_object_insert({
        CmdbObjectKey.TYPE_ID.value: object_type.public_id,
        CmdbObjectKey.AUTHOR_ID.value: request_user.public_id,
        CmdbObjectKey.ACTIVE.value: True,
        CmdbObjectKey.FIELDS.value: entries,
    }, request_user, context.objects_manager, context.types_manager)

    if change is not None:
        write_membership_change(public_id, change, context)

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
        HTTPException: 404 / 403 (``read_marked_object``), what the object update and the membership check answer -
            the record and its groups are written all or none
        ObjectsManagerGetError | ObjectsManagerUpdateError | AccessDeniedError: from the object update
    """
    stored: CmdbObject = read_marked_object(marker, public_id, request_user)
    context: ObjectWriteContext = ObjectWriteContext.for_request(request_user)
    selected: set[int] | None = _selected_groups(marker, body)
    change = MembershipChange()

    if selected is not None:
        current: set[int] = set(
            groups_of_persons(context.objects_manager, [public_id], _denied(request_user))[public_id])
        change = plan_membership_change(context, current, selected - current, current - selected)

    write_membership_change(stored.get_public_id(), change, context, _fields_payload(field_entries(marker, body)))


def delete_record(marker: SpecialType, public_id: int, request_user: CmdbUser) -> dict[str, Any]:
    """
    Deletes the record's object with every guard and clean-up, answering the record as it was

    Args:
        marker (SpecialType): PERSON or PERSON_GROUP
        public_id (int): The record's id
        request_user (CmdbUser): The writer

    Raises:
        HTTPException: 404 / 403 (``read_marked_object``), what the object delete answers

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


def _fields_payload(entries: list[dict[str, Any]]) -> ObjectPayloadBuilder:
    """
    The payload builder of a record update: the stored object with the record keys' field values set, every other
    value kept

    Args:
        entries (list[dict[str, Any]]): The ``{name, value}`` entries to set

    Returns:
        ObjectPayloadBuilder: Answers the merged object
    """
    def _build(current_object: CmdbObject, current_type: CmdbType) -> dict[str, Any]:
        return build_patched_object_data(current_object, {CmdbObjectKey.FIELDS.value: entries},
                                         current_type.get_mds_section_ids())

    return _build
