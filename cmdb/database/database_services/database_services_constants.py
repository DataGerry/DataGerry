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
Constants for the cmdb.database.database_services package

Replaces the bare string / numeric literals previously scattered across the bootstrap and updater
service modules. Each enum / class is scoped to a single owner: the Service Portal lookup, the
database updater bookkeeping, and the first-boot predefined-data seeding.
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #


class ServicePortalEnv:
    """Environment-variable names used to reach the DataGerry Service Portal"""
    ACCESS_TOKEN: str = 'X-ACCESS-TOKEN'
    BASE_URL: str = 'DG_SP_BASE_URL'


class ServicePortal:
    """
    Request constants for the Service Portal database-name lookup

    DB_NAMES_ENDPOINT is appended to the configured base URL; REQUEST_TIMEOUT_SECONDS bounds the
    call; ACCESS_TOKEN_HEADER is the auth header name; RESPONSE_MESSAGE_KEY is the error-body field
    read for a human-readable message; LOCAL_MODE_DB_NAMES is the fixed list returned in local mode
    """
    DB_NAMES_ENDPOINT: str = '/datagerry/database/all/names'
    REQUEST_TIMEOUT_SECONDS: int = 3
    ACCESS_TOKEN_HEADER: str = 'x-access-token'
    RESPONSE_MESSAGE_KEY: str = 'message'
    LOCAL_MODE_DB_NAMES: list[str] = ['testdb1', 'testdb2', 'testdb3']


class UpdaterSetting(BaseStrEnum):
    """
    Keys of the 'updater' settings document tracking the applied database version

    SECTION is both the settings section name and the document's _id value; ID and VERSION are the
    stored document fields
    """
    SECTION = 'updater'
    ID = '_id'
    VERSION = 'version'


class Updater:
    """
    Runtime constants for applying database migrations

    PROCESS_BAR_LABEL is the progress label; THROTTLE_SECONDS is the delay between migrations to
    avoid throttling; CLASS_PATH_TEMPLATE is the dotted path of an updater class, formatted with the
    integer version (e.g. updater_20250619.Update20250619)
    """
    PROCESS_BAR_LABEL: str = 'Process'
    THROTTLE_SECONDS: float = 0.25
    CLASS_PATH_TEMPLATE: str = 'cmdb.database.updater.versions.updater_{version}.Update{version}'


class BootstrapDocumentKey(BaseStrEnum):
    """Document keys read or written while seeding predefined bootstrap data"""
    ID = '_id'
    NAME = 'name'
    PREDEFINED = 'predefined'


# Name of the predefined report category seeded on first boot
GENERAL_REPORT_CATEGORY_NAME: str = 'General'
