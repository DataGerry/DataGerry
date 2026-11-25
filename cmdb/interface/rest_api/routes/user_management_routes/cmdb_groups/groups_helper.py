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
Helper methods shared by the CmdbUserGroup REST routes

Both write routes refuse a ``rights`` list naming a right the right tree does not know
(``abort_if_unknown_rights``), with one message - the schema only checks that every entry is a string.

The delete route's refusals (``resolve_move_target``, ``abort_if_members_would_be_stranded``,
``abort_if_admin_would_be_deleted``) all run before anything is written. ``redistribute_members`` is the one write
path for the members: it reads them once, records the exact inverse in the request's WriteLedger, and then writes by
those ids. A member in other groups too only loses the group; the action (MOVE / DELETE) is about the **sole**
members, whose only group it is - so the refusals ask about those
"""
from collections.abc import Iterable
from typing import Any
from flask import abort

from cmdb.framework.write_ledger import WriteLedger
from cmdb.manager import GroupsManager, UserSettingsManager, UsersManager
from cmdb.models.settings_model import UserSettingKey
from cmdb.models.user_model import CmdbUser, CmdbUserKey
from cmdb.models.group_model.effective_rights import EffectiveRights
from cmdb.interface.route_utils import request_groups
from cmdb.interface.rest_api.routes.user_management_routes.cmdb_groups.groups_constants import (
    GROUP_ADMIN_MEMBER_MSG,
    GROUP_MEMBERS_NEED_ACTION_MSG,
    GROUP_MOVE_TARGET_IS_SOURCE_MSG,
    GROUP_RIGHTS_NOT_HELD_MSG,
    GROUP_UNKNOWN_RIGHTS_MSG,
)
from cmdb.models.group_model import (
    CmdbUserGroup,
    GroupDeleteMode,
    GroupKey,
    ADMIN_GROUP_ID,
    MASTER_RIGHT_NAME,
)
# -------------------------------------------------------------------------------------------------------------------- #

# A find projection returning every field, `_id` included
WHOLE_DOCUMENT: None = None


def resolve_move_target(
    groups_manager: GroupsManager,
    action: GroupDeleteMode | None,
    target_group_id: int | None,
    source_group_id: int,
) -> CmdbUserGroup | None:
    """
    Validates and resolves the destination group for a MOVE-mode group deletion

    Only meaningful for the ``MOVE`` action: the caller must supply a ``target_group_id``, that group must
    exist, and it must not be the group being deleted - moving the members there would leave them holding
    a group_id that is gone the moment the delete completes. For any other action (``DELETE`` or ``None``)
    there is no target to resolve

    Args:
        groups_manager (GroupsManager): Manager used to look up the target group
        action (GroupDeleteMode | None): The delete mode requested for the source group
        target_group_id (int | None): public_id of the group members should be moved to
        source_group_id (int): public_id of the group being deleted

    Raises:
        HTTPException: 400 if ``MOVE`` is requested without a ``target_group_id`` or with the source group
            as its target; 404 if the target group does not exist

    Returns:
        CmdbUserGroup | None: The resolved target group for ``MOVE``, otherwise None
    """
    if action != GroupDeleteMode.MOVE:
        return None

    if not target_group_id:
        abort(400, "The target group for moving users was not provided!")

    if target_group_id == source_group_id:
        abort(400, GROUP_MOVE_TARGET_IS_SOURCE_MSG.format(public_id=source_group_id))

    target_group: CmdbUserGroup | None = groups_manager.get_group(target_group_id)

    if not target_group:
        abort(404, f"The target UserGroup for moving users with ID:{target_group_id} was not found!")

    return target_group


def abort_if_members_would_be_stranded(
    users_manager: UsersManager,
    group_id: int,
    action: GroupDeleteMode | None,
) -> None:
    """
    Refuses a UserGroup delete that names no action while the group is some member's only group

    A member in other groups too just loses this one. A member whose only group it is would be left with none - still
    authenticated, refused every right - so for them the caller must choose MOVE or DELETE. A group without such
    members needs no action

    Args:
        users_manager (UsersManager): Manager used to ask whether the group has sole members
        group_id (int): public_id of the UserGroup being deleted
        action (GroupDeleteMode | None): The delete mode requested for the group's sole members

    Raises:
        HTTPException: 400 when no action is given and the group is at least one CmdbUser's only group
    """
    if action is not None:
        return

    if users_manager.has_sole_members(group_id):
        abort(400, GROUP_MEMBERS_NEED_ACTION_MSG.format(public_id=group_id))


def abort_if_admin_would_be_deleted(
    users_manager: UsersManager,
    group_id: int,
    action: GroupDeleteMode | None,
) -> None:
    """
    Refuses a DELETE-mode UserGroup delete whose sole members include the bootstrap admin user

    The admin must never be deleted. Only a sole member is deleted - an admin in other groups too only loses this
    one. Checked with one indexed lookup before anything is written, beside the other refusals;
    ``UsersManager.delete_users`` keeps the same guard as a backstop

    Args:
        users_manager (UsersManager): Manager used to look the admin up in the group
        group_id (int): public_id of the UserGroup being deleted
        action (GroupDeleteMode | None): The delete mode requested for the group's members

    Raises:
        HTTPException: 400 when the members would be deleted and the admin user is one of them
    """
    if action != GroupDeleteMode.DELETE:
        return

    admin_member: dict[str, Any] | None = users_manager.get_one_by({
        **UsersManager.sole_member_criteria(group_id),
        CmdbUserKey.PUBLIC_ID.value: CmdbUser.ADMIN_PUBLIC_ID,
    })

    if admin_member:
        abort(400, GROUP_ADMIN_MEMBER_MSG)


def _users_in_group(users_manager: UsersManager, user_ids: list[int], group_id: int) -> int:
    """
    How many of the given CmdbUsers belong to a UserGroup

    Args:
        users_manager (UsersManager): The users' manager
        user_ids (list[int]): public_ids of the users
        group_id (int): public_id of the UserGroup

    Returns:
        int: The number of them who are members of ``group_id``
    """
    return users_manager.count_documents({
        CmdbUserKey.PUBLIC_ID.value: {'$in': user_ids},
        CmdbUserKey.GROUP_IDS.value: group_id,
    })


def redistribute_members(
    ledger: WriteLedger,
    managers: tuple[UsersManager, UserSettingsManager],
    group_id: int,
    action: GroupDeleteMode | None,
    target_group_id: int | None,
) -> None:
    """
    Takes a UserGroup about to be deleted out of its members' groups, with the inverse recorded first

    The members and the sole ones among them (whose only group it is) are read once. Every member's group list is
    rewritten except for a sole member that is deleted: the others lose the group, a sole member is MOVEd into the
    target. Their lists are read first and the inverse writes each back as it was, checked by a count. For a DELETE
    the sole members' documents and settings rows are snapshotted and recorded as batch deletes
    (``WriteLedger.deleted_many``). The write itself then selects by the ids read, so it changes exactly the users the
    inverse covers

    Args:
        ledger (WriteLedger): The request's ledger
        managers (tuple[UsersManager, UserSettingsManager]): The users' and the user settings' managers
        group_id (int): public_id of the UserGroup being deleted
        action (GroupDeleteMode | None): MOVE or DELETE for the sole members; None when there are none
        target_group_id (int | None): Destination group for MOVE; ignored otherwise

    Raises:
        UsersManagerGetError: When the members could not be read
        UsersManagerUpdateError | UsersManagerDeleteError: When the redistribution failed
    """
    users_manager, settings_manager = managers
    member_ids, sole_ids = users_manager.read_group_members(group_id)

    if not member_ids:
        return

    regrouped_ids: list[int] = (
        sorted(set(member_ids) - set(sole_ids)) if action == GroupDeleteMode.DELETE else sorted(member_ids)
    )

    if regrouped_ids:
        group_ids_before: dict[int, list[int]] = users_manager.get_group_ids_of(regrouped_ids)
        ledger.compensated(
            users_manager.collection,
            f"users {regrouped_ids} taken out of UserGroup {group_id}",
            undo=lambda: users_manager.restore_group_ids(group_ids_before),
            verify=lambda: _users_in_group(users_manager, regrouped_ids, group_id) == len(regrouped_ids),
        )

    if action == GroupDeleteMode.DELETE and sole_ids:
        # Read whole, `_id` included (the database manager drops it unless a projection is given): the undo
        # re-inserts each document under its old identity
        id_filter: dict[str, Any] = {'$in': sole_ids}
        ledger.deleted_many(
            users_manager,
            users_manager.find(criteria={CmdbUserKey.PUBLIC_ID.value: id_filter}, projection=WHOLE_DOCUMENT),
            f"users {sorted(sole_ids)} of UserGroup {group_id} deleted",
        )
        ledger.deleted_many(
            settings_manager,
            settings_manager.find(criteria={UserSettingKey.USER_ID.value: id_filter}, projection=WHOLE_DOCUMENT),
            f"the settings of users {sorted(sole_ids)} deleted",
        )

    users_manager.handle_users_on_group_delete(group_id, action, target_group_id, (member_ids, sole_ids))


def ensure_admin_group_keeps_master_right(public_id: int, data: dict[str, Any]) -> None:
    """
    Refuses a CmdbUserGroup update that would strip the master right from the administrator group

    The administrator group (``ADMIN_GROUP_ID``) is seeded with the single right
    ``MASTER_RIGHT_NAME`` ('base.*'), which is what grants its members every other right. Since an
    update is always a full-object write, a payload whose ``rights`` list omits that right would
    remove it - and with it the ``base.user-management.group.edit`` right needed to hand it back,
    locking every administrator out of the system with no in-app way to recover

    The membership test is a plain name lookup in the payload list: the schema has already refused any
    entry that is not a string, so a payload carrying full right *dicts* never reaches this check

    Any other group, and any other change to the administrator group (its name, its label, adding
    further rights), is unaffected

    Args:
        public_id (int): public_id of the CmdbUserGroup being updated (taken from the URL)
        data (dict[str, Any]): The validated update payload for that group

    Raises:
        HTTPException: 400 if the administrator group's update payload does not keep the master right
    """
    if public_id != ADMIN_GROUP_ID:
        return

    submitted_rights: list[str] = data.get(GroupKey.RIGHTS) or []

    if MASTER_RIGHT_NAME not in submitted_rights:
        abort(
            400,
            f"The right '{MASTER_RIGHT_NAME}' cannot be removed from the administrator group, "
            "otherwise no user could administrate DataGerry anymore!"
        )


def unknown_right_names(submitted_rights: list[str], known_names: frozenset[str]) -> list[str]:
    """
    Lists the submitted right names the right tree does not know

    Args:
        submitted_rights (list[str]): The ``rights`` list of a validated group payload
        known_names (frozenset[str]): Every right name the right tree holds (``GroupsManager.right_names``)

    Returns:
        list[str]: Each unknown name once, in the order it was submitted; empty when every name is known
    """
    return list(dict.fromkeys(name for name in submitted_rights if name not in known_names))


def abort_if_unknown_rights(data: dict[str, Any], known_names: frozenset[str]) -> None:
    """
    Refuses a CmdbUserGroup write whose ``rights`` names a right that does not exist

    The same rule on create and on update: an unknown name would otherwise be stored by one route and
    silently dropped by the other. Wildcard rights (``base.framework.*``) are nodes of the tree and pass

    Args:
        data (dict[str, Any]): The validated group payload (every ``rights`` entry is a string)
        known_names (frozenset[str]): Every right name the right tree holds (``GroupsManager.right_names``)

    Raises:
        HTTPException: 400 naming every unknown right
    """
    unknown: list[str] = unknown_right_names(data.get(GroupKey.RIGHTS) or [], known_names)

    if unknown:
        abort(400, GROUP_UNKNOWN_RIGHTS_MSG.format(names=', '.join(f"'{name}'" for name in unknown)))


def unheld_rights(held: EffectiveRights, submitted: list[str] | None, already_granted: Iterable[Any] = ()
                  ) -> list[str]:
    """
    The rights a group write would newly grant that the caller does not hold - directly or through a wildcard

    Args:
        held (EffectiveRights): The caller's rights
        submitted (list[str] | None): The right names the write sends
        already_granted (Iterable[Any]): The rights the group holds already, as stored - not judged; an entry that
            is no name (a group stored before the rights rule) holds nothing

    Returns:
        list[str]: The names not held, in the order sent, each once
    """
    granted: set[str] = {name for name in already_granted if isinstance(name, str)}

    return [name for name in dict.fromkeys(submitted or []) if name not in granted and not held.grants(name)]


def abort_if_granting_unheld_rights(request_user: CmdbUser, submitted: list[str] | None,
                                    already_granted: Iterable[Any] = ()) -> None:
    """
    Refuses a group create or update granting a right the caller does not hold - nobody hands out more than they
    have; the rights the group holds already may stay

    Args:
        request_user (CmdbUser): The caller - its groups' rights are read once per request
        submitted (list[str] | None): The right names the write sends
        already_granted (Iterable[Any]): The rights the group holds already, as stored

    Raises:
        HTTPException: 400 naming the rights not held
    """
    unheld: list[str] = unheld_rights(request_groups(request_user), submitted, already_granted)

    if unheld:
        abort(400, GROUP_RIGHTS_NOT_HELD_MSG.format(names=unheld))
