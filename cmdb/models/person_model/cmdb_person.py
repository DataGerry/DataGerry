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
Implementation of CmdbPerson
"""
from logging import Logger, getLogger

from cmdb.models.cmdb_dao import CmdbDAO

from cmdb.class_schema.person_model.cmdb_person_schema import get_cmdb_person_schema

from cmdb.errors.models.cmdb_person import (
    CmdbPersonInitError,
    CmdbPersonInitFromDataError,
    CmdbPersonToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  CmdbPerson - CLASS                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class CmdbPerson(CmdbDAO):
    """
    Implementation of CmdbPerson

    Extends: CmdbDAO
    """
    COLLECTION = "management.person"
    MODEL = 'Person'

    SCHEMA: dict = get_cmdb_person_schema()

    #pylint: disable=R0917
    def __init__(
            self,
            public_id: int,
            display_name: str,
            first_name: str,
            last_name: str,
            phone_number: str = None,
            email: str = None,
            groups: list[int] = None):
        """
        Initialises a CmdbPerson

        Args:
            public_id (int): public_id of the CmdbPerson
            display_name (str): The display_name of the CmdbPerson
            first_name (str): first_name of the CmdbPerson
            last_name (str): last_name of the CmdbPerson
            phone_number (str, optional): phone_number of the CmdbPerson
            email (str, optional): email of the CmdbPerson
            groups (list[int], optional): public_id's of assigned CmdbPersonGroups

        Raises:
            CmdbPersonInitError: When the CmdbPerson could not be initialised
        """
        try:
            self.display_name = display_name
            self.first_name = first_name
            self.last_name = last_name
            self.phone_number = phone_number
            self.email = email
            self.groups = groups

            super().__init__(public_id=public_id)
        except Exception as err:
            raise CmdbPersonInitError(err) from err

# -------------------------------------------------- CLASS FUNCTIONS ------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict) -> "CmdbPerson":
        """
        Initialises a CmdbPerson from a dict

        Args:
            data (dict): Data with which the CmdbPerson should be initialised

        Raises:
            CmdbPersonInitFromDataError: If the initialisation with the given data fails

        Returns:
            CmdbPerson: CmdbPerson with the given data
        """
        try:
            return cls(
                public_id = data.get('public_id'),
                display_name = data.get('display_name'),
                first_name = data.get('first_name'),
                last_name = data.get('last_name'),
                phone_number = data.get('phone_number'),
                email = data.get('email'),
                groups = data.get('groups', []),
            )
        except Exception as err:
            raise CmdbPersonInitFromDataError(err) from err


    @classmethod
    def to_json(cls, instance: "CmdbPerson") -> dict:
        """
        Converts a CmdbPerson into a json compatible dict

        Args:
            instance (CmdbPerson): The CmdbPerson which should be converted

        Raises:
            CmdbPersonToJsonError: If the CmdbPerson could not be converted to a json compatible dict

        Returns:
            dict: Json compatible dict of the CmdbPerson values
        """
        try:
            return {
                'public_id': instance.get_public_id(),
                'display_name': instance.display_name,
                'first_name': instance.first_name,
                'last_name': instance.last_name,
                'phone_number': instance.phone_number,
                'email': instance.email,
                'groups': instance.groups,
            }
        except Exception as err:
            raise CmdbPersonToJsonError(err) from err
