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
Keys and defaults of the stored `auth` settings section

One source of truth for the three places that would otherwise spell these strings by hand: this model,
`AuthModule` (which normalises the section against the installed providers) and the auth routes
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

#: Minutes in a day, named so the token-lifetime default reads as the duration it is meant to be
MINUTES_PER_DAY: int = 24 * 60

#: `_id` of the settings document holding the auth section. `SettingsManager` addresses sections by
#: this value, so it is both the document id and the section name
AUTH_SETTINGS_ID: str = 'auth'

#: Default token lifetime **in minutes** - `TokenGenerator.get_expire_time` feeds it to
#: `timedelta(minutes=...)`, so this is one full day.
#:
#: Note 1400 (23h20m) is a typo for it rather than a deliberate value:
#: nothing referenced 23h20m and the surrounding code disagreed with it everywhere it was repeated.
#: Only the DEFAULT changed - an `auth` section that already stores a lifetime keeps it, because that
#: is an administrator's setting and not ours to rewrite
DEFAULT_TOKEN_LIFETIME: int = MINUTES_PER_DAY


class AuthSettingsKey(BaseStrEnum):
    """
    Keys of the stored `auth` settings document

    A **frontend-visible contract**: the Angular `AuthSettings` model declares exactly these four
    fields and its settings form posts all of them back, so a member renamed here rejects a payload
    the UI still sends
    """
    ID = '_id'
    PROVIDERS = 'providers'
    ENABLE_EXTERNAL = 'enable_external'
    TOKEN_LIFETIME = 'token_lifetime'


class ProviderEntryKey(BaseStrEnum):
    """
    Keys of one entry in `AuthSettingsKey.PROVIDERS`

    Each entry names an authentication provider class and carries that provider's own configuration
    sub-document. An entry missing CLASS_NAME is the malformed shape a historical `AuthModule` bug
    wrote; the reads in `CmdbAuthSettings` tolerate it rather than raising `KeyError`
    """
    CLASS_NAME = 'class_name'
    CONFIG = 'config'
