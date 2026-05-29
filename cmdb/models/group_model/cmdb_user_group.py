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
Represents a CmdbUserGroup in DataGerry
"""
from logging import Logger, getLogger

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.right_model.base_right import BaseRight
from cmdb.models.right_model.constants import GLOBAL_RIGHT_IDENTIFIER

from cmdb.class_schema.group_model.cmdb_user_group_schema import get_cmdb_user_group_schema

from cmdb.errors.models.cmdb_user_group import (
    CmdbUserGroupInitError,
    CmdbUserGroupInitFromDataError,
    CmdbUserGroupToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 CmdbUserGroup - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class CmdbUserGroup(CmdbDAO):
    """
    Implementation of CmdbUserGroup. Every CmdbUser is part of a CmdbUserGroup in DataGerry
    """
    COLLECTION = 'management.groups'
    MODEL = 'Group'
    INDEX_KEYS = [
        {'keys': [('name', CmdbDAO.DAO_ASCENDING)], 'name': 'name', 'unique': True}
    ]

    SCHEMA: dict = get_cmdb_user_group_schema()


    def __init__(self, public_id: int, name: str, label: str = None, rights: list[BaseRight] = None):
        """
        Initialises a CmdbUserGroup

        Args:
            public_id (int): public_id of the CmdbUserGroup
            name (str): Unique name of the CmdbUserGroup
            label (str, optional): Displayed label of the CmdbUserGroup. Defaults to None
            rights (list[BaseRight], optional): CmdbRights given to this CmdbUserGroup. Defaults to None

        Raises:
            CmdbUserGroupInitError: If the initialisation fails
        """
        try:
            self.name: str = name
            self.label: str = label or name.title()
            self.rights: list = rights or []

            super().__init__(public_id=public_id)
        except Exception as err:
            raise CmdbUserGroupInitError(err) from err

# --------------------------------------------------- CLASS METHODS -------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict, rights: list[BaseRight] = None) -> "CmdbUserGroup":
        """
        Initialises a CmdbUserGroup from a dict

        Args:
            data (dict): Data with which the CmdbUserGroup should be initialised

        Raises:
            CmdbUserGroupInitFromDataError: If the initialisation with the given data fails

        Returns:
            CmdbUserGroup: CmdbUserGroup with the given data
        """
        try:
            if rights:
                rights = [right for right in rights if right['name'] in data.get('rights', [])]
            else:
                rights = []

            return cls(
                public_id=data.get('public_id'),
                name=data.get('name'),
                label=data.get('label', None),
                rights=rights
            )
        except Exception as err:
            raise CmdbUserGroupInitFromDataError(err) from err


    @classmethod
    def to_json(cls, instance: "CmdbUserGroup", insert_mode: bool = False) -> dict:
        """
        Converts a CmdbUserGroup into a json compatible dict

        Args:
            instance (CmdbUserGroup): The CmdbUserGroup which should be converted

        Raises:
            CmdbUserGroupToJsonError: If the CmdbUserGroup could not be converted to a json compatible dict

        Returns:
            dict: Json compatible dict of the CmdbUserGroup values
        """
        rights = []

        if insert_mode:
            rights = [right.name for right in instance.rights]
        else:
            rights = [BaseRight.to_dict(right) for right in instance.rights]

        try:
            return {
                'public_id': instance.public_id,
                'name': instance.name,
                'label': instance.label,
                'rights': rights
            }
        except Exception as err:
            raise CmdbUserGroupToJsonError(err) from err

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    def has_right(self, right_name: str) -> bool:
        """
        Check if a CmdbRight exists in the CmdbUserGroup

        Args:
            right_name (str): The name of the CmdbRight to check

        Returns:
            bool: True if the right exists, otherwise False
        """
        return any(right.name == right_name for right in self.rights)


    def has_extended_right(self, right_name: str) -> bool:
        """
        Recursively checks if a CmdbUserGroup has an extended right

        Args:
            right_name (str): The name of the right to check

        Returns:
            bool: True if the extended right exists, otherwise False
        """
        parent_right_name: str = right_name.rsplit(".", 1)[0]

        if self.has_right(f'{parent_right_name}.{GLOBAL_RIGHT_IDENTIFIER}'):
            return True

        if parent_right_name == 'base':
            return self.has_right(f'{parent_right_name}.{GLOBAL_RIGHT_IDENTIFIER}')

        return self.has_extended_right(right_name=parent_right_name)
