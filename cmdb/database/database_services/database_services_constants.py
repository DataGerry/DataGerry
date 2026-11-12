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

Names the string / numeric literals the bootstrap and updater service modules share. Each enum / class
is scoped to a single owner: the Service Portal lookup, the database updater bookkeeping, and the
first-boot predefined-data seeding.
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


class UpdateAction(BaseStrEnum):
    """
    What bringing a database up to date does once its collections are validated
    (`database_bring_up.decide_update_action`)

    STAMP: no stamp and no data - the validator just built it at the current schema, so it is stamped, not migrated.
    MIGRATE: a stamp behind the newest migration, or data without a stamp - the migrations run.
    NONE: stamped at the newest version.
    """
    STAMP = 'stamp'
    MIGRATE = 'migrate'
    NONE = 'none'


class TenantSetupLock:
    """
    The lock a cloud login holds while it sets up a tenant database that carries no stamp
    (`cloud_user_helper.ensure_tenant_database`)

    Held as the tenant's own settings section SECTION. Two first logins of one tenant would otherwise both run the
    setup and one would fail on the other's seeded documents. The setup takes seconds, so a second login waits:
    ATTEMPTS times, RETRY_WAIT_SECONDS apart. TTL_SECONDS outlives gunicorn's 120 s worker timeout - a lock older
    than that has no running holder and is taken over
    """
    SECTION: str = 'tenant_setup_lock'
    LABEL: str = 'tenant setup lock'
    TTL_SECONDS: int = 180
    ATTEMPTS: int = 20
    RETRY_WAIT_SECONDS: float = 0.5


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
    """
    Document keys read or written while seeding predefined bootstrap data

    The generic ones the counters, the fixed groups and the section templates share; the 'General' report category is
    seeded with its own model's keys (``ReportCategoryKey``)
    """
    ID = '_id'
    PUBLIC_ID = 'public_id'
    NAME = 'name'


# Name of the predefined report category seeded on first boot
GENERAL_REPORT_CATEGORY_NAME: str = 'General'

# The boot's warning about stored objects without a public_id (missing or null) - every object list and search
# they appear in is refused until they are repaired
OBJECTS_WITHOUT_PUBLIC_ID_WARNING: str = (
    "Database '%s' holds %d object document(s) without a public_id. Every object list and search that reaches "
    "one is refused until it is repaired or removed - find them with {public_id: null} in the objects collection"
)
