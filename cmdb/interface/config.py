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
Flask config object classes consumed by `BaseCmdbApp` via `app.config.from_object`

Both app factories - `net_app.create_app` for the SPA host and `rest_api.create_rest_api` for the
API - pick a class from the `app_config` mapping with `config_name_for_mode(cmdb.__MODE__)` and feed
it to `app.config.from_object`, which copies the upper-case class attributes onto `app.config`.

The three subclasses differ only in the `DEBUG` and `TESTING` flags. Nothing here names a mount
point: the two apps are mounted at different prefixes by `DispatcherMiddleware`, so `APPLICATION_ROOT`
cannot be a shared value and each factory sets its own (the SPA host keeps Flask's default `/`; the
REST app sets `/rest/`). It used to live on `Config`, which meant the SPA host - mounted at `/` - was
configured with the API's mount
"""
# -------------------------------------------------------------------------------------------------------------------- #

#: `cmdb.__MODE__` value -> key in `app_config`. Any mode not named here is production
MODE_CONFIG_NAMES: dict[str, str] = {
    'DEBUG': 'development',
    'TESTING': 'testing',
}

#: The key used for every mode `MODE_CONFIG_NAMES` does not name
DEFAULT_CONFIG_NAME: str = 'production'


def config_name_for_mode(mode: str) -> str:
    """
    Maps a `cmdb.__MODE__` value onto its `app_config` key

    Lives here so both app factories select their config the same way. They used to spell the
    mapping out separately, and they disagreed: the SPA host had no `TESTING` branch, which is why
    `TestingConfig` was reachable from the REST app but dead from `create_app`

    Args:
        mode (str): The process-wide mode, i.e. `cmdb.__MODE__`

    Returns:
        str: Key into `app_config`; DEFAULT_CONFIG_NAME for any unrecognised mode
    """
    return MODE_CONFIG_NAMES.get(mode, DEFAULT_CONFIG_NAME)


class Config:
    """
    Base Flask config class — production defaults shared by every variant

    `from_object` only copies upper-case attributes onto `app.config`, so the fields here become
    Flask config keys. Deliberately carries no `APPLICATION_ROOT`: see the module docstring
    """
    TESTING = False
    DEBUG = False


class DevelopmentConfig(Config):
    """
    Selected when `cmdb.__MODE__ == 'DEBUG'`; turns Flask's debug flag on

    Setting `DEBUG = True` causes Flask to surface the interactive traceback page on
    exceptions, auto-reload on file change in a `flask run` context, and skip some
    response sanitisation
    """
    DEBUG = True


class ProductionConfig(Config):
    """
    Default fallback selected for any `cmdb.__MODE__` other than `'DEBUG'`

    Inherits the production defaults (`DEBUG = False`, `TESTING = False`) from `Config`
    without overriding anything
    """


class TestingConfig(Config):
    """
    Selected when `cmdb.__MODE__ == 'TESTING'`, by both app factories

    Setting `TESTING = True` switches Flask to propagating exceptions to the test client instead of
    converting them to 500 responses
    """
    DEBUG = True
    TESTING = True


#: Config-name → Config-class lookup. Both app factories index it with
#: `config_name_for_mode(cmdb.__MODE__)`, so every entry here is reachable from both
app_config: dict[str, type[Config]] = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig
}
