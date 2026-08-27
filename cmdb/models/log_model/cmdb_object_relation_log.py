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
Represents a CmdbObjectRelationLog in DataGerry
"""
from logging import Logger, getLogger
from datetime import datetime, timezone
from dateutil.parser import parse

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.log_model.log_interaction_enum import LogInteraction

from cmdb.errors.models.cmdb_object_relation_log import (
    CmdbObjectRelationLogInitError,
    CmdbObjectRelationLogInitFromDataError,
    CmdbObjectRelationLogToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                             CmdbObjectRelationLog - CLASS                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class CmdbObjectRelationLog(CmdbDAO):
    """
    Implementation of a CmdbObjectRelationLog in DataGerry

    Extends: CmdbDAO
    """
    COLLECTION = 'framework.objectRelationLogs'

    INDEX_KEYS = [{
        'keys': [('object_relation_id', CmdbDAO.DAO_ASCENDING)],
        'name': 'object_relation_id',
    }]

    # pylint: disable=too-many-arguments
    def __init__(self,
                 public_id: int,
                 object_relation_id: int,
                 object_relation_parent_id: int,
                 object_relation_child_id: int,
                 creation_time: datetime,
                 action: LogInteraction,
                 author_id: int,
                 author_name: str,
                 changes: dict = None):
        """
        Creates an instance of CmdbObjectRelationLog

        Args:
            public_id (int): public_id of the CmdbObjectRelationLog
            object_relation_id (int): public_id of the CmdbObjectRelation
            object_relation_parent_id (int): public_id of the parent CmdbObject of the CmdbObjectRelation
            object_relation_child_id (int): public_id of the child CmdbObject of the CmdbObjectRelation
            creation_time (datetime): When the CmdbObjectRelationLog was created
            action: (LogInteraction): CREATE, EDIT or DELETE
            author_id (int): public_id of the CmdbUser who have done the change to the CmdbObjectRelation
            author_name (str, optional): Name of the CmdbbUser if any.
            changes (dict, optional): Changes to the CmdbObjectRelation. Defaults to None (When deleted)

        Raises:
            CmdbObjectRelationLogInitError: If the CmdbObjectRelationLog could not be initialised
        """
        try:
            self.object_relation_id = object_relation_id
            self.object_relation_parent_id = object_relation_parent_id
            self.object_relation_child_id = object_relation_child_id
            self.creation_time = creation_time or datetime.now(timezone.utc)
            self.action = action
            self.author_id = author_id
            self.author_name = author_name
            self.changes = changes

            super().__init__(public_id=public_id)
        except Exception as err:
            raise CmdbObjectRelationLogInitError(err) from err

# --------------------------------------------------- CLASS METHODS -------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict) -> "CmdbObjectRelationLog":
        """
        Generates a CmdbObjectRelationLog instance from a dict

        Args:
            data (dict): Data with which the CmdbObjectRelationLog should be instantiated

        Raises:
            CmdbObjectRelationLogInitFromDataError: If the initialisation with the given data fails

        Returns:
            CmdbObjectRelationLog: CmdbObjectRelationLog instance with given data
        """
        try:
            creation_time = data.get('creation_time', None)

            if creation_time and isinstance(creation_time, str):
                creation_time = parse(creation_time, fuzzy=True)

            return cls(
                public_id = data.get('public_id'),
                object_relation_id = data.get('object_relation_id'),
                object_relation_parent_id = data.get('object_relation_parent_id'),
                object_relation_child_id = data.get('object_relation_child_id'),
                creation_time = creation_time,
                action = data.get('action'),
                author_id = data.get('author_id'),
                author_name = data.get('author_name'),
                changes = data.get('changes', None),
            )
        except Exception as err:
            raise CmdbObjectRelationLogInitFromDataError(err) from err


    @classmethod
    def to_json(cls, instance: "CmdbObjectRelationLog") -> dict:
        """
        Converts a CmdbObjectRelationLog into a json compatible dict

        Args:
            instance (CmdbObjectRelationLog): The CmdbObjectRelationLog which should be converted

        Raises:
            CmdbObjectRelationLogToJsonError: If the CmdbObjectRelationLog could not be converted
                                              to a json compatible dict

        Returns:
            dict: Json dict of the CmdbObjectRelationLog values
        """
        try:
            return {
                'public_id': instance.get_public_id(),
                'object_relation_id': instance.object_relation_id,
                'object_relation_parent_id': instance.object_relation_parent_id,
                'object_relation_child_id': instance.object_relation_child_id,
                'creation_time': instance.creation_time,
                'action': instance.action,
                'author_id': instance.author_id,
                'author_name': instance.author_name,
                'changes': instance.changes,
            }
        except Exception as err:
            raise CmdbObjectRelationLogToJsonError(err) from err
