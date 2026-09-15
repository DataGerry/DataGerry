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
Implementation of UserSettingType
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

class UserSettingType(BaseStrEnum):
    """
    Scope a CmdbUserSetting declares for itself

    The three values are what the API accepts in `setting_type` (the document schema allows exactly
    these), and the value is stored as the string.

    **The backend does not act on the distinction.** Nothing server-side reads the scope to decide
    anything: `UserSettingsManager.get_user_settings` can filter by it, but no route passes a filter,
    so the scope is a label the frontend maintains for itself. The names describe the intent it was
    introduced with:

        - SERVER: meant for settings only the backend would consume
        - APPLICATION: frontend-only settings - what the Angular app writes (`UserSetting.USER_SETTING_TYPE`)
        - GLOBAL: meant for both
    """
    GLOBAL = 'GLOBAL'
    APPLICATION = 'APPLICATION'
    SERVER = 'SERVER'
