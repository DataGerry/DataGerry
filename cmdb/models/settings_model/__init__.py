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
Provides all CmdbUserSetting classes

One document per (CmdbUser, resource) - see `cmdb_user_setting.py` for what a setting is, who writes
them and why the read path is more forgiving than the write path.

`UserSettingPayload` used to live here as a wrapper around each stored payload entry: it took a dict
in `from_data` and handed the same dict back in `to_json`, nothing else referenced it, and its
`__slots__` declared a `name` it never assigned. It was removed on 2026-09-09 - the payload entries
are the client's own structures and travel as they are
"""
from .cmdb_user_setting import CmdbUserSetting
from .user_setting_constants import UserSettingKey
from .user_setting_type_enum import UserSettingType
from .user_setting_utils import normalize_user_setting_document
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'CmdbUserSetting',
    'UserSettingKey',
    'UserSettingType',
    'normalize_user_setting_document',
]
