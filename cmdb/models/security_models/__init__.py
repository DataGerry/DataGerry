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
Models of the security / authentication domain

Currently one entity: `CmdbAuthSettings`, the in-memory form of the stored `auth` settings section,
plus the keys and defaults that describe that document
"""
from .auth_settings import CmdbAuthSettings
from .auth_settings_constants import (
    AUTH_SETTINGS_ID,
    DEFAULT_TOKEN_LIFETIME,
    MINUTES_PER_DAY,
    AuthSettingsKey,
    ProviderEntryKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'AUTH_SETTINGS_ID',
    'DEFAULT_TOKEN_LIFETIME',
    'MINUTES_PER_DAY',
    'AuthSettingsKey',
    'CmdbAuthSettings',
    'ProviderEntryKey',
]
