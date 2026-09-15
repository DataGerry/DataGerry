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

Every authenticated request passes through this manager: `route_utils.user_has_right` resolves the
token's user here before it can resolve their group and rights, so a read that fails here fails the
whole request. Beyond user CRUD it owns two cross-cutting jobs:

* **Member redistribution when a UserGroup is deleted** (`handle_users_on_group_delete`). The group
  route deletes the group itself; this manager decides what happens to the members first, and it
  must never leave a user pointing at a group that no longer exists - such a user still
  authenticates but is refused every right, because `user_has_right` resolves their group to None
* **Cascading a user delete** into the collections that reference a user by public_id. Today that is
  `management.users.settings`; see `_delete_user_settings`

Errors: every public method converts failures into the `UsersManagerError` family, because the route
layer maps those to specific 400 responses and falls through to a 500 for anything else. A
`BaseManager*` error reaching a route unconverted is therefore a bug, not a style question
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.database import MongoDatabaseManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.base_manager import BaseManager
from cmdb.manager.users_manager_constants import MINIMAL_USER_PROJECTION, USER_ID_PROJECTION

from cmdb.models.group_model import GroupDeleteMode
from cmdb.models.settings_model import CmdbUserSetting, UserSettingKey
from cmdb.models.user_model import CmdbUser
from cmdb.framework.results import IterationResult

