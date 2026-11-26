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
This module contains the implementation of the FieldRulesManager - the Field Rules
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_constants import MONGO_ID_FIELD
from cmdb.manager.generic_manager import GenericManager

from cmdb.models.access_model import CmdbFieldRule, FieldRuleKey

from cmdb.errors.manager import BaseManagerGetError, BaseManagerUpdateError
from cmdb.errors.manager.field_rules_manager import (
    FIELD_RULES_MANAGER_ERRORS,
    FieldRulesManagerGetError,
    FieldRulesManagerUpdateError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                             FieldRulesManager - CLASS                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class FieldRulesManager(GenericManager):
    """
    The FieldRulesManager manages the Field Rules of the access rules in the database

    Extends: GenericManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        """
        Set the database connection for the FieldRulesManager

        Args:
            dbm (MongoDatabaseManager): Database interaction manager
            database (str | None): Name of the database the dbm should connect to. Only used in cloud mode
        """
        super().__init__(dbm, CmdbFieldRule, FIELD_RULES_MANAGER_ERRORS, database)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def all_rules(self) -> list[dict[str, Any]]:
        """
        Every stored Field Rule, ascending by public_id

        Raises:
            FieldRulesManagerGetError: When the read fails

        Returns:
            list[dict[str, Any]]: The rules as stored
        """
        try:
            return self.find(criteria={}, projection={MONGO_ID_FIELD: 0}, sort=[(FieldRuleKey.PUBLIC_ID.value, 1)])
        except BaseManagerGetError as err:
            LOGGER.error("[all_rules] Exception: %s. Type: %s", err, type(err))
            raise FieldRulesManagerGetError(err) from err


    def rules_naming_type(self, type_id: int) -> list[dict[str, Any]]:
        """
        The rules listing a Type by its id - the ones a Type delete changes; a rule on every Type names none

        Args:
            type_id (int): The CmdbType's public_id

        Raises:
            FieldRulesManagerGetError: When the read fails

        Returns:
            list[dict[str, Any]]: The rules as stored, ascending by public_id
        """
        try:
            return self.find(criteria={FieldRuleKey.TYPES.value: type_id}, projection={MONGO_ID_FIELD: 0},
                             sort=[(FieldRuleKey.PUBLIC_ID.value, 1)])
        except BaseManagerGetError as err:
            LOGGER.error("[rules_naming_type] Exception: %s. Type: %s", err, type(err))
            raise FieldRulesManagerGetError(err) from err


    def active_rules(self) -> list[dict[str, Any]]:
        """
        Every active Field Rule, in the order rules run (ascending public_id)

        Raises:
            FieldRulesManagerGetError: When the read fails

        Returns:
            list[dict[str, Any]]: The rules as stored
        """
        try:
            return self.find(criteria={FieldRuleKey.ACTIVE.value: {'$ne': False}}, projection={MONGO_ID_FIELD: 0},
                             sort=[(FieldRuleKey.PUBLIC_ID.value, 1)])
        except BaseManagerGetError as err:
            LOGGER.error("[active_rules] Exception: %s. Type: %s", err, type(err))
            raise FieldRulesManagerGetError(err) from err


    def name_taken(self, name: str, own_id: int | None = None) -> bool:
        """
        Whether another stored Field Rule carries a name

        Args:
            name (str): The name
            own_id (int | None): The rule being written, which may carry it. Defaults to None

        Raises:
            FieldRulesManagerGetError: When the read fails

        Returns:
            bool: True when another rule carries it
        """
        try:
            found: list[dict[str, Any]] = self.find(criteria={FieldRuleKey.NAME.value: name},
                                                    projection={FieldRuleKey.PUBLIC_ID.value: 1, MONGO_ID_FIELD: 0})
        except BaseManagerGetError as err:
            LOGGER.error("[name_taken] Exception: %s. Type: %s", err, type(err))
            raise FieldRulesManagerGetError(err) from err

        return any(document[FieldRuleKey.PUBLIC_ID.value] != own_id for document in found)

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

    def pull_type_from_rules(self, type_id: int) -> int:
        """
        Removes a Type id from every rule listing it, in one write. A rule left with no Type is kept and runs nowhere

        Re-run safe: a second call finds nothing to pull

        Args:
            type_id (int): The CmdbType's public_id

        Raises:
            FieldRulesManagerUpdateError: When the write fails

        Returns:
            int: How many rules were changed
        """
        try:
            return self.update_many_pull({FieldRuleKey.TYPES.value: type_id},
                                         {FieldRuleKey.TYPES.value: type_id}).modified_count
        except BaseManagerUpdateError as err:
            LOGGER.error("[pull_type_from_rules] Exception: %s. Type: %s", err, type(err))
            raise FieldRulesManagerUpdateError(err) from err


    def pull_missing_types(self, existing_type_ids: list[int]) -> int:
        """
        Removes from every rule listing Type ids each id that is not among the given stored ones, in one write - after
        Types went past the Type delete (a configuration reset). A rule on every Type is left alone

        Re-run safe: a second call finds nothing to pull

        Args:
            existing_type_ids (list[int]): The public_ids of the Types still stored

        Raises:
            FieldRulesManagerUpdateError: When the write fails

        Returns:
            int: How many rules were changed
        """
        try:
            return self.update_many_raw(
                {FieldRuleKey.TYPES.value: {'$type': 'array'}},
                {'$pull': {FieldRuleKey.TYPES.value: {'$nin': list(existing_type_ids)}}},
            ).modified_count
        except BaseManagerUpdateError as err:
            LOGGER.error("[pull_missing_types] Exception: %s. Type: %s", err, type(err))
            raise FieldRulesManagerUpdateError(err) from err
