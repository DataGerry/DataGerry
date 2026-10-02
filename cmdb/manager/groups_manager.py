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
This module contains the implementation of the GroupsManager
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.database import MongoDatabaseManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.generic_manager import GenericManager

from cmdb.models.right_model.all_rights import flat_rights_tree, ALL_RIGHTS
from cmdb.models.right_model.base_right import BaseRight
from cmdb.models.group_model import CmdbUserGroup, PROTECTED_GROUP_IDS
from cmdb.framework.results import IterationResult

from cmdb.errors.database import TRANSIENT_DATABASE_ERRORS
from cmdb.errors.manager.groups_manager import (
    GROUPS_MANAGER_ERRORS,
    GroupsManagerInitError,
    GroupsManagerInsertError,
    GroupsManagerGetError,
    GroupsManagerIterationError,
    GroupsManagerDeleteError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# Document field carrying the CmdbUserGroup identity (pinned on update so a payload can never rewrite it)
PUBLIC_ID_FIELD: str = 'public_id'

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 GroupsManager - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class GroupsManager(GenericManager):
    """
    Manages CmdbUserGroup documents on top of GenericManager

    Keeps the named public API (``insert_group`` / ``get_group`` / ``iterate`` / ``update_group`` /
    ``delete_group``) used by the existing route + bootstrap call sites. Insert overrides
    ``GenericManager.insert_item`` because ``CmdbUserGroup.to_json`` needs ``insert_mode=True`` to
    serialize rights as name strings; the reads (``get_group``, ``iterate``) and the write hydration build
    every model through ``_build_group``, which feeds the cached ``self.rights`` to
    ``CmdbUserGroup.from_data``; delete keeps the admin / user-group guard

    Extends: GenericManager
    """
    def __init__(self, dbm: MongoDatabaseManager | None = None, database: str | None = None) -> None:
        """
        Set the database connection for the GroupsManager and cache the flat right tree and its names

        ``right_names`` is the set of every name the right tree knows - what a group's ``rights`` may carry

        Args:
            dbm (MongoDatabaseManager): Database interaction manager
            database (str): Name of the database to which the ``dbm`` should connect. Used whenever it is
                given, in every mode - pass one only in cloud mode (``ManagerProvider`` does)

        Raises:
            GroupsManagerInitError: If the manager (or the right-tree cache) could not be initialised
        """
        super().__init__(dbm, CmdbUserGroup, GROUPS_MANAGER_ERRORS, database)

        try:
            self.rights: list[BaseRight] = flat_rights_tree(ALL_RIGHTS)
            self.right_names: frozenset[str] = frozenset(right.name for right in self.rights)
        except Exception as err:
            raise GroupsManagerInitError(err) from err

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

    def insert_group(self, group: CmdbUserGroup | dict[str, Any]) -> int:
        """
        Insert a single CmdbUserGroup into the database

        Overrides the generic insert path because ``CmdbUserGroup.to_json`` requires
        ``insert_mode=True`` on insert, which serializes rights as a list of name strings rather
        than as a list of full BaseRight dicts

        Args:
            group (CmdbUserGroup | dict[str, Any]): Raw dict or model instance of the CmdbUserGroup to create

        Raises:
            GroupsManagerInsertError: When the CmdbUserGroup could not be inserted. The two TRANSIENT_DATABASE_ERRORS
                are raised unwrapped

        Returns:
            int: The public_id of the inserted CmdbUserGroup
        """
        try:
            if isinstance(group, CmdbUserGroup):
                group = CmdbUserGroup.to_json(group, True)

            return self.insert(group)
        except TRANSIENT_DATABASE_ERRORS:
            # A lock timeout or a lost connection is no fault of the CmdbUserGroup: left unwrapped for the route
            # layer to answer as a server error, not as the insert's 400
            raise
        except Exception as err:
            LOGGER.error("[insert_group] Exception: %s. Type: %s", err, type(err))
            raise GroupsManagerInsertError(err) from err

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def _build_group(self, document: dict[str, Any]) -> CmdbUserGroup:
        """
        Builds a CmdbUserGroup from a stored document, its right names resolved through the cached right tree

        The one place a stored group becomes a model, so the single read, the list and the write hydration
        cannot resolve the rights differently

        Args:
            document (dict[str, Any]): A stored CmdbUserGroup document, or a validated payload

        Raises:
            CmdbUserGroupInitFromDataError: When the document cannot be read as a CmdbUserGroup

        Returns:
            CmdbUserGroup: The group, holding the rights of the tree its document names
        """
        return CmdbUserGroup.from_data(document, self.rights)


    def get_group(self, public_id: int) -> CmdbUserGroup | None:
        """
        Get a single CmdbUserGroup by its public_id

        Reuses the generic ``get_item`` for the raw fetch (and its error wrapping), then builds the model
        with ``_build_group``, which resolves the right names through the cached right tree

        Args:
            public_id (int): public_id of the CmdbUserGroup

        Raises:
            GroupsManagerGetError: When the requested CmdbUserGroup could not be retrieved

        Returns:
            CmdbUserGroup | None: The requested CmdbUserGroup, or None if no group has that id
        """
        requested_group = self.get_item(public_id, as_dict=True)

        if not requested_group:
            return None

        try:
            return self._build_group(requested_group)
        except Exception as err:
            LOGGER.error("[get_group] Exception: %s. Type: %s", err, type(err))
            raise GroupsManagerGetError(err) from err


    def iterate(self, builder_params: BuilderParameters) -> IterationResult[CmdbUserGroup]:
        """
        Retrieve multiple CmdbUserGroups, each with its rights resolved like the single read

        Runs the generic query (``iterate_query``) and builds every row with ``_build_group``. The generic
        ``iterate_items`` cannot be used: it builds each model with the document alone, and a group read
        without the right tree holds no rights

        Args:
            builder_params (BuilderParameters): Filter, sort and pagination parameters

        Raises:
            GroupsManagerIterationError: When the query failed or a row could not be read as a CmdbUserGroup

        Returns:
            IterationResult[CmdbUserGroup]: The CmdbUserGroups matching the filter, with the total count
        """
        try:
            documents, total = self.iterate_query(builder_params)

            return IterationResult([self._build_group(document) for document in documents], total)
        except Exception as err:
            LOGGER.error("[iterate] Exception: %s. Type: %s", err, type(err))
            raise GroupsManagerIterationError(err) from err

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

    def hydrate_group(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        Build the persisted (insert-mode) serialization of a CmdbUserGroup from raw payload data

        Resolves the submitted right names through the manager's cached right tree
        (``self.rights``) instead of recomputing ``flat_rights_tree(ALL_RIGHTS)`` per call, then
        serializes with ``insert_mode=True`` so rights are stored as name strings - the form
        ``canonical_right_names`` produces for a create

        Args:
            data (dict[str, Any]): Raw CmdbUserGroup payload (e.g. a validated request body)

        Returns:
            dict[str, Any]: The insert-mode json of the hydrated CmdbUserGroup
        """
        group: CmdbUserGroup = self._build_group(data)

        return CmdbUserGroup.to_json(group, True)


    def canonical_right_names(self, right_names: list[str]) -> list[str]:
        """
        The stored form of a ``rights`` list: each known name once, in the order of the right tree

        The same list ``hydrate_group`` stores on an update, so both write routes store one form. A create
        needs it without building the model, which cannot exist before its public_id is drawn

        Args:
            right_names (list[str]): The submitted right names

        Returns:
            list[str]: The known names among them, each once, in tree order
        """
        submitted: set[str] = set(right_names)

        return [right.name for right in self.rights if right.name in submitted]


    def update_group(self, public_id: int, group: CmdbUserGroup | dict[str, Any]) -> None:
        """
        Update an existing CmdbUserGroup via the generic update path

        A model instance is serialized with ``insert_mode=True`` (rights stored as name strings,
        matching how groups are persisted on insert). The document identity is pinned to
        ``public_id`` so a payload ``public_id`` can never rewrite the stored id. Updating an id
        that does not exist is a no-op (the underlying update does not upsert)

        Args:
            public_id (int): public_id of the CmdbUserGroup which should be updated
            group (CmdbUserGroup | dict[str, Any]): New data for the CmdbUserGroup

        Raises:
            GroupsManagerUpdateError: When the update operation failed
        """
        if isinstance(group, CmdbUserGroup):
            group = CmdbUserGroup.to_json(group, True)

        # Pin the identity: a payload public_id can never rewrite the document's id
        group[PUBLIC_ID_FIELD] = public_id

        self.update_item(public_id, group)

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def is_protected_group(self, public_id: int) -> bool:
        """
        Check whether a CmdbUserGroup is a protected bootstrap group that must not be deleted

        The bootstrap admin and user groups (public_ids in ``PROTECTED_GROUP_IDS``) are protected.
        Call sites can use this to refuse a deletion *before* performing any side effects (e.g.
        redistributing the group's users), so a rejected delete leaves no partial mutation behind

        Args:
            public_id (int): public_id of the CmdbUserGroup to check

        Returns:
            bool: True if the group is protected and may not be deleted
        """
        return public_id in PROTECTED_GROUP_IDS


    def delete_group(self, public_id: int) -> bool:
        """
        Delete an existing CmdbUserGroup by its public_id

        Refuses to delete the bootstrap admin and user groups (see ``is_protected_group``); for any
        other id the deletion is delegated to the generic delete path

        Args:
            public_id (int): public_id of the CmdbUserGroup which should be deleted

        Raises:
            GroupsManagerDeleteError: When the target id is protected, or the delete operation failed

        Returns:
            bool: True if a document was actually removed, False otherwise
        """
        if self.is_protected_group(public_id):
            raise GroupsManagerDeleteError(f'Deletion of Group with ID: {public_id} is not allowed!')

        return self.delete_item(public_id)
