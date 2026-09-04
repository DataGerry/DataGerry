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
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.database import MongoDatabaseManager
from cmdb.manager.generic_manager import GenericManager

from cmdb.models.extendable_option_model import CmdbExtendableOption, ExtendableOptionKey

from cmdb.errors.manager import BaseManagerGetError
from cmdb.errors.manager.extendable_options_manager import (
    EXTENDABLE_OPTIONS_MANAGER_ERRORS,
    ExtendableOptionsManagerGetError,
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
