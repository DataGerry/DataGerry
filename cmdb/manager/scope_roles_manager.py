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
This module contains the implementation of the ScopeRolesManager
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_constants import MONGO_ID_FIELD
from cmdb.manager.generic_manager import GenericManager

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.access_model import (
    ALL_TYPES,
    ACCESS_RIGHTS_MIGRATION_REPORT_ID,
    MIGRATION_REPORT_COLLECTION,
    TYPE_ACL_MIGRATION_REPORT_ID,
    CmdbScopeRole,
    ScopeRoleKey,
)

from cmdb.errors.manager import BaseManagerGetError, BaseManagerUpdateError
from cmdb.errors.manager.scope_roles_manager import (
    SCOPE_ROLES_MANAGER_ERRORS,
    ScopeRolesManagerGetError,
    ScopeRolesManagerUpdateError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The order every read of several roles answers in
BY_PUBLIC_ID: list[tuple[str, int]] = [(CmdbDAO.PUBLIC_ID_KEY, CmdbDAO.DAO_ASCENDING)]

# -------------------------------------------------------------------------------------------------------------------- #
#                                              ScopeRolesManager - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class ScopeRolesManager(GenericManager):
    """
    The ScopeRolesManager manages the scope roles of the permission data model in the database

    Extends: GenericManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        """
        Set the database connection for the ScopeRolesManager

        Args:
            dbm (MongoDatabaseManager): Database interaction manager
            database (str | None): Name of the database the dbm should connect to. Only used in cloud mode
        """
        super().__init__(dbm, CmdbScopeRole, SCOPE_ROLES_MANAGER_ERRORS, database)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def _find_roles(self, criteria: dict[str, Any], caller: str) -> list[dict[str, Any]]:
        """
        Reads the stored roles matching the criteria, whole and without ``_id``, ascending by public_id

        Args:
            criteria (dict[str, Any]): Which roles
            caller (str): The public method reading, for the log line

        Raises:
            ScopeRolesManagerGetError: When the read fails

        Returns:
            list[dict[str, Any]]: The roles as stored
        """
        try:
            return self.find(criteria=criteria, projection={MONGO_ID_FIELD: 0}, sort=BY_PUBLIC_ID)
        except BaseManagerGetError as err:
            LOGGER.error("[%s] Exception: %s. Type: %s", caller, err, type(err))
            raise ScopeRolesManagerGetError(err) from err


    def all_roles(self) -> list[dict[str, Any]]:
        """
        Reads every stored scope role in one read - the access rules are an administrator's configuration, a handful of
        documents, not a growing collection

        Raises:
            ScopeRolesManagerGetError: When the read fails

        Returns:
            list[dict[str, Any]]: The roles as stored, ascending by public_id
        """
        return self._find_roles({}, 'all_roles')


    def roles_by_ids(self, public_ids: list[int]) -> list[dict[str, Any]]:
        """
        Reads the given scope roles in one read

        Args:
            public_ids (list[int]): The roles' public_ids; none reads nothing

        Raises:
            ScopeRolesManagerGetError: When the read fails

        Returns:
            list[dict[str, Any]]: The roles that exist, as stored, ascending by public_id
        """
        if not public_ids:
            return []

        return self._find_roles({CmdbDAO.PUBLIC_ID_KEY: {'$in': list(public_ids)}}, 'roles_by_ids')


    def roles_granting_class(self, class_name: str) -> list[dict[str, Any]]:
        """
        Reads the roles granting a field class - what keeps the class from being deleted

        Args:
            class_name (str): The field class's name

        Raises:
            ScopeRolesManagerGetError: When the read fails

        Returns:
            list[dict[str, Any]]: The roles as stored, ascending by public_id
        """
        return self._find_roles({ScopeRoleKey.FIELD_CLASSES.value: class_name}, 'roles_granting_class')


    def roles_naming_type(self, type_id: int) -> list[dict[str, Any]]:
        """
        Reads the roles listing a Type by its id - the ones a Type delete changes. A role covering every Type
        (``ALL_TYPES``) names no Type and is not among them

        Args:
            type_id (int): The CmdbType's public_id

        Raises:
            ScopeRolesManagerGetError: When the read fails

        Returns:
            list[dict[str, Any]]: The roles as stored, ascending by public_id - what a ledger records before the pull
        """
        return self._find_roles({ScopeRoleKey.TYPES.value: type_id}, 'roles_naming_type')


    def roles_covering_type(self, type_id: int) -> list[dict[str, Any]]:
        """
        Reads the roles that cover a Type: the ones listing it and the ones covering every Type (``ALL_TYPES``)

        Args:
            type_id (int): The CmdbType's public_id

        Raises:
            ScopeRolesManagerGetError: When the read fails

        Returns:
            list[dict[str, Any]]: The roles as stored, ascending by public_id
        """
        return self._find_roles({'$or': [{ScopeRoleKey.TYPES.value: type_id}, {ScopeRoleKey.TYPES.value: ALL_TYPES}]},
                                'roles_covering_type')


    def migration_reports(self) -> dict[str, dict[str, Any]]:
        """
        Reads the access migration reports: the type ACL migration's (how the stored type ACLs became these roles and
        their assignments) and the access rights migration's (which groups were given which access rule right)

        Raises:
            ScopeRolesManagerGetError: When a read fails

        Returns:
            dict[str, dict[str, Any]]: Each stored report without its ``_id``, keyed by it
                (``TYPE_ACL_MIGRATION_REPORT_ID`` / ``ACCESS_RIGHTS_MIGRATION_REPORT_ID``); a report never written is
                absent
        """
        reports: dict[str, dict[str, Any]] = {}

        for report_id in (TYPE_ACL_MIGRATION_REPORT_ID, ACCESS_RIGHTS_MIGRATION_REPORT_ID):
            try:
                found: list[dict[str, Any]] = self.get_many_from_other_collection(
                    MIGRATION_REPORT_COLLECTION, limit=1, projection={MONGO_ID_FIELD: 0},
                    criteria={MONGO_ID_FIELD: report_id},
                )
            except BaseManagerGetError as err:
                LOGGER.error("[migration_reports] Exception: %s. Type: %s", err, type(err))
                raise ScopeRolesManagerGetError(err) from err

            if found:
                reports[report_id] = found[0]

        return reports

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

    def pull_type_from_roles(self, type_id: int) -> int:
        """
        Removes a Type id from every role listing it, in one write. A role left with no Type is kept and grants nothing

        Re-run safe: a second call finds nothing to pull

        Args:
            type_id (int): The CmdbType's public_id

        Raises:
            ScopeRolesManagerUpdateError: When the write fails

        Returns:
            int: How many roles were changed
        """
        try:
            return self.update_many_pull({ScopeRoleKey.TYPES.value: type_id},
                                         {ScopeRoleKey.TYPES.value: type_id}).modified_count
        except BaseManagerUpdateError as err:
            LOGGER.error("[pull_type_from_roles] Exception: %s. Type: %s", err, type(err))
            raise ScopeRolesManagerUpdateError(err) from err


    def pull_missing_types(self, existing_type_ids: list[int]) -> int:
        """
        Removes from every role listing Type ids each id that is not among the given stored ones, in one write - after
        Types went past the Type delete (a configuration reset). A role covering every Type is left alone

        Re-run safe: a second call finds nothing to pull

        Args:
            existing_type_ids (list[int]): The public_ids of the Types still stored

        Raises:
            ScopeRolesManagerUpdateError: When the write fails

        Returns:
            int: How many roles were changed
        """
        try:
            return self.update_many_raw(
                {ScopeRoleKey.TYPES.value: {'$type': 'array'}},
                {'$pull': {ScopeRoleKey.TYPES.value: {'$nin': list(existing_type_ids)}}},
            ).modified_count
        except BaseManagerUpdateError as err:
            LOGGER.error("[pull_missing_types] Exception: %s. Type: %s", err, type(err))
            raise ScopeRolesManagerUpdateError(err) from err
