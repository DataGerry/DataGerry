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
Validation schema for CmdbUserSetting

CmdbUserSetting holds one CmdbUser's settings for a single resource - one document per
(user_id, resource), in collection ``management.users.settings``.

This module is the single source of the document's Cerberus validation schema, consumed as
CmdbUserSetting.SCHEMA by the POST and the PUT/PATCH route.

**``setting_type`` is constrained to the three UserSettingType values** (added 2026-09-09). It was
typed as a plain string, so any string was accepted on write while the read resolved it to a
UserSettingType member - one stored value outside the enum therefore made the whole settings list of
that user unreadable. The allowed list is what closes that at the door.
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=R0801
def get_cmdb_user_setting_schema() -> dict[str, Any]:
    """
    Builds the Cerberus validation schema for a CmdbUserSetting document

    Returns:
        dict: Field name to Cerberus rule mapping, consumed as CmdbUserSetting.SCHEMA
    """
    # Imported inside the builder on purpose: the model imports this module for its SCHEMA, so a
    # module-level import of the model package would close the cycle (class_schema convention)
    # pylint: disable=import-outside-toplevel
    from cmdb.models.settings_model.user_setting_constants import UserSettingKey
    from cmdb.models.settings_model.user_setting_type_enum import UserSettingType

    return {
        # Identifier / name of what this setting belongs to (unique together with user_id)
        UserSettingKey.RESOURCE.value: {
            'type': 'string',
            'required': True,
        },
        # public_id of the CmdbUser the setting belongs to; pinned to the URL by both write routes
        UserSettingKey.USER_ID.value: {
            'type': 'integer',
            'required': True,
        },
        # The stored setting entries. Their content is the client's own structure and is deliberately
        # not described further - only that each entry is an object, so a list of scalars is refused
        UserSettingKey.PAYLOADS.value: {
            'type': 'list',
            'required': False,
            'schema': {'type': 'dict'},
        },
        # Scope of the setting; exactly the three values a UserSettingType can be stored as
        UserSettingKey.SETTING_TYPE.value: {
            'type': 'string',
            'required': True,
            'allowed': [setting_type.value for setting_type in UserSettingType],
        },
    }
