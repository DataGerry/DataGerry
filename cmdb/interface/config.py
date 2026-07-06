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

`cmdb.interface.net_app.create_app` picks one of these classes from the `app_config` mapping
based on `cmdb.__MODE__` and feeds it to `app.config.from_object`, which copies the
upper-case class attributes onto `app.config`. The three subclasses differ only in the
`DEBUG` and `TESTING` flags; `APPLICATION_ROOT` is inherited from `Config` and is the same
for every variant
"""
# -------------------------------------------------------------------------------------------------------------------- #

class Config:
    """
    Base Flask config class — production defaults shared by every variant

    `from_object` only copies upper-case attributes onto `app.config`, so the fields here
    become Flask config keys. `APPLICATION_ROOT = '/rest/'` is inherited unchanged by every
    subclass; see the audit notes for why this is currently questionable when the same
    config is applied to the SPA host app
    """
    TESTING = False
    DEBUG = False
    APPLICATION_ROOT = '/rest/'


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
    Test-only variant — registered in `app_config` but never selected by `create_app`

    Setting `TESTING = True` switches Flask to propagating exceptions to the test client
    instead of converting them to 500 responses. Currently unreachable from the standard
    bootstrap; would be the right target if a test harness ever wants a non-production
    Flask config
    """
    DEBUG = True
    TESTING = True


#: Mode-name → Config-class lookup consumed by `net_app.create_app`. `'development'` is
#: picked when `cmdb.__MODE__ == 'DEBUG'`; every other mode falls through to
#: `'production'`. The `'testing'` entry exists for completeness but has no caller today
app_config: dict[str, type[Config]] = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig
}
