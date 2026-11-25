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
This module contains the implementation of the FieldClassesManager
"""
from logging import Logger, getLogger
from typing import Any
from collections.abc import Iterable

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_constants import MONGO_ID_FIELD
from cmdb.manager.generic_manager import GenericManager

from cmdb.models.access_model import CmdbFieldClass, FieldClassKey

from cmdb.errors.manager import BaseManagerGetError
from cmdb.errors.manager.field_classes_manager import FIELD_CLASSES_MANAGER_ERRORS, FieldClassesManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                             FieldClassesManager - CLASS                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class FieldClassesManager(GenericManager):
    """
    The FieldClassesManager manages the field classes of the permission data model in the database

    Extends: GenericManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        """
        Set the database connection for the FieldClassesManager

        Args:
            dbm (MongoDatabaseManager): Database interaction manager
            database (str | None): Name of the database the dbm should connect to. Only used in cloud mode
        """
        super().__init__(dbm, CmdbFieldClass, FIELD_CLASSES_MANAGER_ERRORS, database)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def find_existing_names(self, names: Iterable[str]) -> set[str]:
        """
        Reports which of the given field class names are stored

        One projected ``$in`` read, so a scope role naming several classes is checked in one query

        Args:
            names (Iterable[str]): The class names to look for; an empty selection queries nothing

        Raises:
            FieldClassesManagerGetError: When the read fails

        Returns:
            set[str]: The subset that is stored. Subtract it from the input to get the unknown names
        """
        wanted: list[str] = list(names or [])

        if not wanted:
            return set()

        try:
            documents: list[dict[str, Any]] = self.find(
                criteria={FieldClassKey.NAME.value: {'$in': wanted}},
                projection={FieldClassKey.NAME.value: 1, MONGO_ID_FIELD: 0},
            )

            return {document[FieldClassKey.NAME.value] for document in documents}
        except BaseManagerGetError as err:
            LOGGER.error("[find_existing_names] Exception: %s. Type: %s", err, type(err))
            raise FieldClassesManagerGetError(err) from err
