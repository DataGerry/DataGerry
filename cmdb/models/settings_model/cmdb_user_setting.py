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
Implementation of CmdbUserSetting

**What a user setting is.** One document per (CmdbUser, resource): whatever a client wants to remember
for that user under that name. In practice the client is the Angular app, which stores its table
state, sidebar and dashboard layout here and writes on every interaction (`table.service.ts`), so this
is the most frequently written collection in the product and its payloads are opaque to the backend.

**Identity is `(user_id, resource)`, not a public_id.** That pair carries the unique compound index
below, and it is what every manager call and every route filters on. The collection nevertheless
*holds* a `public_id` - `GenericManager.insert_item` stamps one on every insert - and the
single-resource read answers it while the list read does not. That divergence, and whether a user
setting should have a public_id in its API shape at all (which is what migrating this model onto
`CmdbDAO` would settle), is discussion-backlog #218.

**The scope (`setting_type`) is a label the frontend maintains.** Nothing server-side branches on it;
see `UserSettingType`.

**Reading is deliberately more forgiving than writing.** The write path goes through this model and
through the schema, which allows exactly the three scope values. The read path does not build models
at all: `user_setting_utils.normalize_user_setting_document` answers the same four keys and reports a
document it cannot read, so one unreadable record no longer costs the user their whole settings list
"""
from typing import Any

from pymongo import IndexModel

from cmdb.models.settings_model.user_setting_constants import UserSettingKey
from cmdb.models.settings_model.user_setting_type_enum import UserSettingType
from cmdb.models.settings_model.user_setting_utils import (
    coerce_payloads,
    coerce_setting_type,
    coerce_user_id,
)

from cmdb.class_schema.settings_model.cmdb_user_setting_schema import get_cmdb_user_setting_schema

from cmdb.errors.models.cmdb_user_setting import (
    CmdbUserSettingInitError,
    CmdbUserSettingInitFromDataError,
    CmdbUserSettingToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

# -------------------------------------------------------------------------------------------------------------------- #
#                                                CmdbUserSetting - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class CmdbUserSetting:
    """
    One CmdbUser's stored settings for a single resource

    Not a `CmdbDAO` (see the module docstring): it exposes the `COLLECTION` + `get_index_keys()`
    contract `CollectionValidator` needs - it is registered in `user_management_constants.__COLLECTIONS__`,
    so the unique index below really is built - and nothing else of the DAO surface
    """

    COLLECTION = 'management.users.settings'

    # The identity of a setting, enforced by the database: one document per user and resource
    INDEX_KEYS: list[dict[str, Any]] = [
        {
            'keys': [(UserSettingKey.RESOURCE.value, 1), (UserSettingKey.USER_ID.value, 1)],
            'name': 'resource-user',
            'unique': True,
        }
    ]

    SCHEMA: dict = get_cmdb_user_setting_schema()


    def __init__(
            self,
            resource: str,
            user_id: int,
            payloads: list[dict[str, Any]] | None,
            setting_type: UserSettingType | str) -> None:
        """
        Initialises a CmdbUserSetting

        The one place a setting's values are normalised: the scope is resolved to a `UserSettingType`
        member (so `to_json` can always read its value), the owner id to an int, and an absent payload
        list to an empty one. A scope that is not one of the three values is refused here rather than
        stored and tripped over on the next read

        Args:
            resource (str): Identifier of what this setting belongs to, unique per user
            user_id (int): public_id of the owning CmdbUser
            payloads (list[dict[str, Any]] | None): The stored setting entries, opaque to the backend
            setting_type (UserSettingType | str): Scope of the setting, as a member or its stored value

        Raises:
            CmdbUserSettingInitError: If the given values are not usable as a CmdbUserSetting
        """
        try:
            self.resource: str = resource
            self.user_id: int = coerce_user_id(user_id)
            self.payloads: list[dict[str, Any]] = coerce_payloads(payloads)
            self.setting_type: UserSettingType = coerce_setting_type(setting_type)
        except ValueError as err:
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
    def from_data(cls, data: dict[str, Any]) -> "CmdbUserSetting":
        """
        Initialises a CmdbUserSetting from a dict

        The write path's entry point: the routes hand it a validated request body. `public_id` is not
        read, because it is not part of the model - an update therefore `$set`s the four keys and
        leaves the stamped id untouched

        Args:
            data (dict[str, Any]): Data with which the CmdbUserSetting should be initialised

        Raises:
            CmdbUserSettingInitFromDataError: If the initialisation with the given data fails

        Returns:
            CmdbUserSetting: CmdbUserSetting with the given data
        """
        try:
            return cls(
                resource=data[UserSettingKey.RESOURCE.value],
                user_id=data.get(UserSettingKey.USER_ID.value),
                payloads=data.get(UserSettingKey.PAYLOADS.value),
                setting_type=data.get(UserSettingKey.SETTING_TYPE.value),
            )
        except Exception as err:
            raise CmdbUserSettingInitFromDataError(err) from err


    @classmethod
    def to_json(cls, instance: "CmdbUserSetting") -> dict[str, Any]:
        """
        Converts a CmdbUserSetting into a json compatible dict

        The payload entries are handed back exactly as they were stored: they are the client's own
        structures and the backend attaches no meaning to them

        Args:
            instance (CmdbUserSetting): The CmdbUserSetting which should be converted

        Raises:
            CmdbUserSettingToJsonError: If the CmdbUserSetting could not be converted to a json
                compatible dict

        Returns:
            dict[str, Any]: Json compatible dict of the CmdbUserSetting values
        """
        try:
            if not isinstance(instance, cls):
                raise TypeError(f"Expected {cls.__name__} in 'to_json' got: {type(instance).__name__}!")

            return {
                UserSettingKey.RESOURCE.value: instance.resource,
                UserSettingKey.USER_ID.value: instance.user_id,
                UserSettingKey.PAYLOADS.value: instance.payloads,
                UserSettingKey.SETTING_TYPE.value: instance.setting_type.value,
            }
        except Exception as err:
            raise CmdbUserSettingToJsonError(err) from err
