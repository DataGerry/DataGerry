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
from typing import Any

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

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 CmdbUserGroup - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class CmdbUserGroup(CmdbDAO):
    """
    Implementation of CmdbUserGroup. Every CmdbUser is part of a CmdbUserGroup in DataGerry
    """
    COLLECTION = 'management.groups'
    INDEX_KEYS = [
        {'keys': [('name', CmdbDAO.DAO_ASCENDING)], 'name': 'name', 'unique': True}
    ]

    SCHEMA: dict[str, Any] = get_cmdb_user_group_schema()


    def __init__(
        self,
        public_id: int,
        name: str,
        label: str | None = None,
        rights: list[BaseRight] | None = None,
    ):
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
            self.rights: list[BaseRight] = rights or []

            super().__init__(public_id=public_id)
        except Exception as err:
            raise CmdbUserGroupInitError(err) from err

# --------------------------------------------------- CLASS METHODS -------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict[str, Any], rights: list[BaseRight] | None = None) -> "CmdbUserGroup":
        """
        Initialises a CmdbUserGroup from a dict

        Args:
            data (dict[str, Any]): Data with which the CmdbUserGroup should be initialised
            rights (list[BaseRight] | None): Known rights used to resolve the data's right-name list
                into BaseRight instances; names not present here are dropped. Defaults to None

        Raises:
            CmdbUserGroupInitFromDataError: If the initialisation with the given data fails

        Returns:
            CmdbUserGroup: CmdbUserGroup with the given data
        """
        try:
            if rights:
                # A set, not the raw list: the tree holds ~200 rights and every one of them was
                # tested against the stored name list, which made deserialising a group O(n*m)
                granted_names: set[str] = set(data.get('rights') or [])
                rights = [right for right in rights if right['name'] in granted_names]
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
    def to_json(cls, instance: "CmdbUserGroup", insert_mode: bool = False) -> dict[str, Any]:
        """
        Converts a CmdbUserGroup into a json compatible dict

        Args:
            instance (CmdbUserGroup): The CmdbUserGroup which should be converted
            insert_mode (bool): When True, rights are serialized as their name strings (the stored
                form); when False, as full BaseRight dicts. Defaults to False

        Raises:
            CmdbUserGroupToJsonError: If the CmdbUserGroup could not be converted to a json compatible dict

        Returns:
            dict: Json compatible dict of the CmdbUserGroup values
        """
        try:
            if insert_mode:
                rights: list[Any] = [right.name for right in instance.rights]
            else:
                rights = [BaseRight.to_dict(right) for right in instance.rights]

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

        Walks the qualified name outwards one segment at a time and asks whether the group holds the
        wildcard right of that parent - so `base.framework.object.view` is granted by
        `base.framework.object.*`, by `base.framework.*` or by the master right `base.*`.

        The recursion stops when a segment can no longer be stripped, which is also the guard
        against a name that carries no dot at all: `rsplit` returns such a name unchanged, so
        recursing on it would never terminate.

        Args:
            right_name (str): The qualified name of the right to check

        Returns:
            bool: True if the extended right exists, otherwise False
        """
        parent_right_name: str = right_name.rsplit(".", 1)[0]

        if parent_right_name == right_name:
            # Nothing left to strip - an unqualified name, or the outermost segment already checked
            return False

        if self.has_right(f'{parent_right_name}.{GLOBAL_RIGHT_IDENTIFIER}'):
            return True

        return self.has_extended_right(right_name=parent_right_name)
