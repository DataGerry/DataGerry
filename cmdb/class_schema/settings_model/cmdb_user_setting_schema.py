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
The schema of a CmdbUserSetting
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=R0801
def get_cmdb_user_setting_schema() -> dict[str, Any]:
    """
    Returns the CmdbUserSettingSchema

    Returns:
        dict: Schema of the CmdbUserSetting
    """
    return {
        'resource': {  # Identifier / name of the setting this document stores (unique together with user_id)
            'type': 'string',
            'required': True,
        },
        'user_id': {  # public_id of the CmdbUser the setting belongs to
            'type': 'integer',
            'required': True,
        },
        'payloads': {  # List of UserSettingPayload entries holding the actual stored setting values
            'type': 'list',
            'required': False,
        },
        'setting_type': {  # Scope of the setting; the stored value of a UserSettingType
            'type': 'string',
            'required': True,
        },
    }
