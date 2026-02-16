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
Represents a CmdbObjectLink in DataGerry
"""
from datetime import datetime, timezone
from logging import Logger, getLogger

from cmdb.models.cmdb_dao import CmdbDAO

from cmdb.errors.models.cmdb_object_link import (
    CmdbObjectLinkInitError,
    CmdbObjectLinkInitFromDataError,
    CmdbObjectLinkToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                CmdbObjectLink - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class CmdbObjectLink(CmdbDAO):
    """
    Implementation of a CmdbObjectLink in DataGerry

    `Extends`: CmdbDAO
    """
    COLLECTION = "framework.links"

    def __init__(self, public_id: int, primary: int, secondary: int, creation_time: datetime = None) -> None:
        """
        Initializes a CmdbObjectLink

        Args:
            public_id (int): public_id of the CmdbObjectLink
            primary (int): public_id of the primary CmdbObject
            secondary (int): public_id of tje secondary CmdbObject
            creation_time (datetime, optional): The timestamp of creation. Defaults to current UTC time

        Raises:
            CmdbObjectLinkInitError: If an error occurs during initialization
        """
        try:
            if primary == secondary:
                raise ValueError(f"Primary ({primary}) and secondary ({secondary}) link IDs must not be the same!")

            self.primary = primary
            self.secondary = secondary
            self.creation_time = creation_time or datetime.now(timezone.utc)

            super().__init__(public_id = public_id)
        except Exception as err:
            raise CmdbObjectLinkInitError(err) from err


    def get_primary(self) -> int:
        """
        Returns the public_id of the primary CmdbObject of the CmdbObjectLink

        Returns:
            int: The public_id associated with the primary CmdbObject
        """
        return self.primary


    def get_secondary(self) -> int:
        """
        Returns the public_id of the secondary CmdbObject of the CmdbObjectLink

        Returns:
            int: The public_id associated with the secondary CmdbObject
        """
        return self.secondary


    @classmethod
    def from_data(cls, data: dict) -> "CmdbObjectLink":
        """
        Initialises a CmdbObjectLink from a dict

        Args:
            data (dict): Data with which the CmdbObjectLink should be initialised

        Raises:
            CmdbObjectLinkInitFromDataError: If the initialisation with the given data fails 

        Returns:
            CmdbObjectLink: CmdbObjectLink with the given data
        """
        try:
            return cls(
                public_id=data.get('public_id'),
                primary=int(data.get('primary')),
                secondary=int(data.get('secondary')),
                creation_time=data.get('creation_time', None),
            )
        except Exception as err:
            raise CmdbObjectLinkInitFromDataError(err) from err


    @classmethod
    def to_json(cls, instance: "CmdbObjectLink") -> dict:
        """
        Converts a CmdbObjectLink into a json compatible dict

        Args:
            instance (CmdbObjectLink): The CmdbObjectLink which should be converted

        Raises:
            CmdbObjectLinkToJsonError: If the CmdbObjectLink could not be converted to a json compatible dict
        Returns:
            dict: Json dict of the CmdbObjectLink values
        """
        try:
            return {
                'public_id': instance.public_id,
                'primary': instance.primary,
                'secondary': instance.secondary,
                'creation_time': instance.creation_time,
            }
        except Exception as err:
            raise CmdbObjectLinkToJsonError(err) from err
