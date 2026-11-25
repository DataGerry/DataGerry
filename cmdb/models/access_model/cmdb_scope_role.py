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
Implementation of CmdbScopeRole in DataGerry

A scope role bundles the operations it grants on its Types - one set for all of them - and which fields it may
write: the regular ones (``write_regular_fields``) and those of the named field classes. Its Types are every Type
(``ALL_TYPES``) or a list of Type ids. The same role serves any number of assignments
"""
from typing import Any
from logging import Logger, getLogger

from cmdb.models.cmdb_dao import CmdbDAO

from cmdb.class_schema.access_model.cmdb_scope_role_schema import get_cmdb_scope_role_schema
from cmdb.models.access_model.access_constants import ScopeRoleKey

from cmdb.errors.models.cmdb_scope_role import (
    CmdbScopeRoleInitError,
    CmdbScopeRoleInitFromDataError,
    CmdbScopeRoleToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                CmdbScopeRole - CLASS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class CmdbScopeRole(CmdbDAO):
    """
    Implementation of CmdbScopeRole

    Extends: CmdbDAO
    """
    COLLECTION = 'access.scopeRoles'
    # What its own from_data / to_json raise - declared so a manager can tell a document that no longer
    # fits the model from a programming error (GenericManager._model_errors)
    INIT_FROM_DATA_ERROR: type[Exception] = CmdbScopeRoleInitFromDataError
    TO_JSON_ERROR: type[Exception] = CmdbScopeRoleToJsonError
    INDEX_KEYS = [
        {'keys': [(ScopeRoleKey.NAME.value, CmdbDAO.DAO_ASCENDING)], 'name': ScopeRoleKey.NAME.value, 'unique': True},
        # The roles naming a Type - read when a Type is deleted
        {'keys': [(ScopeRoleKey.TYPES.value, CmdbDAO.DAO_ASCENDING)], 'name': ScopeRoleKey.TYPES.value},
        # The roles granting a field class - read when a class is deleted
        {
            'keys': [(ScopeRoleKey.FIELD_CLASSES.value, CmdbDAO.DAO_ASCENDING)],
            'name': ScopeRoleKey.FIELD_CLASSES.value,
        },
    ]

    SCHEMA: dict[str, Any] = get_cmdb_scope_role_schema()


    def __init__(
        self,
        *,
        public_id: int,
        name: str,
        types: str | list[int],
        operations: list[str],
        description: str = '',
        write_regular_fields: bool = False,
        field_classes: list[str] | None = None,
    ) -> None:
        """
        Initialises a CmdbScopeRole

        Args:
            public_id (int): public_id of the CmdbScopeRole
            name (str): The unique name the role is listed under
            types (str | list[int]): ``ALL_TYPES`` or the public_ids of the CmdbTypes it covers
            operations (list[str]): The ``ScopeOperation`` values it grants
            description (str): What the role is for. Defaults to ''
            write_regular_fields (bool): Whether it may write the fields carrying no field class. Defaults to False
            field_classes (list[str] | None): The field classes whose fields it may write. Defaults to none

        Raises:
            CmdbScopeRoleInitError: When the CmdbScopeRole could not be initialised
        """
        try:
            self.name: str = name
            self.types: str | list[int] = types if isinstance(types, str) else list(types)
            self.operations: list[str] = list(operations)
            self.description: str = description or ''
            self.write_regular_fields: bool = bool(write_regular_fields)
            self.field_classes: list[str] = list(field_classes or [])

            super().__init__(public_id=public_id)
        except Exception as err:
            raise CmdbScopeRoleInitError(err) from err

# -------------------------------------------------- CLASS FUNCTIONS ------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> "CmdbScopeRole":
        """
        Initialises a CmdbScopeRole from a dict

        Args:
            data (dict[str, Any]): Data with which the CmdbScopeRole should be initialised

        Raises:
            CmdbScopeRoleInitFromDataError: If the initialisation with the given data fails

        Returns:
            CmdbScopeRole: CmdbScopeRole with the given data
        """
        try:
            return cls(
                public_id=data.get(ScopeRoleKey.PUBLIC_ID.value),
                name=data.get(ScopeRoleKey.NAME.value),
                types=data.get(ScopeRoleKey.TYPES.value),
                operations=data.get(ScopeRoleKey.OPERATIONS.value),
                description=data.get(ScopeRoleKey.DESCRIPTION.value, ''),
                write_regular_fields=data.get(ScopeRoleKey.WRITE_REGULAR_FIELDS.value, False),
                field_classes=data.get(ScopeRoleKey.FIELD_CLASSES.value),
            )
        except Exception as err:
            raise CmdbScopeRoleInitFromDataError(err) from err


    @classmethod
    def to_json(cls, instance: "CmdbScopeRole") -> dict[str, Any]:
        """
        Converts a CmdbScopeRole into a json compatible dict

        Args:
            instance (CmdbScopeRole): The CmdbScopeRole which should be converted

        Raises:
            CmdbScopeRoleToJsonError: If the CmdbScopeRole could not be converted to a json compatible dict

        Returns:
            dict[str, Any]: Json compatible dict of the CmdbScopeRole values, its lists new lists
        """
        try:
            return {
                ScopeRoleKey.PUBLIC_ID.value: instance.get_public_id(),
                ScopeRoleKey.NAME.value: instance.name,
                ScopeRoleKey.DESCRIPTION.value: instance.description,
                ScopeRoleKey.TYPES.value: instance.types if isinstance(instance.types, str) else list(instance.types),
                ScopeRoleKey.OPERATIONS.value: list(instance.operations),
                ScopeRoleKey.WRITE_REGULAR_FIELDS.value: instance.write_regular_fields,
                ScopeRoleKey.FIELD_CLASSES.value: list(instance.field_classes),
            }
        except Exception as err:
            raise CmdbScopeRoleToJsonError(err) from err
