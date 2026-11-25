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
Implementation of CmdbFieldClass in DataGerry

A field class is a named protection class: a type field carrying it may only be written by a scope role granting
it. The name is the identifier fields and roles reference; the label is what the class is shown under
"""
from typing import Any
from logging import Logger, getLogger

from cmdb.models.cmdb_dao import CmdbDAO

from cmdb.class_schema.access_model.cmdb_field_class_schema import get_cmdb_field_class_schema
from cmdb.models.access_model.access_constants import FieldClassKey

from cmdb.errors.models.cmdb_field_class import (
    CmdbFieldClassInitError,
    CmdbFieldClassInitFromDataError,
    CmdbFieldClassToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                CmdbFieldClass - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class CmdbFieldClass(CmdbDAO):
    """
    Implementation of CmdbFieldClass

    Extends: CmdbDAO
    """
    COLLECTION = 'access.fieldClasses'
    # What its own from_data / to_json raise - declared so a manager can tell a document that no longer
    # fits the model from a programming error (GenericManager._model_errors)
    INIT_FROM_DATA_ERROR: type[Exception] = CmdbFieldClassInitFromDataError
    TO_JSON_ERROR: type[Exception] = CmdbFieldClassToJsonError
    INDEX_KEYS = [
        {'keys': [(FieldClassKey.NAME.value, CmdbDAO.DAO_ASCENDING)], 'name': FieldClassKey.NAME.value, 'unique': True},
    ]

    SCHEMA: dict[str, Any] = get_cmdb_field_class_schema()


    def __init__(self, *, public_id: int, name: str, label: str, description: str = '') -> None:
        """
        Initialises a CmdbFieldClass

        Args:
            public_id (int): public_id of the CmdbFieldClass
            name (str): The identifier fields and scope roles reference
            label (str): The name the class is shown under
            description (str): What the class protects. Defaults to ''

        Raises:
            CmdbFieldClassInitError: When the CmdbFieldClass could not be initialised
        """
        try:
            self.name: str = name
            self.label: str = label
            self.description: str = description or ''

            super().__init__(public_id=public_id)
        except Exception as err:
            raise CmdbFieldClassInitError(err) from err

# -------------------------------------------------- CLASS FUNCTIONS ------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> "CmdbFieldClass":
        """
        Initialises a CmdbFieldClass from a dict

        Args:
            data (dict[str, Any]): Data with which the CmdbFieldClass should be initialised

        Raises:
            CmdbFieldClassInitFromDataError: If the initialisation with the given data fails

        Returns:
            CmdbFieldClass: CmdbFieldClass with the given data
        """
        try:
            return cls(
                public_id=data.get(FieldClassKey.PUBLIC_ID.value),
                name=data.get(FieldClassKey.NAME.value),
                label=data.get(FieldClassKey.LABEL.value),
                description=data.get(FieldClassKey.DESCRIPTION.value, ''),
            )
        except Exception as err:
            raise CmdbFieldClassInitFromDataError(err) from err


    @classmethod
    def to_json(cls, instance: "CmdbFieldClass") -> dict[str, Any]:
        """
        Converts a CmdbFieldClass into a json compatible dict

        Args:
            instance (CmdbFieldClass): The CmdbFieldClass which should be converted

        Raises:
            CmdbFieldClassToJsonError: If the CmdbFieldClass could not be converted to a json compatible dict

        Returns:
            dict[str, Any]: Json compatible dict of the CmdbFieldClass values
        """
        try:
            return {
                FieldClassKey.PUBLIC_ID.value: instance.get_public_id(),
                FieldClassKey.NAME.value: instance.name,
                FieldClassKey.LABEL.value: instance.label,
                FieldClassKey.DESCRIPTION.value: instance.description,
            }
        except Exception as err:
            raise CmdbFieldClassToJsonError(err) from err
