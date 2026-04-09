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
This module contains the implementation of CmdbObject, which is representing
an object in DataGerry
"""
from logging import Logger, getLogger
from typing import Any
from datetime import datetime, timezone
from dateutil.parser import parse

from cmdb.class_schema.cmdb_object_schema import get_cmdb_object_schema
from cmdb.models.cmdb_dao import CmdbDAO

from cmdb.errors.models.cmdb_object import (
    CmdbObjectInitError,
    CmdbObjectInitFromDataError,
    CmdbObjectToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  CmdbObject - CLASS                                                  #
# -------------------------------------------------------------------------------------------------------------------- #

class CmdbObject(CmdbDAO):
    """
    The CmdbObject is the basic data wrapper for storing and holding the pure objects within the CMDB

    Extends CmdbDAO
    """
    COLLECTION = 'framework.objects'
    MODEL = 'Object'
    DEFAULT_VERSION = '1.0.0'
    REQUIRED_INIT_KEYS: list[str] = ['type_id', 'creation_time', 'author_id', 'active', 'fields', 'version']
    SCHEMA: dict[str, Any] = get_cmdb_object_schema()

    INDEX_KEYS: list[dict[str, Any]] = [
        {'keys': [('type_id', CmdbDAO.DAO_ASCENDING)], 'name': 'type_id', 'unique': False},
        {"keys": [("fields.value", CmdbDAO.DAO_ASCENDING)], "name": "fields_value", "unique": False},
        {
            "keys": [("multi_data_sections.values.data.value", CmdbDAO.DAO_ASCENDING)],
            "name": "multi_data_sections_values_data_value",
            "unique": False
        }
    ]

    #pylint: disable=R0913, R0917
    def __init__(
        self,
        type_id: int,
        creation_time: datetime,
        author_id: int,
        active: bool,
        fields: list[dict[str, Any]],
        multi_data_sections: list | None = None,
        last_edit_time: datetime | None = None,
        editor_id: int | None = None,
        version: str = '1.0.0',
        ci_explorer_tooltip: str | None = None,
        **kwargs: Any
    ) -> None:
        """
        Initialises a CmdbObject

        Args:
            type_id (int): public_id of the CmdbType
            version (str): current version of the CmdbObject
            creation_time (datetime): date of CmdbObject creation
            author_id (int): public_id of the CmdbUser which created this CmdbObject
            last_edit_time (datetime): date when this CmdbObject was edited the last time
            editor_id (int): public_id of the CmdbUser which edited this CmdbObject the last time
            active (bool): activation status of the CmdbObject (True = active, False = inactive)
            fields (list): Fields with values for his CmdbObject
            ci_explorer_tooltip (str): Tooltip to show for this CmdbObject in the CI Explorer when it is hovered
            multi_data_sections (list): MDS with values for this CmdbObject
            **kwargs: additional data

        Raises:
            CmdbObjectInitError: If the initialisation failed
        """
        try:
            self.type_id: int = type_id
            self.version: str = version
            self.creation_time: datetime = creation_time
            self.author_id: int = author_id
            self.last_edit_time: datetime | None = last_edit_time
            self.editor_id: int | None = editor_id
            self.active: bool = active
            self.fields: list[dict[str, Any]] = fields
            self.ci_explorer_tooltip: str | None = ci_explorer_tooltip
            self.multi_data_sections = multi_data_sections or []

            super().__init__(**kwargs)
        except Exception as err:
            raise CmdbObjectInitError(str(err)) from err


    def __truediv__(self, other: "CmdbObject") -> dict[str, list[Any]]:
        """
        Compares the 'fields' of two CmdbObjects of the same class and returns a dictionary with differences

        This method is called when the '/' (division) operator is used between two objects of the same class

        Args:
            other (object): The CmdbObject to compare with the current CmdbObject

        Returns:
            dict: A dictionary with two keys:
                - 'old': A list of fields present in `self.fields` but not in `other.fields`.
                - 'new': A list of fields present in `other.fields` but not in `self.fields`.

        Raises:
            TypeError: If the `other` object is not of the same class as `self`.
        """
        if not isinstance(other, self.__class__):
            raise TypeError("Not the same class")

        return {**{'old': [i for i in self.fields if i not in other.fields]},
                **{'new': [j for j in other.fields if j not in self.fields]}}


    @classmethod
    def from_data(cls, data: dict[str, Any]) -> "CmdbObject":
        """
        Initialises a CmdbObject from a dict

        Args:
            data (dict): Data with which the CmdbObject should be initialised

        Raises:
            CmdbObjectInitFromDataError: If the initialisation with the given data fails

        Returns:
            CmdbObject: CmdbObject with the given data
        """
        try:
            creation_time: Any | None = data.get('creation_time')
            last_edit_time: Any | None = data.get('last_edit_time')

            if isinstance(creation_time, str):
                creation_time = parse(creation_time, fuzzy=True)

            if isinstance(last_edit_time, str):
                last_edit_time = parse(last_edit_time, fuzzy=True)

            return cls(
                public_id=data.get('public_id'),
                type_id=int(data["type_id"]),
                version=data.get("version", "1.0.0"),
                creation_time=creation_time or datetime.now(timezone.utc),
                author_id=int(data["author_id"]),
                last_edit_time=last_edit_time,
                editor_id=data.get('editor_id'),
                active=data.get("active", True),
                fields=data.get('fields', []),
                ci_explorer_tooltip=data.get('ci_explorer_tooltip'),
                multi_data_sections=data.get('multi_data_sections', []),
            )
        except Exception as err:
            raise CmdbObjectInitFromDataError(str(err)) from err


    @classmethod
    def to_json(cls, instance: "CmdbObject") -> dict[str, Any]:
        """
        Converts a CmdbObject into a json compatible dict

        Args:
            instance (CmdbObject): The CmdbObject which should be converted

        Raises:
            CmdbObjectToJsonError: If the CmdbObject could not be converted to a json compatible dict

        Returns:
            dict: Json compatible dict of the CmdbObject values
        """
        try:
            return {
                'public_id': instance.get_public_id(),
                'type_id': instance.get_type_id(),
                'version': instance.version,
                'creation_time': instance.creation_time,
                'author_id': instance.author_id,
                'last_edit_time': instance.last_edit_time,
                'editor_id': instance.editor_id,
                'active': instance.active,
                'fields': instance.fields,
                'ci_explorer_tooltip': instance.ci_explorer_tooltip,
                'multi_data_sections': instance.multi_data_sections,
            }
        except Exception as err:
            raise CmdbObjectToJsonError(str(err)) from err


    def get_type_id(self) -> int:
        """
        Returns the public_id of the CmdbType which is used as a blueprint for the CmdbObject

        Returns:
            int: public_id of the CmdbType of this CmdbObject
        """
        return self.type_id


    def get_all_fields(self) -> list[dict[str, Any]]:
        """
        Reutns all fields of the CmdbObject

        Returns:
            list: All fields of the CmdbObject
        """
        return self.fields


    def get_value(self, field: str) -> str | None:
        """
        Retrieves the value of a field by its name

        This method searches for a field by its name and returns its associated value

        Args:
            field (str): The name of the field whose value is to be retrieved

        Raises:
            ValueError: If no field with the specified name is found

        Returns:
            str | None: The value of the field if found
        """
        f: dict[str, Any]
        for f in self.fields:
            if f.get('name') == field:
                return f.get('value')

        raise ValueError(field)


    def has_fields_of_type(self, field_type: str) -> bool:
        """TODO: document"""
        # check normal fields
        for field in self.fields or []:
            if field.get("type") == field_type:
                return True

        # check multi-data sections
        for section in self.multi_data_sections or []:
            for row in section.get("values", []):
                for field in row.get("data", []):
                    if field.get("type") == field_type:
                        return True

        return False
