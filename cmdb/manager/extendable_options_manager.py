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
This module contains the implementation of the ExtendableOptionsManager

The CRUD is plain and inherited from GenericManager. What is added here are the three reads whose
callers need something other than a model instance per document: a snapshot of one list's values
(`get_option_values`), a public_id -> value lookup for resolving references into labels
(`get_option_values_by_id`), and the raw documents the list route answers
(`iterate_option_documents`). All three read projected or normalise on the way out, because an
option list is small, requested whole, and read far more often than it is written
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.database import MongoDatabaseManager
from cmdb.manager.generic_manager import GenericManager
from cmdb.manager.query_builder import BuilderParameters

from cmdb.models.extendable_option_model import CmdbExtendableOption, ExtendableOptionKey

from cmdb.errors.manager import BaseManagerGetError
from cmdb.errors.manager.extendable_options_manager import (
    EXTENDABLE_OPTIONS_MANAGER_ERRORS,
    ExtendableOptionsManagerGetError,
    ExtendableOptionsManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                           ExtendableOptionsManager - CLASS                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class ExtendableOptionsManager(GenericManager):
    """
    The ExtendableOptionsManager manages the interaction between CmdbExtendableOptions and the database

    Extends: GenericManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        """
        Set the database connection for the ExtendableOptionsManager

        Args:
            dbm (MongoDatabaseManager): Database interaction manager
            database (str | None): Name of the database the dbm should connect to. Only used in cloud mode
        """
        super().__init__(dbm, CmdbExtendableOption, EXTENDABLE_OPTIONS_MANAGER_ERRORS, database)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def get_option_values(self, option_type: str) -> list[str]:
        """
        Retrieves the plain values of one CmdbExtendableOption list, in the order they were created

        The read behind seeding a snapshot of an option list into something that cannot reference the
        list itself - today the CABLE SpecialType's cable-type select, whose inline options a stored
        CmdbType field can only carry as values. Ordered by public_id so the predefined values keep
        the order they were seeded in and a customer's own additions follow them

        Args:
            option_type (str): The OptionType whose values should be read

        Raises:
            ExtendableOptionsManagerGetError: If the CmdbExtendableOptions could not be retrieved

        Returns:
            list[str]: The option values, empty when the list holds nothing
        """
        try:
            options: list[dict[str, Any]] = self.find(
                criteria={ExtendableOptionKey.OPTION_TYPE.value: option_type},
                sort=[(ExtendableOptionKey.PUBLIC_ID.value, self.model.DAO_ASCENDING)],
            )

            return [
                option[ExtendableOptionKey.VALUE.value] for option in options
                if isinstance(option.get(ExtendableOptionKey.VALUE.value), str)
            ]
        except (BaseManagerGetError, Exception) as err:
            raise ExtendableOptionsManagerGetError(str(err)) from err


    def get_option_values_by_id(self, option_types: list[str]) -> dict[str, dict[int, str]]:
        """
        Retrieves the value of every CmdbExtendableOption of the given OptionTypes, keyed by public_id

        The read behind resolving an option reference into the label a report shows. One projected
        query serves every requested list - the option_type prefix of the unique compound index
        covers the '$in' - and only the three keys a label lookup needs leave the database: no model
        is built for a value that is read once and thrown away.

        A document missing its value or its option_type is left out rather than mapped to None: the
        caller's lookup then simply does not resolve, which is the same outcome as a reference to an
        option that no longer exists

        Args:
            option_types (list[str]): The OptionTypes to read, as values or OptionType members

        Raises:
            ExtendableOptionsManagerGetError: If the CmdbExtendableOptions could not be retrieved

        Returns:
            dict[str, dict[int, str]]: {option_type: {public_id: value}}, with an entry for every
                requested OptionType that holds at least one readable option
        """
        if not option_types:
            return {}

        try:
            options: list[dict[str, Any]] = self.find(
                criteria={ExtendableOptionKey.OPTION_TYPE.value: {'$in': list(option_types)}},
                projection={
                    ExtendableOptionKey.PUBLIC_ID.value: 1,
                    ExtendableOptionKey.VALUE.value: 1,
                    ExtendableOptionKey.OPTION_TYPE.value: 1,
                },
            )

            value_maps: dict[str, dict[int, str]] = {}

            for option in options:
                option_type = option.get(ExtendableOptionKey.OPTION_TYPE.value)
                value = option.get(ExtendableOptionKey.VALUE.value)
                public_id = option.get(ExtendableOptionKey.PUBLIC_ID.value)

                if option_type is None or value is None or public_id is None:
                    continue

                value_maps.setdefault(option_type, {})[public_id] = value

            return value_maps
        except Exception as err:
            raise ExtendableOptionsManagerGetError(str(err)) from err


    def iterate_option_documents(self, builder_params: BuilderParameters) -> tuple[list[dict[str, Any]], int]:
        """
        Retrieves the raw CmdbExtendableOption documents matching the given query parameters

        The read behind the list route, and deliberately not `iterate_items`: that builds a
        CmdbExtendableOption per document which the route converts straight back into a dict. An
        option list is requested whole (the frontend sends `limit=0`) and twice per ISMS or port
        form, so the route normalises the documents instead - see
        `normalize_extendable_option_document`, which also drops the '_id' the aggregation returns

        Args:
            builder_params (BuilderParameters): Filter, sort and pagination parameters

        Raises:
            ExtendableOptionsManagerIterationError: If the CmdbExtendableOptions could not be read

        Returns:
            tuple[list[dict[str, Any]], int]: The matched documents and the total number of matches,
                which is counted independently of the page and therefore also counts a document the
                caller cannot read
        """
        try:
            return self.iterate_query(builder_params)
        except Exception as err:
            raise ExtendableOptionsManagerIterationError(str(err)) from err
