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
Implementation of CmdbUserSetting
"""
from logging import Logger, getLogger
from pymongo import IndexModel

from cmdb.models.settings_model.user_setting_payload import UserSettingPayload
from cmdb.models.settings_model.user_setting_type_enum import UserSettingType

from cmdb.errors.models.cmdb_user_setting import (
    CmdbUserSettingInitError,
    CmdbUserSettingInitFromDataError,
    CmdbUserSettingToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                CmdbUserSetting- CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class CmdbUserSetting:
    """
    Represents a user settings model.

    This class stores all user-specific settings. Each user has exactly 
    one corresponding document in the database collection.
    """

    COLLECTION = 'management.users.settings'
    MODEL = 'UserSetting'
    INDEX_KEYS = [
        {'keys': [('resource', 1), ('user_id', 1)],
         'name': 'resource-user',
         'unique': True}
    ]

    SCHEMA: dict = {
        'resource': {
            'type': 'string',
            'required': True
        },
        'user_id': {
            'type': 'integer',
            'required': True
        },
        'payloads': {
            'type': 'list',
            'required': False
        },
        'setting_type': {
            'type': 'string',
            'required': True
        }
    }


    def __init__(self, resource: str, user_id: int, payloads: list[UserSettingPayload], setting_type: UserSettingType):
        """
        Initialises a CmdbUserSetting

        Args:
            resource: (str): Identifier or name of the setting
            user_id (int): public_id of the CmdbUser
            payloads (list[UserSettingPayload]): List of setting payloads
            setting_type (UserSettingType): Scope type of the setting

        Raises:
            CmdbUserSettingInitError: If the CmdbUserSetting could not be initialised
        """
        try:
            self.resource = resource
            self.user_id = user_id
            self.payloads = payloads
            self.setting_type = setting_type
        except Exception as err:
            raise CmdbUserSettingInitError(err) from err

# --------------------------------------------------- CLASS METHODS -------------------------------------------------- #

    @classmethod
    def get_index_keys(cls) -> list[IndexModel]:
        """
        Retrieves the index keys for the CmdbUserSetting

        Returns:
            list[IndexModel]: A list of index models constructed from INDEX_KEYS
        """
        return [IndexModel(**index) for index in cls.INDEX_KEYS]


    @classmethod
    def from_data(cls, data: dict) -> "CmdbUserSetting":
        """
        Initialises a CmdbUserSetting from a dict

        Args:
            data (dict): Data with which the CmdbUserSetting should be initialised

        Raises:
            CmdbUserSettingInitFromDataError: If the initialisation with the given data fails

        Returns:
            CmdbUserSetting: CmdbUserSetting with the given data
        """
        try:
            payloads = [UserSettingPayload.from_data(payload) for payload in data.get('payloads', [])]

            return cls(
                resource=data.get('resource'),
                user_id=int(data.get('user_id')),
                payloads=payloads,
                setting_type=UserSettingType(data.get('setting_type'))
            )
        except Exception as err:
            raise CmdbUserSettingInitFromDataError(err) from err


    @classmethod
    def to_json(cls, instance: "CmdbUserSetting") -> dict:
        """
        Converts a CmdbUserSetting into a json compatible dict

        Args:
            instance (CmdbUserSetting): The CmdbUserSetting which should be converted

        Raises:
            CmdbUserSettingToJsonError: If the CmdbUserSetting could not be converted to a json compatible dict

        Returns:
            dict: Json compatible dict of the CmdbUserSetting values
        """
        try:
            return {
                'resource': instance.resource,
                'user_id': instance.user_id,
                'payloads': [UserSettingPayload.to_json(payload) for payload in instance.payloads],
                'setting_type': instance.setting_type.value
            }
        except Exception as err:
            raise CmdbUserSettingToJsonError(err) from err