from cmdb.errors.manager import (
    BaseManagerDeleteError,
    BaseManagerGetError,
    BaseManagerUpdateError,
)
from cmdb.errors.manager.users_manager import (
    UsersManagerActionError,
    UsersManagerInitError,
    UsersManagerGetError,
    UsersManagerInsertError,
    UsersManagerDeleteError,
    UsersManagerUpdateError,
    UsersManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

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

        Raises:
            UsersManagerInitError: When the underlying BaseManager could not be initialised
        """
        try:
            super().__init__(CmdbUser.COLLECTION, dbm, database)
        except Exception as err:
            raise UsersManagerInitError(str(err)) from err

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
        except Exception as err:
            LOGGER.error("[get_minimal_users_by_ids] Exception: %s. Type: %s", err, type(err))
            raise UsersManagerGetError(str(err)) from err

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

    def insert_user(self, user: CmdbUser | dict) -> int:
        """
        Insert a single CmdbUser into the database

        Args:
            user (CmdbUser | dict): Raw data of the CmdbUser

        Raises:
            UsersManagerInsertError: When the CmdbUser could not be inserted in the database

        Returns:
            int: The public_id of the created CmdbUser
        """
        try:
            if isinstance(user, CmdbUser):
                user = CmdbUser.to_json(user)

            return self.insert(user)
        except Exception as err:
            LOGGER.error("[insert_user] Exception: %s. Type: %s", err, type(err))
            raise UsersManagerInsertError(str(err)) from err

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
        except Exception as err:
            LOGGER.error("[get_user] Exception: %s. Type: %s", err, type(err))
            raise UsersManagerGetError(str(err)) from err


    def get_user_by(self, query: dict) -> CmdbUser | None:
        """
        Get a single CmdbUser by a query

        Args:
            query (dict): Query filter of CmdbUser parameters

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
        except Exception as err:
            LOGGER.error("[get_user_by] Exception: %s. Type: %s", err, type(err))
            raise UsersManagerGetError(str(err)) from err


    def get_many_users(self, query: dict[str, Any] | None = None) -> list[CmdbUser]:
        """
        Get multiple CmdbUsers by a query. Passing no query means all users

        Args:
            query (dict[str, Any] | None): A database query for filtering

        Raises:
            UsersManagerGetError: Raised when CmdbUsers cant be retrieved or not transformed into CmdbUser

        Returns:
            list[CmdbUser]: A list of all users which matches the query
        """
        query = query or {}

        try:
            results = self.get(filter=query)

            return [CmdbUser.from_data(user) for user in results]
        except Exception as err:
            LOGGER.error("[get_many_users] Exception: %s, Type: %s", err, type(err))
            raise UsersManagerGetError(str(err)) from err


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
        except Exception as err:
            LOGGER.error("[iterate] Exception: %s, Type: %s", err, type(err))
            raise UsersManagerIterationError(str(err)) from err


    def get_user_lookup(self, user_ids: list[int]) -> dict[int, CmdbUser]:
        """
        Retrieves a lookup dictionary of CmdbUsers filtered by the provided user_ids

        Args:
            user_ids (list[int]): The public_ids of CmdbUsers which should be retrieved

        Raises:
            UsersManagerGetError: When the CmdbUsers could not be retrieved or deserialised

        Returns:
            dict[int, CmdbUser]: The lookup dictionary with the CmdbUsers
        """
        try:
            users: list[dict[str, Any]] = self.find(criteria={"public_id": {"$in": list(user_ids)}})

            return {user['public_id']: CmdbUser.from_data(user) for user in users}
        except Exception as err:
            LOGGER.error("[get_user_lookup] Exception: %s. Type: %s", err, type(err))
            raise UsersManagerGetError(str(err)) from err

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

    def update_user(self, public_id: int, user_data: CmdbUser | dict) -> None:
        """
        Update an existing CmdbUser

        Args:
            public_id (int): public_id of the CmdbUser
            user_data (CmdbUser | dict): Instance or dict of CmdbUser

        Raises:
            UsersManagerUpdateError: When the CmdbUser could not be updated
        """
        try:
            if isinstance(user_data, CmdbUser):
                user_data = CmdbUser.to_json(user_data)

            self.update(criteria={'public_id': public_id}, data=user_data)
        except Exception as err:
            LOGGER.error("[update_user] Exception: %s, Type: %s", err, type(err))
            raise UsersManagerUpdateError(str(err)) from err

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
        try:
            if public_id == CmdbUser.ADMIN_PUBLIC_ID:
                raise UsersManagerDeleteError("It is not possible to delete the admin user!")

            deleted: bool = self.delete({'public_id': public_id})

            self._delete_user_settings([public_id])

            return deleted
        except Exception as err:
            LOGGER.error("[delete_user] Exception: %s, Type: %s", err, type(err))
            raise UsersManagerDeleteError(str(err)) from err

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
        action: GroupDeleteMode,
        target_group_id: int | None
    ) -> None:
        """
        Redistribute the members of a UserGroup that is about to be deleted

        Depending on ``action``:
          * ``MOVE`` - every user in ``group_id`` is reassigned to ``target_group_id`` in a single
            ``update_many`` (``target_group_id`` must be provided)
          * ``DELETE`` - every user in ``group_id`` is deleted along with their settings, but the
            call is refused first if the bootstrap admin user is a member (the admin must never be
            deleted)
        A group with no members is a no-op in both cases

        ``action`` must be a member of ``GroupDeleteMode``. Anything else raises rather than falling
        through silently: a silent no-op here would delete the group while its members keep pointing
        at it, and such a user is refused every right by `route_utils.user_has_right` (it resolves
        their group to None) while still being able to authenticate

        Args:
            group_id (int): public_id of the UserGroup being deleted
            action (GroupDeleteMode): How to handle the group's members (MOVE or DELETE)
            target_group_id (int | None): Destination group for MOVE; ignored for DELETE

        Raises:
            UsersManagerActionError: When 'action' is not a supported GroupDeleteMode
            UsersManagerDeleteError: When the admin user is a member on DELETE, or a member delete failed
            UsersManagerUpdateError: When the move target is missing or a member move failed
            UsersManagerGetError: When the group's members could not be retrieved
        """
        try:
            if action == GroupDeleteMode.MOVE:
                self._move_group_members(group_id, target_group_id)
            elif action == GroupDeleteMode.DELETE:
                self._delete_group_members(group_id)
            else:
                raise UsersManagerActionError(f"Unsupported GroupDeleteMode: {action!r}")
        # This manager's own errors (the admin refusal, the missing move target, the unsupported
        # action) are NOT caught here: UsersManagerError does not extend BaseManagerError, so they
        # pass these arms untouched and reach the route with their identity intact
        except BaseManagerUpdateError as err:
            LOGGER.error("[handle_users_on_group_delete] BaseManagerUpdateError: %s", err)
            raise UsersManagerUpdateError(str(err)) from err
        except BaseManagerDeleteError as err:
            LOGGER.error("[handle_users_on_group_delete] BaseManagerDeleteError: %s", err)
            raise UsersManagerDeleteError(str(err)) from err
        except BaseManagerGetError as err:
            LOGGER.error("[handle_users_on_group_delete] BaseManagerGetError: %s", err)
            raise UsersManagerGetError(str(err)) from err


    def _move_group_members(self, group_id: int, target_group_id: int | None) -> None:
        """
        Reassigns every member of a UserGroup to another group

        One `update_many` against the group_id predicate: every member gets the same new group, so
        there is nothing to read first and nothing to write per user

        Args:
            group_id (int): public_id of the UserGroup whose members are moved
            target_group_id (int | None): public_id of the destination UserGroup

        Raises:
            UsersManagerUpdateError: When no target group was provided
            BaseManagerUpdateError: When the update failed
        """
        if not target_group_id:
            raise UsersManagerUpdateError("Target group_id required when moving Users!")

        self.update_many({'group_id': group_id}, {'group_id': int(target_group_id)})


    def _delete_group_members(self, group_id: int) -> None:
        """
        Deletes every member of a UserGroup, refusing if the bootstrap admin is one of them

        Reads only the members' public_ids (a projected read), so the settings cascade knows whose
        rows to remove without loading the user documents themselves

        Args:
            group_id (int): public_id of the UserGroup whose members are deleted

        Raises:
            UsersManagerDeleteError: When the admin user is a member of the group
            BaseManagerGetError: When the members could not be read
            BaseManagerDeleteError: When the members could not be deleted
        """
        # Check if the admin user is part of this UserGroup
        admin_user: dict[str, Any] | None = self.get_one_by({
            "group_id": group_id,
            "public_id": CmdbUser.ADMIN_PUBLIC_ID
        })

        if admin_user:
            raise UsersManagerDeleteError("This Group can not be deleted because the admin user is part of it")

        member_ids: list[int] = [
            user['public_id']
            for user in self.find(criteria={'group_id': group_id}, projection=USER_ID_PROJECTION)
        ]

        if not member_ids:
            return

        self.delete_many({"group_id": group_id})

        self._delete_user_settings(member_ids)
