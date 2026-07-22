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
Implementation of CmdbObjectGroup in DataGerry
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.object_group_model.object_group_mode_enum import ObjectGroupMode
from cmdb.models.extendable_option_model.option_type_enum import OptionType

from cmdb.class_schema.object_group_model.cmdb_object_group_schema import get_cmdb_object_group_schema

from cmdb.errors.models.cmdb_object_group import (
    CmdbObjectGroupInitError,
    CmdbObjectGroupInitFromDataError,
    CmdbObjectGroupToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                CmdbObjectGroup - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class CmdbObjectGroup(CmdbDAO):
    """
    Implementation of CmdbObjectGroup

    Extends: CmdbDAO
    """
    OPTION_TYPE = OptionType.OBJECT_GROUP
    COLLECTION = "framework.objectGroups"
    MODEL = 'ObjectGroup'

    INDEX_KEYS: list[dict[str, Any]] = [
        {'keys': [('group_type', CmdbDAO.DAO_ASCENDING)], 'name': 'group_type', 'unique': False},
        {'keys': [('assigned_ids', CmdbDAO.DAO_ASCENDING)], 'name': 'assigned_ids', 'unique': False}
    ]

<<<<<<< HEAD
    SCHEMA: dict = {
        'public_id': {
            'type': 'integer',
            'min': 1,
        },
        'name': {
            'type': 'string',
            'required': True,
            'empty': False
        },
        'group_type': {
            'type': 'string',
            'required': True,
            'empty': False
        },
        'assigned_ids': {
            'type': 'list',
            'required': True,
            'empty': False
        },
        'categories': {
            'type': 'list',
        },
    }
=======
    SCHEMA: dict = get_cmdb_object_group_schema()
>>>>>>> origin/version-3.2

    #pylint: disable=R0917
    def __init__(
        self,
        public_id: int,
        name: str,
        group_type: ObjectGroupMode,
        assigned_ids: list[int],
        categories: list[int]
    ) -> None:
        """
        Initialises a CmdbObjectGroup

        Args:
            public_id (int): public_id of the CmdbObjectGroup
            name (str): name of the CmdbObjectGroup
            group_type (ObjectGroupMode): STATIC (for specific CmdbObjects) OR DYNAMIC (for CmdbTypes)
            assigned_ids (list[int]): assigned public_ids of CmdbObjects or CmdbTypes, depending on group_type
            categories (list[int]): public_ids of assigned CmdbExtendableOptions

        Raises:
            CmdbObjectGroupInitError: If initialsation failed
        """
        try:
            self.name = name
            self.group_type = group_type
            self.assigned_ids = assigned_ids
            self.categories = categories or []

            super().__init__(public_id=public_id)
        except Exception as err:
            raise CmdbObjectGroupInitError(str(err)) from err

# -------------------------------------------------- CLASS FUNCTIONS ------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict) -> "CmdbObjectGroup":
        """
        Initialises a CmdbObjectGroup from a dict

        Args:
            data (dict): Data with which the CmdbObjectGroup should be initialised

        Raises:
            CmdbObjectGroupInitFromDataError: If the initialisation with the given data fails

        Returns:
            CmdbObjectGroup: CmdbObjectGroup with the given data
        """
        try:
            return cls(
                public_id = data.get('public_id'),
                name = data.get('name'),
                group_type = data.get('group_type'),
                assigned_ids = data.get('assigned_ids'),
                categories = data.get('categories', []),
            )
        except Exception as err:
            raise CmdbObjectGroupInitFromDataError(str(err)) from err


    @classmethod
    def to_json(cls, instance: "CmdbObjectGroup") -> dict[str, Any]:
        """
        Converts a CmdbObjectGroup into a json compatible dict

        Args:
            instance (CmdbObjectGroup): The CmdbObjectGroup which should be converted

        Raises:
            CmdbObjectGroupToJsonError: If the CmdbObjectGroup could not be converted to a json dict

        Returns:
            dict: Json compatible dict of the CmdbObjectGroup values
        """
        try:
            return {
                'public_id': instance.get_public_id(),
                'name': instance.name,
                'group_type': instance.group_type,
                'assigned_ids': instance.assigned_ids,
                'categories': instance.categories,
            }
        except Exception as err:
            raise CmdbObjectGroupToJsonError(str(err)) from err
