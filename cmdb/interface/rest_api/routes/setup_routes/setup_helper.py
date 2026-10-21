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
Helper functions for the setup REST routes

``assert_tenant_database`` decides whether a subscription teardown may drop the database it names: only a DataGerry
tenant database - never MongoDB's own databases, the shared user cache or the process's own database, and never a
database DataGerry did not create. The Service Portal tears a tenant down with its own account, not the tenant's, so
there is no subscription list naming the database to check it against; what the database IS decides instead

``read_target_emails`` turns the ``email`` value of a cache-eviction request into the list of cache keys to remove:
the shape checked (a non-empty string, or a non-empty list of non-empty strings) and every address spelled the way
every cloud entry point spells it before it reaches the cache (``normalize_login_email``: stripped, lower-cased). An
eviction that matched the address only as sent would leave the entry a differently-cased teardown request names in
place, and still answer success
"""
from typing import Any

from logging import Logger, getLogger

from flask import abort

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_constants import DG_CACHE_DB
from cmdb.models.type_model import CmdbType
from cmdb.security.auth.login_name import normalize_login_email
from cmdb.interface.rest_api.routes.setup_routes.setup_constants import (
    MONGODB_SYSTEM_DATABASES,
    SetupMessage,
    SetupRequestKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)


def read_target_emails(payload: Any) -> list[str]:
    """
    Reads the cache keys a cache-eviction request names

    Args:
        payload (Any): The parsed JSON body - None when the body is not JSON

    Raises:
        HTTPException: 400 when the body is not a JSON object, carries no ``email``, its value is neither a string
            nor a list, names no address, or holds an entry that is not a non-empty string (the message names the
            positions)

    Returns:
        list[str]: The normalised addresses, each once, in the order sent
    """
    if not isinstance(payload, dict):
        abort(400, SetupMessage.NO_PAYLOAD.value)

    if SetupRequestKey.EMAIL not in payload:
        abort(400, SetupMessage.NO_EMAIL.value)

    value: Any = payload[SetupRequestKey.EMAIL]

    if not isinstance(value, (str, list)):
        abort(400, SetupMessage.EMAIL_TYPE.value)

    entries: list[Any] = [value] if isinstance(value, str) else value

    if not entries:
        abort(400, SetupMessage.EMPTY_EMAIL.value)

    unusable: list[int] = [
        position for position, entry in enumerate(entries)
        if not isinstance(entry, str) or not normalize_login_email(entry)
    ]

    if unusable:
        if isinstance(value, str):
            abort(400, SetupMessage.EMPTY_EMAIL.value)

        abort(400, SetupMessage.EMAIL_ITEMS.value.format(positions=', '.join(str(p) for p in unusable)))

    return list(dict.fromkeys(normalize_login_email(entry) for entry in entries))


def assert_tenant_database(dbm: MongoDatabaseManager, database: str) -> None:
    """
    Refuses a subscription teardown that names anything but an existing DataGerry tenant database

    Checked in this order, each a 400 that names the database (and a warning in the log):

    * **a reserved name** - MongoDB's own ``admin`` / ``config`` / ``local``, the shared user cache (``DG_CACHE_DB``,
      every tenant's cached logins) and the process's own database (``dbm.db_name``)
    * **an unknown name** - nothing to drop
    * **a database DataGerry did not create** - every tenant database is made by ``init_db_routine``, whose
      ``CollectionValidator`` creates the framework collections first; one without ``framework.types`` is some other
      application's. A half-provisioned tenant already has it, so the portal can still clean one up

    The shape check and the drop are two calls; a database would have to gain ``framework.types`` in between to slip
    through, and only tenant creation makes that collection

    Args:
        dbm (MongoDatabaseManager): The process-wide database manager
        database (str): The database the teardown names

    Raises:
        HTTPException: 400 for a reserved, unknown or non-tenant database
    """
    if database in MONGODB_SYSTEM_DATABASES or database in (DG_CACHE_DB, dbm.db_name):
        LOGGER.warning("[assert_tenant_database] Refused to drop the reserved database '%s'", database)
        abort(400, SetupMessage.RESERVED_DATABASE.value.format(database=database))

    if not dbm.check_database_exists(database):
        abort(400, SetupMessage.UNKNOWN_DATABASE.value.format(database=database))

    if not dbm.connector.get_database(database).list_collection_names(filter={'name': CmdbType.COLLECTION}):
        LOGGER.warning("[assert_tenant_database] Refused to drop '%s', which is no DataGerry tenant database", database)
        abort(400, SetupMessage.NOT_A_TENANT_DATABASE.value.format(database=database))
