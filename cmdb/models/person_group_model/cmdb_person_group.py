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
Implementation of CmdbPersonGroup
"""
from logging import Logger, getLogger

from cmdb.models.cmdb_dao import CmdbDAO

from cmdb.errors.models.cmdb_person_group import (
    CmdbPersonGroupInitError,
    CmdbPersonGroupInitFromDataError,
    CmdbPersonGroupToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                CmdbPersonGroup - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class CmdbPersonGroup(CmdbDAO):
    """
    Implementation of CmdbPersonGroup

    Extends: CmdbDAO
    """
    COLLECTION = "management.personGroup"
    MODEL = 'PersonGroup'

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
        'email': {
            'type': 'string',
            'required': True,
            'empty': True,
            'regex': r'^(?!.*\.\.)[\w\.-]+@[a-zA-Z\d-]+(\.[a-zA-Z]{2,})+$',  # Email regex pattern
        },
        'group_members': {
            'type': 'list',
            'schema': {
                'type': 'integer',
                'min': 1,
            },
        },
    }


    def __init__(
            self,
            public_id: int,
            name: str,
            group_members: list[int] = None,
            email: str = None,):
        """
        Initialises a CmdbPersonGroup

        Args:
            public_id (int): public_id of the CmdbPersonGroup
            name (str): The name of the CmdbPersonGroup
            group_members (list[int]): public_id's of assigned CmdbPersons
            email (str, optional): email of the CmdbPersonGroup

        Raises:
            CmdbPersonGroupInitError: When the CmdbPersonGroup could not be initialised
        """
        try:
            self.name = name
            self.group_members = group_members
            self.email = email

            super().__init__(public_id=public_id)
        except Exception as err:
            raise CmdbPersonGroupInitError(err) from err

# -------------------------------------------------- CLASS FUNCTIONS ------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict) -> "CmdbPersonGroup":
        """
        Initialises a CmdbPersonGroup from a dict

        Args:
            data (dict): Data with which the CmdbPersonGroup should be initialised

        Raises:
            CmdbPersonGroupInitFromDataError: If the initialisation with the given data fails

        Returns:
            CmdbPersonGroup: CmdbPersonGroup with the given data
        """
        try:
            return cls(
                public_id = data.get('public_id'),
                name = data.get('name'),
                group_members = data.get('group_members'),
                email = data.get('email'),
            )
        except Exception as err:
            raise CmdbPersonGroupInitFromDataError(err) from err


    @classmethod
    def to_json(cls, instance: "CmdbPersonGroup") -> dict:
        """
        Converts a CmdbPersonGroup into a json compatible dict

        Args:
            instance (CmdbPersonGroup): The CmdbPersonGroup which should be converted

        Raises:
            CmdbPersonGroupToJsonError: If the CmdbPersonGroup could not be converted to a json compatible dict

        Returns:
            dict: Json compatible dict of the CmdbPersonGroup values
        """
        try:
            return {
                'public_id': instance.get_public_id(),
                'name': instance.name,
                'group_members': instance.group_members,
                'email': instance.email,
            }
        except Exception as err:
            raise CmdbPersonGroupToJsonError(err) from err
