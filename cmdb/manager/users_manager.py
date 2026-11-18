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
Implementation of the `UsersManager`, the service layer over the `management.users` collection

Every authenticated request passes through this manager: `route_utils.insert_request_user` resolves the
token's user here, and the route's right check (`route_utils.user_has_right`) then reads that user's
group, so a read that fails here fails the whole request. Beyond user CRUD it owns two cross-cutting jobs:

* **Member redistribution when a UserGroup is deleted** (`handle_users_on_group_delete`). The group
  route deletes the group itself; this manager decides what happens to the members first, and it
  must never leave a user pointing at a group that no longer exists. A member in other groups too only loses the
  group (`remove_group_from_users`); a member for whom it is the only group is moved or deleted
  (`move_users`, `delete_users`) - those are the ``sole`` members (`get_sole_member_ids`). It writes by the member
  ids it is handed (`get_group_member_ids`), so the route can record the exact inverse of the write before it runs
* **Cascading a user delete** into the collections that reference a user by public_id. Today that is
  `management.users.settings`; see `_delete_user_settings`

Errors: every public method converts what its calls raise - the call's `BaseManager*` error and the CmdbUser's
declared (de)serialisation errors (`USER_DOCUMENT_ERRORS`) - into the `UsersManagerError` family, because the
route layer maps those to specific 400 responses and falls through to a 500 for anything else. Anything else - a
programming error - propagates as itself and answers 500; the two transient database errors are never caught. An
unreadable stored user is a `UsersManagerGetError`, which the login refuses like an unknown user
"""
from logging import Logger, getLogger
from typing import Any, Iterable

from pymongo import UpdateOne

from cmdb.database import MongoDatabaseManager
from cmdb.utils import Builder
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.base_manager import BaseManager
from cmdb.manager.users_manager_constants import (
    MINIMAL_USER_PROJECTION,
    USER_ID_PROJECTION,
    WITHOUT_PASSWORD_PROJECTION,
)

from cmdb.models.group_model import GroupDeleteMode
from cmdb.models.settings_model import CmdbUserSetting, UserSettingKey
from cmdb.models.user_model import CmdbUser, CmdbUserKey
from cmdb.framework.results import IterationResult

from cmdb.errors.manager import (
    BaseManagerDeleteError,
    BaseManagerGetError,
    BaseManagerInsertError,
    BaseManagerIterationError,
    BaseManagerUpdateError,
)
from cmdb.errors.manager.users_manager import (
    UsersManagerActionError,
    UsersManagerGetError,
    UsersManagerInsertError,
    UsersManagerDeleteError,
    UsersManagerAdminMemberError,
    UsersManagerUpdateError,
    UsersManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# What a stored user document that no longer fits the model raises, on the way in and on the way out
USER_DOCUMENT_ERRORS: tuple[type[Exception], ...] = (CmdbUser.INIT_FROM_DATA_ERROR, CmdbUser.TO_JSON_ERROR)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 UsersManager - CLASS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class UsersManager(BaseManager):
    """
    The UsersManager handles the interaction between the CmdbUsers-API and the database

    Extends: BaseManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        """
        Set the database connection for the UsersManager

        Args:
            dbm (MongoDatabaseManager): Database interaction manager
            database (str | None): Name of the database to which the 'dbm' should connect. Only used in CLOUD_MODE
        """
        super().__init__(CmdbUser.COLLECTION, dbm, database)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def get_minimal_users_by_ids(self, public_ids: list[int]) -> list[dict[str, Any]]:
        """
        Retrieves a minimal projection of the CmdbUsers with the given public_ids

        Only the fields needed to display a user (e.g. as a log author) are returned - public_id,
        first_name, last_name, image, user_name - in a single query; no full user documents are loaded.
        Ids without a matching user are simply absent from the result.

        Args:
            public_ids (list[int]): public_ids of the CmdbUsers to retrieve

        Raises:
            UsersManagerGetError: When the CmdbUsers could not be retrieved

        Returns:
            list[dict[str, Any]]: Minimal user dicts; an empty list when no ids are provided
        """
        if not public_ids:
            return []

        try:
            return self.find(criteria={'public_id': {'$in': list(public_ids)}}, projection=MINIMAL_USER_PROJECTION)
        except BaseManagerGetError as err:
            LOGGER.error("[get_minimal_users_by_ids] BaseManagerGetError: %s", err)
            raise UsersManagerGetError(err) from err

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

    def insert_user(self, user: CmdbUser | dict[str, Any], id_from_counter: bool = False) -> int:
        """
        Insert a single CmdbUser into the database

        Args:
            user (CmdbUser | dict[str, Any]): Raw data of the CmdbUser
            id_from_counter (bool): The public_id was reserved from the counter (``get_new_*``) - not raised again.
                Defaults to False

        Raises:
            UsersManagerInsertError: When the CmdbUser could not be inserted in the database. The two
                TRANSIENT_DATABASE_ERRORS are raised unwrapped

        Returns:
            int: The public_id of the created CmdbUser
        """
        try:
            if isinstance(user, CmdbUser):
                user = CmdbUser.to_json(user)

            return self.insert(user, id_from_counter=id_from_counter)
        except (BaseManagerInsertError, *USER_DOCUMENT_ERRORS) as err:
            # A lock timeout or a lost connection is neither, so it passes unwrapped for the route layer to answer
            # as a server error, not as the insert's 400
            LOGGER.error("[insert_user] Exception: %s. Type: %s", err, type(err))
            raise UsersManagerInsertError(err) from err

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def get_user(self, public_id: int) -> CmdbUser | None:
        """
        Retrieve a single CmdbUser by its public_id

        Args:
            public_id (int): public_id of the CmdbUser

        Raises:
            UsersManagerGetError: If CmdbUser could not be retrieved

        Returns:
            CmdbUser | None: The requested CmdbUser if it exist else None
        """
        try:
            requested_user = self.get_one(public_id)

            if not requested_user:
                return None

            return CmdbUser.from_data(requested_user)
        except (BaseManagerGetError, *USER_DOCUMENT_ERRORS) as err:
            LOGGER.error("[get_user] Exception: %s. Type: %s", err, type(err))
            raise UsersManagerGetError(err) from err


    def get_user_by(self, query: dict[str, Any]) -> CmdbUser | None:
        """
        Get a single CmdbUser by a query

        Args:
            query (dict[str, Any]): Query filter of CmdbUser parameters

        Raises:
            UsersManagerGetError: When the CmdbUser could not be retrieved

        Returns:
            CmdbUser | None: CmdbUser matching the query if it exist else None
        """
        try:
            requested_user = self.get_one_by(query)

            if requested_user is None:
                return None

            return CmdbUser.from_data(requested_user)
        except (BaseManagerGetError, *USER_DOCUMENT_ERRORS) as err:
            LOGGER.error("[get_user_by] Exception: %s. Type: %s", err, type(err))
            raise UsersManagerGetError(err) from err


    def iterate(self, builder_params: BuilderParameters) -> IterationResult[CmdbUser]:
        """
        Iterate CmdbUsers

        Args:
            builder_params (BuilderParameters): Filter for iteration

        Raises:
            UsersManagerIterationError: When the iteration failed

        Returns:
            IterationResult: IterationResult with CmdbUsers matching the filter
        """
        try:
            aggregation_result, total = self.iterate_query(builder_params)

            iteration_result: IterationResult[CmdbUser] = IterationResult(aggregation_result, total, CmdbUser)

            return iteration_result
        except (BaseManagerIterationError, *USER_DOCUMENT_ERRORS) as err:
            LOGGER.error("[iterate] Exception: %s, Type: %s", err, type(err))
            raise UsersManagerIterationError(err) from err


    def get_user_lookup(self, user_ids: Iterable[int]) -> dict[int, CmdbUser]:
        """
        Retrieves a lookup dictionary of CmdbUsers filtered by the provided user_ids

        The users are read without their password digest (``WITHOUT_PASSWORD_PROJECTION``): a lookup is for
        showing and judging users, never for writing one back

        Args:
            user_ids (Iterable[int]): The public_ids of CmdbUsers which should be retrieved

        Raises:
            UsersManagerGetError: When the CmdbUsers could not be retrieved or deserialised

        Returns:
            dict[int, CmdbUser]: The lookup dictionary with the CmdbUsers
        """
        try:
            users: list[dict[str, Any]] = self.find(
                criteria={"public_id": {"$in": list(user_ids)}}, projection=WITHOUT_PASSWORD_PROJECTION,
            )

            # Keyed by the built user, so a document without a public_id fails as an unreadable user
            built_users: list[CmdbUser] = [CmdbUser.from_data(user) for user in users]
        except (BaseManagerGetError, *USER_DOCUMENT_ERRORS) as err:
            LOGGER.error("[get_user_lookup] Exception: %s. Type: %s", err, type(err))
            raise UsersManagerGetError(err) from err

        return {user.public_id: user for user in built_users}

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

    def update_user(self, public_id: int, user_data: CmdbUser | dict[str, Any]) -> None:
        """
        Update an existing CmdbUser

        Args:
            public_id (int): public_id of the CmdbUser
            user_data (CmdbUser | dict[str, Any]): Instance or dict of CmdbUser

        Raises:
            UsersManagerUpdateError: When the CmdbUser could not be updated
        """
        try:
            if isinstance(user_data, CmdbUser):
                user_data = CmdbUser.to_json(user_data)

            self.update(criteria={'public_id': public_id}, data=user_data)
        except (BaseManagerUpdateError, *USER_DOCUMENT_ERRORS) as err:
            LOGGER.error("[update_user] Exception: %s, Type: %s", err, type(err))
            raise UsersManagerUpdateError(err) from err

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_user(self, public_id: int) -> bool:
        """
        Delete an existing CmdbUser with the given public_id

        The user's rows in the collections that reference it by public_id are removed as well (see
        `_delete_user_settings`). There is no cross-collection transaction, so the cascade runs
        after the user document is gone: a failure in it leaves orphaned rows behind, never a
        deleted settings set for a user that still exists

        Args:
            public_id (int): PublicID of the user

        Raises:
            UsersManagerDeleteError: When trying to delete the admin CmdbUser with public_id=1 or deletion failed

        Returns:
            bool: True if deletion was successful
        """
        if public_id == CmdbUser.ADMIN_PUBLIC_ID:
            raise UsersManagerDeleteError("It is not possible to delete the admin user!")

        try:
            deleted: bool = self.delete({'public_id': public_id})

            self._delete_user_settings([public_id])

            return deleted
        except BaseManagerDeleteError as err:
            LOGGER.error("[delete_user] BaseManagerDeleteError: %s", err)
            raise UsersManagerDeleteError(err) from err

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    def _delete_user_settings(self, user_ids: list[int]) -> None:
        """
        Removes the CmdbUserSettings belonging to the given CmdbUsers

        The settings collection references its user by public_id only - there is no back-reference
        and nothing else prunes it, so without this cascade a deleted user's settings survive
        forever and would be inherited by any later user that reuses the public_id

        Args:
            user_ids (list[int]): public_ids of the CmdbUsers whose settings should be removed

        Raises:
            BaseManagerDeleteError: When the settings could not be removed
        """
        if not user_ids:
            return

        self.delete_many_from_other_collection(
            CmdbUserSetting.COLLECTION,
            {UserSettingKey.USER_ID.value: {'$in': list(user_ids)}},
        )


    def handle_users_on_group_delete(
        self,
        group_id: int,
        action: GroupDeleteMode | None,
        target_group_id: int | None,
        member_ids: tuple[list[int], list[int]] | None = None,
    ) -> None:
        """
        Redistribute the members of a UserGroup that is about to be deleted

        Every member loses the group. A member in other groups too keeps them and nothing else changes
        (``remove_group_from_users``). For a member whose only group it is - a ``sole`` member - ``action`` decides:
          * ``MOVE`` - the member is put into ``target_group_id`` (which must be provided)
          * ``DELETE`` - the member is deleted along with their settings, but the call is refused first if the
            bootstrap admin user is one of them (the admin must never be deleted)
        Without sole members the action is not needed; a group with no members is a no-op

        The members are the ``member_ids`` the caller read - (all members, the sole ones), the ones it recorded the
        undo for - and every write selects by those ids, never by the group predicate, so it changes exactly the
        users the undo knows about. Without ``member_ids`` they are read here

        ``action`` must be a member of ``GroupDeleteMode`` while there are sole members. Anything else raises rather
        than falling through silently: a silent no-op here would delete the group while those members keep it as
        their only group - authenticated, and refused every right

        Args:
            group_id (int): public_id of the UserGroup being deleted
            action (GroupDeleteMode | None): How to handle the sole members (MOVE or DELETE); None without any
            target_group_id (int | None): Destination group for MOVE; ignored for DELETE
            member_ids (tuple[list[int], list[int]] | None): public_ids of all the members and of the sole ones.
                Defaults to None (read)

        Raises:
            UsersManagerActionError: When there are sole members and 'action' is not a supported GroupDeleteMode
            UsersManagerAdminMemberError: When the admin user is a sole member on DELETE
            UsersManagerDeleteError: When a member delete failed
            UsersManagerUpdateError: When the move target is missing or a member update failed
            UsersManagerGetError: When the group's members could not be retrieved
        """
        ids, sole_ids = (
            self.read_group_members(group_id) if member_ids is None else (list(member_ids[0]), list(member_ids[1]))
        )

        if sole_ids and action not in (GroupDeleteMode.MOVE, GroupDeleteMode.DELETE):
            raise UsersManagerActionError(f"Unsupported GroupDeleteMode: {action!r}")

        try:
            self.remove_group_from_users(sorted(set(ids) - set(sole_ids)), group_id)

            if action == GroupDeleteMode.MOVE:
                self.move_users(sole_ids, group_id, target_group_id)
            elif action == GroupDeleteMode.DELETE:
                self.delete_users(sole_ids)
        # This manager's own errors (the admin refusal, the missing move target) are NOT caught here:
        # UsersManagerError does not extend BaseManagerError, so they pass these arms untouched and reach the
        # route with their identity intact
        except BaseManagerUpdateError as err:
            LOGGER.error("[handle_users_on_group_delete] BaseManagerUpdateError: %s", err)
            raise UsersManagerUpdateError(err) from err
        except BaseManagerDeleteError as err:
            LOGGER.error("[handle_users_on_group_delete] BaseManagerDeleteError: %s", err)
            raise UsersManagerDeleteError(err) from err


    def get_group_member_ids(self, group_id: int) -> list[int]:
        """
        The public_ids of every CmdbUser in a UserGroup - a projected read, no user document is loaded

        Args:
            group_id (int): public_id of the UserGroup

        Raises:
            UsersManagerGetError: When the members could not be read

        Returns:
            list[int]: The members' public_ids
        """
        try:
            return [
                user[CmdbUserKey.PUBLIC_ID.value]
                for user in self.find(criteria={CmdbUserKey.GROUP_IDS.value: group_id}, projection=USER_ID_PROJECTION)
            ]
        except BaseManagerGetError as err:
            LOGGER.error("[get_group_member_ids] BaseManagerGetError: %s", err)
            raise UsersManagerGetError(err) from err


    def read_group_members(self, group_id: int) -> tuple[list[int], list[int]]:
        """
        The members of a UserGroup and, among them, the sole ones - whose only group it is

        Two projected reads. The sole members are kept to the members of the first read: a user who joins the group
        between the two reads is in neither list, so a write by these ids leaves them as they are

        Args:
            group_id (int): public_id of the UserGroup

        Raises:
            UsersManagerGetError: When the members could not be read

        Returns:
            tuple[list[int], list[int]]: Every member's public_id, and the sole members' among them
        """
        member_ids: list[int] = self.get_group_member_ids(group_id)

        if not member_ids:
            return [], []

        members: set[int] = set(member_ids)

        return member_ids, [user_id for user_id in self.get_sole_member_ids(group_id) if user_id in members]


    @staticmethod
    def sole_member_criteria(group_id: int) -> dict[str, Any]:
        """
        The users filter selecting the CmdbUsers whose only group a UserGroup is

        A stored list is canonical (sorted, each group once), so "only this group" is the list ``[group_id]`` - an
        equality on the whole array

        Args:
            group_id (int): public_id of the UserGroup

        Returns:
            dict[str, Any]: The criteria
        """
        return {CmdbUserKey.GROUP_IDS.value: [int(group_id)]}


    def get_sole_member_ids(self, group_id: int) -> list[int]:
        """
        The public_ids of the CmdbUsers whose only group a UserGroup is - a projected read

        Args:
            group_id (int): public_id of the UserGroup

        Raises:
            UsersManagerGetError: When the members could not be read

        Returns:
            list[int]: The sole members' public_ids (``sole_member_criteria``)
        """
        try:
            return [
                user[CmdbUserKey.PUBLIC_ID.value]
                for user in self.find(criteria=self.sole_member_criteria(group_id), projection=USER_ID_PROJECTION)
            ]
        except BaseManagerGetError as err:
            LOGGER.error("[get_sole_member_ids] BaseManagerGetError: %s", err)
            raise UsersManagerGetError(err) from err


    def has_sole_members(self, group_id: int) -> bool:
        """
        Reports whether any CmdbUser has a UserGroup as their only group - the members a group delete must decide on

        Counts with a limit of one

        Args:
            group_id (int): public_id of the UserGroup

        Raises:
            UsersManagerGetError: When the members could not be counted

        Returns:
            bool: True when at least one CmdbUser is in this group and no other
        """
        try:
            return self.count_documents(self.sole_member_criteria(group_id), limit=1) > 0
        except BaseManagerGetError as err:
            LOGGER.error("[has_sole_members] BaseManagerGetError: %s", err)
            raise UsersManagerGetError(err) from err


    def has_group_members(self, group_id: int) -> bool:
        """
        Reports whether any CmdbUser belongs to a UserGroup

        Counts with a limit of one, so the answer costs a single index lookup whatever the group's size

        Args:
            group_id (int): public_id of the UserGroup

        Raises:
            UsersManagerGetError: When the members could not be counted

        Returns:
            bool: True when at least one CmdbUser is a member
        """
        try:
            return self.count_documents({CmdbUserKey.GROUP_IDS.value: group_id}, limit=1) > 0
        except BaseManagerGetError as err:
            LOGGER.error("[has_group_members] BaseManagerGetError: %s", err)
            raise UsersManagerGetError(err) from err


    def has_other_active_member(self, group_id: int, public_id: int) -> bool:
        """
        Reports whether any ACTIVE CmdbUser other than the given one belongs to a UserGroup

        What the last-administrator guard asks before a member of the admin group is demoted, deactivated or
        deleted. Counts with a limit of one

        Args:
            group_id (int): public_id of the UserGroup
            public_id (int): public_id of the CmdbUser to leave out

        Raises:
            UsersManagerGetError: When the members could not be counted

        Returns:
            bool: True when another active member remains
        """
        criteria: dict[str, Any] = {
            CmdbUserKey.GROUP_IDS.value: group_id,
            CmdbUserKey.ACTIVE.value: True,
            CmdbUserKey.PUBLIC_ID.value: {'$ne': public_id},
        }

        try:
            return self.count_documents(criteria, limit=1) > 0
        except BaseManagerGetError as err:
            LOGGER.error("[has_other_active_member] BaseManagerGetError: %s", err)
            raise UsersManagerGetError(err) from err


    def move_users(self, user_ids: list[int], source_group_id: int, target_group_id: int | None) -> None:
        """
        Moves the given CmdbUsers from one group to another, keeping their other groups

        One pipeline `update_many` by the ids: in each user's ``group_ids`` the source group is replaced by the
        target group - added once, the list kept sorted

        Args:
            user_ids (list[int]): public_ids of the users to move
            source_group_id (int): public_id of the UserGroup they leave
            target_group_id (int | None): public_id of the destination UserGroup

        Raises:
            UsersManagerUpdateError: When no target group was provided
            BaseManagerUpdateError: When the update failed
        """
        if not target_group_id:
            raise UsersManagerUpdateError("Target group required when moving Users!")

        if not user_ids:
            return

        moved: dict[str, Any] = {
            '$setUnion': [
                {'$setDifference': [f'${CmdbUserKey.GROUP_IDS.value}', [int(source_group_id)]]},
                [int(target_group_id)],
            ],
        }

        self.update_many_raw(
            {CmdbUserKey.PUBLIC_ID.value: {'$in': list(user_ids)}},
            [Builder.set_({CmdbUserKey.GROUP_IDS.value: {'$sortArray': {'input': moved, 'sortBy': 1}}})],
        )


    def remove_group_from_users(self, user_ids: list[int], group_id: int) -> None:
        """
        Takes a UserGroup out of the given CmdbUsers' groups, keeping their others

        One ``update_many`` by the ids, which also requires a second group in the list: a user who in the meantime has
        only this group left keeps it rather than being left with none

        Args:
            user_ids (list[int]): public_ids of the users
            group_id (int): public_id of the UserGroup they leave

        Raises:
            BaseManagerUpdateError: When the update failed
        """
        if not user_ids:
            return

        self.update_many_raw(
            {
                CmdbUserKey.PUBLIC_ID.value: {'$in': list(user_ids)},
                f'{CmdbUserKey.GROUP_IDS.value}.1': {'$exists': True},
            },
            {'$pull': {CmdbUserKey.GROUP_IDS.value: int(group_id)}},
        )


    def get_group_ids_of(self, user_ids: list[int]) -> dict[int, list[int]]:
        """
        The stored ``group_ids`` of the given CmdbUsers - a projected read

        Args:
            user_ids (list[int]): public_ids of the users

        Raises:
            UsersManagerGetError: When the users could not be read

        Returns:
            dict[int, list[int]]: public_id -> its group_ids, for every user found
        """
        projection: dict[str, int] = {CmdbUserKey.PUBLIC_ID.value: 1, CmdbUserKey.GROUP_IDS.value: 1}

        try:
            return {
                user[CmdbUserKey.PUBLIC_ID.value]: list(user.get(CmdbUserKey.GROUP_IDS.value) or [])
                for user in self.find(criteria={CmdbUserKey.PUBLIC_ID.value: {'$in': list(user_ids)}},
                                      projection=projection)
            }
        except BaseManagerGetError as err:
            LOGGER.error("[get_group_ids_of] BaseManagerGetError: %s", err)
            raise UsersManagerGetError(err) from err


    def restore_group_ids(self, group_ids_by_user: dict[int, list[int]]) -> None:
        """
        Writes back the given ``group_ids`` of each CmdbUser - the inverse of a group move

        Args:
            group_ids_by_user (dict[int, list[int]]): public_id -> the group_ids to store

        Raises:
            BaseManagerUpdateError: When the bulk write failed
        """
        if not group_ids_by_user:
            return

        self.bulk_write([
            UpdateOne({CmdbUserKey.PUBLIC_ID.value: user_id}, {'$set': {CmdbUserKey.GROUP_IDS.value: group_ids}})
            for user_id, group_ids in group_ids_by_user.items()
        ])


    def delete_users(self, user_ids: list[int]) -> None:
        """
        Deletes the given CmdbUsers and their settings, refusing if the bootstrap admin is one of them

        Deleted by the ids, not by re-running the group query: a user added to the group in between would
        otherwise be deleted without being among the ids, and so keep their settings

        Args:
            user_ids (list[int]): public_ids of the users to delete

        Raises:
            UsersManagerAdminMemberError: When the admin user is among them
            BaseManagerDeleteError: When the users or their settings could not be deleted
        """
        if CmdbUser.ADMIN_PUBLIC_ID in user_ids:
            raise UsersManagerAdminMemberError("This Group can not be deleted because the admin user is part of it")

        if not user_ids:
            return

        self.delete_many({CmdbUserKey.PUBLIC_ID.value: {'$in': list(user_ids)}})

        self._delete_user_settings(list(user_ids))
