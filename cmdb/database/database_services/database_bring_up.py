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
Bringing one database to the current schema: validate its collections, then stamp or migrate it

**"New" is decided by the stamp, never by whether the database exists.** A database appears with its first write, so
a first setup that fails halfway - after the validator created a collection or the keys, before the stamp - leaves a
database that exists and carries no stamp. Decided by existence, the next run took it for an old database and replayed
every migration from the baseline. Decided by the stamp and the data, it is stamped: no stamp and no types or objects
means nothing the migrations could transform exists - the validator has just built it at the current schema.

The validator runs first in every case, so the stamp is only ever written for a database the validation completed.
Used by the on-premise boot, the cloud tenant loop at startup and the cloud login of a tenant without a stamp
(`cloud_user_helper.ensure_tenant_database`)
"""
from logging import Logger, getLogger

from cmdb.database.mongo_database_manager import MongoDatabaseManager
from cmdb.database.database_services.collection_validator import CollectionValidator
from cmdb.database.database_services.database_updater import DatabaseUpdater
from cmdb.database.database_services.database_services_constants import UpdateAction
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# What holds data a migration could transform: a database with neither has nothing to migrate
DATA_COLLECTIONS: tuple[str, ...] = (CmdbType.COLLECTION, CmdbObject.COLLECTION)


def decide_update_action(stored_version: int | None, holds_data: bool, highest_version: int) -> UpdateAction:
    """
    What a validated database needs: a stamp, the migrations, or nothing

    Args:
        stored_version (int | None): The stamp, None when the database carries none
        holds_data (bool): Whether it holds any type or object
        highest_version (int): The newest registered migration

    Returns:
        UpdateAction: STAMP without a stamp and without data, MIGRATE without a stamp but with data or with a stamp
            behind the newest migration, NONE when stamped at it
    """
    if stored_version is None:
        return UpdateAction.MIGRATE if holds_data else UpdateAction.STAMP

    return UpdateAction.MIGRATE if stored_version < highest_version else UpdateAction.NONE


def database_holds_data(dbm: MongoDatabaseManager, db_name: str) -> bool:
    """
    Whether the database holds any type or object - an existence check per collection, never a full count

    Args:
        dbm (MongoDatabaseManager): Manager owning the MongoDB connection
        db_name (str): The database to look in

    Returns:
        bool: True when at least one type or object is stored
    """
    return any(dbm.count(collection, db_name, {}, limit=1) for collection in DATA_COLLECTIONS)


def bring_database_up_to_date(dbm: MongoDatabaseManager, db_name: str, on_premise: bool = False) -> UpdateAction:
    """
    Brings one database to the current schema: validate the collections, then stamp or migrate

    The validator builds a missing database from the current models and heals an existing one, on every pass. What
    follows is decided by the stamp and the data (`decide_update_action`), read after the validation: a database
    without a stamp and without data is at the current schema and is stamped; data without a stamp, or a stamp behind
    the newest migration, is migrated; a current stamp needs nothing. A validation that fails raises before any stamp
    is written, so the next run decides again

    Args:
        dbm (MongoDatabaseManager): Manager owning the MongoDB connection
        db_name (str): Name of the database to bring up to date
        on_premise (bool): Passed to CollectionValidator, where it gates the key generation and the default admin
            user - True for the on-premise boot only. Defaults to False

    Returns:
        UpdateAction: What was done after the validation
    """
    CollectionValidator(db_name, dbm, on_premise=on_premise).validate_collections()

    database_updater = DatabaseUpdater(dbm, db_name)
    highest_version: int = database_updater.get_highest_update_version()
    action: UpdateAction = decide_update_action(
        database_updater.read_stored_update_version(), database_holds_data(dbm, db_name), highest_version,
    )

    if action == UpdateAction.STAMP:
        database_updater.set_update_version(highest_version)
    elif action == UpdateAction.MIGRATE:
        database_updater.run_updates()

    LOGGER.info("[bring_database_up_to_date] %s: %s", db_name, action.value)

    return action
