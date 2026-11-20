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
A person's groups, read and changed from the person's side - ``GET`` / ``PATCH /objects/<public_id>/person_groups``

Membership is stored on the group side only (a group's base field ``members``), so:

  - **the read** answers the groups the reader may READ whose members hold the person, each as a person selection
    (``selector_render.selection_entry``: id, Type, kind, label, active state, ``system_ref``)
  - **the change** names groups to join and to leave. Every group named is judged before anything is written - a
    group object (400), one the writer may READ (403) and whose Type it may UPDATE (403). A group already as asked is
    left alone; every other one is written through the object update pipeline - its rules (the person selector rule,
    the user sync's lock), its ACL, its edit log and webhook - all of them or none (``apply_object_updates``)

The person itself is read (404 for an id naming no person, 403 for one the caller may not read) and never written
"""
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

from flask import abort

from cmdb.manager import ObjectsManager, TypesManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.object_model import CmdbObject, CmdbObjectFieldKey, CmdbObjectKey
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.person_type_constants import PersonGroupField
from cmdb.security.acl.builder import resolve_denied_type_ids
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.framework.ipam.reference_disclosure import hidden_types_of
from cmdb.framework.person_selector.selector_render import resolve_person_selections
from cmdb.framework.person_types.person_memberships import group_members, members_after, membership_targets
from cmdb.framework.person_types.person_object_references import MarkedObjects, resolve_marked_objects
from cmdb.framework.person_types.person_records import groups_of_persons
from cmdb.interface.rest_api.routes.routes_helper import UNKNOWN_REFERENCES_MSG
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_bulk_update_helper import (
    apply_object_updates,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_constants import (
    PERSON_GROUPS_BOTH_MESSAGE,
    PERSON_GROUPS_RESIDUE_MESSAGE,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_patch_helper import build_patched_object_data
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_write_context import (
    ObjectPayloadBuilder,
    ObjectWriteContext,
)
from cmdb.interface.rest_api.routes.user_management_routes.person_constants import (
    MEMBERSHIP_NOT_READABLE_MESSAGE,
    MEMBERSHIP_NOT_UPDATABLE_MESSAGE,
    PERSON_GROUP_LABEL,
    RECORD_LABELS,
    RECORD_NOT_FOUND_MESSAGE,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'read_marked_object',
    'judge_group_changes',
    'read_person_groups',
    'MembershipChange',
    'plan_membership_change',
    'write_membership_change',
    'change_person_groups',
]


def read_marked_object(marker: SpecialType, public_id: int, request_user: CmdbUser) -> CmdbObject:
    """
    A person or person group object - 404 when the id names no object of the marker, 403 when the caller may not read it

    Args:
        marker (SpecialType): PERSON or PERSON_GROUP
        public_id (int): The object's id
        request_user (CmdbUser): The caller

    Raises:
        HTTPException: 404
        AccessDeniedError: When the caller may not READ the object's Type
        ObjectsManagerGetError: When the read fails

    Returns:
        CmdbObject: The object
    """
    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
    stored: CmdbObject | None = objects_manager.get_object(
        public_id, request_user, AccessControlPermission.READ, as_dict=False,
    )

    if stored is None or stored.special_type != marker.value:
        abort(HTTPStatus.NOT_FOUND, RECORD_NOT_FOUND_MESSAGE.format(label=RECORD_LABELS[marker], public_id=public_id))

    return stored


def judge_group_changes(context: ObjectWriteContext, changed: set[int]) -> None:
    """
    Refuses a membership change naming a group that is none, or one the writer may not read or update

    Args:
        context (ObjectWriteContext): The writer and the managers
        changed (set[int]): The groups the change names - joined or left

    Raises:
        HTTPException: 400 for an id naming no group object, 403 for one the writer may not READ or UPDATE
    """
    marked: MarkedObjects = resolve_marked_objects(
        context.objects_manager, SpecialType.PERSON_GROUP, changed, hidden_types_of(context.request_user),
    )

    if marked.unknown:
        abort(HTTPStatus.BAD_REQUEST, UNKNOWN_REFERENCES_MSG.format(entity_label=PERSON_GROUP_LABEL,
                                                                     unknown=marked.unknown))

    if marked.unreadable:
        abort(HTTPStatus.FORBIDDEN, MEMBERSHIP_NOT_READABLE_MESSAGE.format(ids=marked.unreadable))

    not_updatable: set[int] = set(resolve_denied_type_ids(context.request_user, AccessControlPermission.UPDATE))
    refused: list[int] = sorted(
        document[CmdbObjectKey.PUBLIC_ID.value] for document in context.objects_manager.find(
            {CmdbObjectKey.PUBLIC_ID.value: {'$in': sorted(changed)}},
            projection={CmdbObjectKey.PUBLIC_ID.value: 1, CmdbObjectKey.TYPE_ID.value: 1},
        ) if document.get(CmdbObjectKey.TYPE_ID.value) in not_updatable
    ) if changed and not_updatable else []

    if refused:
        abort(HTTPStatus.FORBIDDEN, MEMBERSHIP_NOT_UPDATABLE_MESSAGE.format(ids=refused))


def _current_groups(objects_manager: ObjectsManager, person_id: int, request_user: CmdbUser) -> list[int]:
    """The groups the reader may READ whose members hold the person, ascending"""
    return groups_of_persons(objects_manager, [person_id], resolve_denied_type_ids(
        request_user, AccessControlPermission.READ))[person_id]


def read_person_groups(person_id: int, request_user: CmdbUser) -> list[dict[str, Any]]:
    """
    The groups the reader may READ whose members hold the person, each as a person selection

    Args:
        person_id (int): The person (already read: ``read_marked_object``)
        request_user (CmdbUser): The reader

    Raises:
        BaseManagerGetError: When a read fails

    Returns:
        list[dict[str, Any]]: The selections (``PersonSelectionKey``), ascending by group id
    """
    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
    types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
    group_ids: list[int] = _current_groups(objects_manager, person_id, request_user)
    visible: dict[int, dict[str, Any]] = resolve_person_selections(
        objects_manager, types_manager, hidden_types_of(request_user), set(group_ids),
    )

    return [visible[group_id] for group_id in group_ids if group_id in visible]


@dataclass(frozen=True)
class MembershipChange:
    """
    A judged membership change of one person: the groups it joins, and the groups to write

    Attributes:
        add (frozenset[int]): The groups the person joins - every other target is one it leaves
        targets (tuple[int, ...]): The groups that change, ascending; a group already as asked is not among them
    """
    add: frozenset[int] = frozenset()
    targets: tuple[int, ...] = ()


def plan_membership_change(context: ObjectWriteContext, current: set[int], add: set[int],
                           remove: set[int]) -> MembershipChange:
    """
    Judges a membership change before anything is written and names the groups it writes

    Args:
        context (ObjectWriteContext): The writer and the managers
        current (set[int]): The readable groups holding the person; empty for a new person
        add (set[int]): The groups it is to join
        remove (set[int]): The groups it is to leave

    Raises:
        HTTPException: 400 for a group both added and removed or naming no group object, 403 for one the writer may
            not READ or UPDATE (``judge_group_changes``)

    Returns:
        MembershipChange: The groups it joins and the groups to write
    """
    both: set[int] = add & remove

    if both:
        abort(HTTPStatus.BAD_REQUEST, PERSON_GROUPS_BOTH_MESSAGE.format(ids=sorted(both)))

    if add | remove:
        judge_group_changes(context, add | remove)

    return MembershipChange(frozenset(add), tuple(membership_targets(current, add, remove)))


def _members_payload(person_id: int, add: frozenset[int]) -> ObjectPayloadBuilder:
    """
    The payload builder of one group of a membership change: its stored members with the person added or taken out

    Args:
        person_id (int): The person
        add (frozenset[int]): The groups it joins - every other group written is one it leaves

    Returns:
        ObjectPayloadBuilder: Answers the group's stored object with only ``members`` changed
    """
    def _build(current_object: CmdbObject, current_type: CmdbType) -> dict[str, Any]:
        members: list[int] = group_members(CmdbObject.to_json(current_object))
        entry: dict[str, Any] = {
            CmdbObjectFieldKey.NAME.value: PersonGroupField.MEMBERS.value,
            CmdbObjectFieldKey.VALUE.value: members_after(members, person_id, current_object.get_public_id() in add),
        }

        return build_patched_object_data(current_object, {CmdbObjectKey.FIELDS.value: [entry]},
                                         current_type.get_mds_section_ids())

    return _build


def write_membership_change(person_id: int, change: MembershipChange, context: ObjectWriteContext,
                            person_payload: ObjectPayloadBuilder | None = None) -> None:
    """
    Writes a judged membership change - and, given its payload, the person's own update - all of them or none

    The person is written first, then each changed group, every write through the object update pipeline under one
    ledger (``apply_object_updates``)

    Args:
        person_id (int): The person
        change (MembershipChange): The judged change (``plan_membership_change``)
        context (ObjectWriteContext): The writer and the managers
        person_payload (ObjectPayloadBuilder | None): Builds the person's own update; None leaves the person alone

    Raises:
        HTTPException: What the object update answers for the person or a group (the earlier writes undone); 500
            naming the objects the undo could not put back
    """
    targets: list[int] = [person_id, *change.targets] if person_payload is not None else list(change.targets)

    if not targets:
        return

    groups_payload: ObjectPayloadBuilder = _members_payload(person_id, change.add)

    def _build(current_object: CmdbObject, current_type: CmdbType) -> dict[str, Any]:
        if person_payload is not None and current_object.get_public_id() == person_id:
            return person_payload(current_object, current_type)

        return groups_payload(current_object, current_type)

    apply_object_updates(targets, _build, None, context, residue_message=PERSON_GROUPS_RESIDUE_MESSAGE)


def change_person_groups(person_id: int, add: set[int], remove: set[int], request_user: CmdbUser) -> None:
    """
    The person joins and leaves groups - every group judged first, then every changed group written, all or none

    Args:
        person_id (int): The person (already read: ``read_marked_object``)
        add (set[int]): The groups it is to join
        remove (set[int]): The groups it is to leave
        request_user (CmdbUser): The writer

    Raises:
        HTTPException: 400 for a group both added and removed or naming no group object, 403 for one the writer may
            not READ or UPDATE, what the object update answers for a group (the earlier groups undone); 500 naming
            the groups the undo could not put back
        BaseManagerGetError: When a read fails
    """
    if not add | remove:
        return

    context: ObjectWriteContext = ObjectWriteContext.for_request(request_user)
    current: set[int] = set(_current_groups(context.objects_manager, person_id, request_user))
    write_membership_change(person_id, plan_membership_change(context, current, add, remove), context)
