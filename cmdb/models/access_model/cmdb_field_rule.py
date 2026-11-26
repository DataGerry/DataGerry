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
Implementation of CmdbFieldRule in DataGerry

A Field Rule sets fields when a user's write changes other fields - as the server, after the write check.
The name is its identifier, a slug, unique and immutable; the public_id is the order rules run in
"""
from typing import Any
from logging import Logger, getLogger

from cmdb.models.cmdb_dao import CmdbDAO

from cmdb.class_schema.access_model.cmdb_field_rule_schema import get_cmdb_field_rule_schema
from cmdb.models.access_model.access_constants import FieldRuleKey

from cmdb.errors.models.cmdb_field_rule import (
    CmdbFieldRuleInitError,
    CmdbFieldRuleInitFromDataError,
    CmdbFieldRuleToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                CmdbFieldRule - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class CmdbFieldRule(CmdbDAO):
    """
    Implementation of CmdbFieldRule

    Extends: CmdbDAO
    """
    COLLECTION = 'access.fieldRules'
    # What its own from_data / to_json raise - declared so a manager can tell a document that no longer
    # fits the model from a programming error (GenericManager._model_errors)
    INIT_FROM_DATA_ERROR: type[Exception] = CmdbFieldRuleInitFromDataError
    TO_JSON_ERROR: type[Exception] = CmdbFieldRuleToJsonError
    INDEX_KEYS = [
        {'keys': [(FieldRuleKey.NAME.value, CmdbDAO.DAO_ASCENDING)], 'name': FieldRuleKey.NAME.value, 'unique': True},
    ]

    SCHEMA: dict[str, Any] = get_cmdb_field_rule_schema()


    def __init__(self, *, public_id: int, name: str, types: Any, when: dict[str, Any],
                 set_values: dict[str, Any],
                 description: str = '', active: bool = True, unless: dict[str, Any] | None = None) -> None:
        """
        Initialises a CmdbFieldRule

        Args:
            public_id (int): public_id of the CmdbFieldRule
            name (str): Its identifier
            types (Any): ``'*'`` or the Type ids it applies to
            when (dict[str, Any]): The trigger
            set_values (dict[str, Any]): The values it writes, by field name (the ``set`` key)
            description (str): What it is for. Defaults to ''
            active (bool): Whether it runs. Defaults to True
            unless (dict[str, Any] | None): The exception. Defaults to None

        Raises:
            CmdbFieldRuleInitError: When the CmdbFieldRule could not be initialised
        """
        try:
            self.name: str = name
            self.types: Any = types
            self.when: dict[str, Any] = when
            self.set_values: dict[str, Any] = set_values
            self.description: str = description or ''
            self.active: bool = active is not False
            self.unless: dict[str, Any] | None = unless

            super().__init__(public_id=public_id)
        except Exception as err:
            raise CmdbFieldRuleInitError(err) from err

# -------------------------------------------------- CLASS FUNCTIONS ------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> "CmdbFieldRule":
        """
        Initialises a CmdbFieldRule from a dict

        Args:
            data (dict[str, Any]): Data with which the CmdbFieldRule should be initialised

        Raises:
            CmdbFieldRuleInitFromDataError: If the initialisation with the given data fails

        Returns:
            CmdbFieldRule: CmdbFieldRule with the given data
        """
        try:
            return cls(
                public_id=data.get(FieldRuleKey.PUBLIC_ID.value),
                name=data.get(FieldRuleKey.NAME.value),
                types=data.get(FieldRuleKey.TYPES.value),
                when=data.get(FieldRuleKey.WHEN.value),
                set_values=data.get(FieldRuleKey.SET.value),
                description=data.get(FieldRuleKey.DESCRIPTION.value, ''),
                active=data.get(FieldRuleKey.ACTIVE.value, True),
                unless=data.get(FieldRuleKey.UNLESS.value),
            )
        except Exception as err:
            raise CmdbFieldRuleInitFromDataError(err) from err


    @classmethod
    def to_json(cls, instance: "CmdbFieldRule") -> dict[str, Any]:
        """
        Converts a CmdbFieldRule into a json compatible dict

        Args:
            instance (CmdbFieldRule): The CmdbFieldRule which should be converted

        Raises:
            CmdbFieldRuleToJsonError: If the CmdbFieldRule could not be converted to a json compatible dict

        Returns:
            dict[str, Any]: Json compatible dict of the CmdbFieldRule values
        """
        try:
            return {
                FieldRuleKey.PUBLIC_ID.value: instance.get_public_id(),
                FieldRuleKey.NAME.value: instance.name,
                FieldRuleKey.DESCRIPTION.value: instance.description,
                FieldRuleKey.ACTIVE.value: instance.active,
                FieldRuleKey.TYPES.value: instance.types,
                FieldRuleKey.WHEN.value: instance.when,
                FieldRuleKey.UNLESS.value: instance.unless,
                FieldRuleKey.SET.value: instance.set_values,
            }
        except Exception as err:
            raise CmdbFieldRuleToJsonError(err) from err
