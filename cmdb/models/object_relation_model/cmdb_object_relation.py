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
Represents a CmdbObjectRelation in DataGerry
"""
from logging import Logger, getLogger
from typing import Any
from datetime import datetime, timezone
from dateutil.parser import parse

from cmdb.class_schema.cmdb_object_relation_schema import get_cmdb_object_relation_schema
from cmdb.models.cmdb_dao import CmdbDAO

from cmdb.errors.models.cmdb_object_relation import (
    CmdbObjectRelationInitError,
    CmdbObjectRelationInitFromDataError,
    CmdbObjectRelationToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

# -------------------------------------------------------------------------------------------------------------------- #
#                                              CmdbObjectRelation - CLASS                                              #
# -------------------------------------------------------------------------------------------------------------------- #
#pylint: disable=too-many-instance-attributes
class CmdbObjectRelation(CmdbDAO):
    """
    Implementation of a CmdbObjectRelation in DataGerry

    `Extends`: CmdbDAO
    """
    COLLECTION = "framework.objectRelations"
    MODEL = 'ObjectRelation'

    INDEX_KEYS: list[dict[str, Any]] = [
        {'keys': [('relation_id', CmdbDAO.DAO_ASCENDING)], 'name': 'relation_id', 'unique': False},
        {'keys': [('relation_parent_id', CmdbDAO.DAO_ASCENDING)], 'name': 'relation_parent_id', 'unique': False},
        {
            'keys': [('relation_parent_type_id', CmdbDAO.DAO_ASCENDING)],
            'name': 'relation_parent_type_id',
            'unique': False
        },
        {'keys': [('relation_child_id', CmdbDAO.DAO_ASCENDING)], 'name': 'relation_child_id', 'unique': False},
        {
            'keys': [('relation_child_type_id', CmdbDAO.DAO_ASCENDING)],
            'name': 'relation_child_type_id',
            'unique': False
        }
    ]

    SCHEMA: dict = get_cmdb_object_relation_schema()

    #pylint: disable=too-many-arguments
    #pylint: disable=too-many-locals
    def __init__(self,
                 public_id: int,
                 relation_id: int,
                 relation_parent_id: int,
                 relation_parent_type_id: int,
                 relation_child_id: int,
                 relation_child_type_id: int,
                 author_id: int,
                 creation_time: datetime = None,
                 last_edit_time: datetime = None,
                 field_values: list[dict] = None):
        """
        Initialises a CmdbObjectRelation

        Args:
            public_id (int): public_id of CmdbObjectRelation
            relation_id (int): public_id of the CmdbRelation
            relation_parent_id (int): public_id of the parent CmdbObject
            relation_parent_type_id (int): public_id of the parent CmdbType
            relation_child_id (int): public_id of the child CmdbObject
            relation_child_type_id (int): public_id of the child CmdbType
            author_id (int): public_id of the CmdbUser who created the CmdbObjectRelation then the last one editing it
            creation_time (datetime, optional): When the CmdbObjectRelation was created. Defaults to None
            last_edit_time (datetime, optional): When the CmdbObjectRelation was last time edited. Defaults to None
            field_values (list[dict], optional): All field values for this CmdbObjectRelation. Defaults to None

        Raises:
            CmdbObjectRelationInitError: If the initialisation failed
        """
        try:
            self.relation_id = relation_id
            self.relation_parent_id = relation_parent_id
            self.relation_parent_type_id = relation_parent_type_id
            self.relation_child_id = relation_child_id
            self.relation_child_type_id = relation_child_type_id
            self.author_id = author_id
            self.creation_time = creation_time or datetime.now(timezone.utc)
            self.last_edit_time = last_edit_time
            self.field_values = field_values

            super().__init__(public_id=public_id)
        except Exception as err:
            raise CmdbObjectRelationInitError(err) from err

# -------------------------------------------------- CLASS FUNCTIONS ------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict) -> "CmdbObjectRelation":
        """
        Initialises a CmdbObjectRelation from a dict

        Args:
            data (dict): Data with which the CmdbObjectRelation should be initialised

        Raises:
            CmdbObjectRelationInitFromDataError: If the initialisation with the given data fails 

        Returns:
            CmdbObjectRelation: CmdbObjectRelation with the given data
        """
        try:
            creation_time = data.get('creation_time', None)

            if creation_time and isinstance(creation_time, str):
                creation_time = parse(creation_time, fuzzy=True)

            last_edit_time = data.get('last_edit_time', None)

            if last_edit_time and isinstance(last_edit_time, str):
                last_edit_time = parse(last_edit_time, fuzzy=True)

            return cls(
                public_id = data.get('public_id'),
                relation_id = data.get('relation_id'),
                relation_parent_id = data.get('relation_parent_id'),
                relation_parent_type_id = data.get('relation_parent_type_id'),
                relation_child_id = data.get('relation_child_id'),
                relation_child_type_id = data.get('relation_child_type_id'),
                author_id = data.get('author_id'),
                creation_time = creation_time,
                last_edit_time = last_edit_time,
                field_values = data.get('field_values', None) or [],
            )
        except Exception as err:
            raise CmdbObjectRelationInitFromDataError(err) from err


    @classmethod
    def to_json(cls, instance: "CmdbObjectRelation") -> dict:
        """
        Converts a CmdbObjectRelation into a json compatible dict

        Args:
            instance (CmdbObjectRelation): The CmdbObjectRelation which should be converted

        Raises:
            CmdbObjectRelationToJsonError: If the CmdbRelation could not be converted to a json compatible dict
        Returns:
            dict: Json dict of the CmdbObjectRelation values
        """
        try:
            return {
                'public_id': instance.get_public_id(),
                'relation_id': instance.relation_id,
                'relation_parent_id': instance.relation_parent_id,
                'relation_parent_type_id': instance.relation_parent_type_id,
                'relation_child_id': instance.relation_child_id,
                'relation_child_type_id': instance.relation_child_type_id,
                'author_id': instance.author_id,
                'creation_time': instance.creation_time,
                'last_edit_time': instance.last_edit_time,
                'field_values': instance.field_values,
            }
        except Exception as err:
            raise CmdbObjectRelationToJsonError(err) from err
