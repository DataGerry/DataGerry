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
Migrates a transfer file from an older version to the importing database's version - with the real updaters

The documents of a file carry the shape the exporting database stored them in. Rather than re-implementing every
updater as a document transform, the file is written into a temporary database, the updaters newer than the file run
against it exactly as they run against a real database, and the migrated documents are read back:

    1. a database name is drawn - `STAGING_DATABASE_PREFIX` + 32 hex characters - and refused if it exists already
       (a fresh one is drawn, `MAX_STAGING_NAME_ATTEMPTS` times at most)
    2. every component's documents go into their collection there, and the file's version into its `updater` section
    3. every registered updater newer than the file and up to the importing version runs, in order
    4. the components' documents are read back; the file keeps its counters and carries the importing version now
    5. the temporary database is dropped - always, whatever failed

The updaters are re-run safe and run on a database holding nothing but these collections. A staging database left
behind by a killed process is not swept away by a later import: in cloud mode another tenant's import may be using
one at that moment. Its name says what it is, and the import logs it
"""
from copy import deepcopy
from logging import Logger, getLogger
from typing import Any, Callable, Collection, Sequence
from uuid import uuid4

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_services.database_services_constants import Updater, UpdaterSetting
from cmdb.database.database_services.database_updater import DatabaseUpdater
from cmdb.manager import SettingsManager
from cmdb.utils import load_class
from cmdb.framework.configuration_transfer.configuration_transfer_constants import (
    MAX_STAGING_NAME_ATTEMPTS,
    NO_STAGING_NAME,
    STAGING_DATABASE_PREFIX,
    TransferFileKey,
    TransferInformationKey,
    TransferSectionKey,
)
from cmdb.framework.configuration_transfer.transfer_component import PUBLIC_ID_KEY, TransferComponent
from cmdb.framework.configuration_transfer.transfer_file import build_component_section, count_component_items
from cmdb.errors.configuration_transfer import StagingDatabaseError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

MONGO_ID_KEY: str = '_id'


def draw_staging_name(existing: Collection[str], draw: Callable[[], str] = lambda: uuid4().hex) -> str:
    """
    Draws a name for the temporary database that no database carries yet

    Args:
        existing (Collection[str]): The names of the databases that exist
        draw (Callable[[], str]): Draws the random part of a name - 32 hex characters

    Raises:
        StagingDatabaseError: When every attempt drew a name that exists

    Returns:
        str: The name
    """
    for _ in range(MAX_STAGING_NAME_ATTEMPTS):
        name: str = f'{STAGING_DATABASE_PREFIX}{draw()}'

        if name not in existing:
            return name

    raise StagingDatabaseError(NO_STAGING_NAME.format(attempts=MAX_STAGING_NAME_ATTEMPTS))


def updater_versions_between(registered: Sequence[int], file_version: int, target_version: int) -> list[int]:
    """
    The updaters a file of one version needs to reach another, in the order they run

    Args:
        registered (Sequence[int]): Every registered updater version
        file_version (int): The file's version - its own updaters already ran on the exporting database
        target_version (int): The importing database's version

    Returns:
        list[int]: Every registered version newer than the file's and not newer than the target's, ascending
    """
    return sorted(version for version in registered if file_version < version <= target_version)


def run_updaters(dbm: MongoDatabaseManager, db_name: str, versions: Sequence[int]) -> None:
    """
    Runs the given updaters against one database, in the order given

    The updater classes are loaded the way `DatabaseUpdater.run_updates` loads them; the loop is its own so the
    request is not slowed by the start-up loop's progress bar and pause between updaters

    Args:
        dbm (MongoDatabaseManager): The database manager
        db_name (str): The database the updaters run against
        versions (Sequence[int]): The updater versions to run

    Raises:
        Exception: Whatever an updater raises - the migration fails with it
    """
    for version in versions:
        updater_class: type = load_class(Updater.CLASS_PATH_TEMPLATE.format(version=version))
        updater_class(dbm, db_name).start_update()


def seed_staging_database(dbm: MongoDatabaseManager, db_name: str, components: Sequence[type[TransferComponent]],
                          transfer_file: dict[str, Any]) -> None:
    """
    Writes a file's documents into the temporary database and records the file's version there

    Args:
        dbm (MongoDatabaseManager): The database manager
        db_name (str): The temporary database
        components (Sequence[type[TransferComponent]]): The registered components
        transfer_file (dict[str, Any]): The file, its envelope already judged
    """
    sections: dict[str, Any] = transfer_file[TransferFileKey.COMPONENTS.value]

    for component in components:
        items: list[dict[str, Any]] = sections[component.NAME.value][TransferSectionKey.ITEMS.value]

        if items:
            dbm.get_collection(component.COLLECTION, db_name).insert_many(deepcopy(items))

    SettingsManager(dbm, db_name).write(UpdaterSetting.SECTION.value, {
        UpdaterSetting.ID.value: UpdaterSetting.SECTION.value,
        UpdaterSetting.VERSION.value: transfer_file[TransferFileKey.DB_VERSION.value],
    })


def read_migrated_file(dbm: MongoDatabaseManager, db_name: str, components: Sequence[type[TransferComponent]],
                       transfer_file: dict[str, Any], target_version: int) -> dict[str, Any]:
    """
    Reads the migrated documents back into a transfer file of the importing version

    The counters are the file's: the updaters reshape documents, they hand out no ids. The `information` counts are
    counted again, as an updater may remove or add entries

    Args:
        dbm (MongoDatabaseManager): The database manager
        db_name (str): The temporary database
        components (Sequence[type[TransferComponent]]): The registered components
        transfer_file (dict[str, Any]): The original file
        target_version (int): The importing database's version

    Returns:
        dict[str, Any]: The migrated file - the original envelope, the importing version, the migrated documents and
                        their counts
    """
    sections: dict[str, Any] = transfer_file[TransferFileKey.COMPONENTS.value]
    migrated: dict[str, Any] = {}

    for component in components:
        items: list[dict[str, Any]] = list(dbm.get_collection(component.COLLECTION, db_name).find(
            {}, {MONGO_ID_KEY: 0}, sort=[(PUBLIC_ID_KEY, 1)],
        ))
        migrated[component.NAME.value] = build_component_section(
            sections[component.NAME.value][TransferSectionKey.COUNTER.value], items,
        )

    information: dict[str, Any] = {**transfer_file[TransferFileKey.INFORMATION.value],
                                   TransferInformationKey.COUNTS.value: count_component_items(migrated)}

    return {**transfer_file, TransferFileKey.DB_VERSION.value: target_version,
            TransferFileKey.INFORMATION.value: information, TransferFileKey.COMPONENTS.value: migrated}


def migrate_transfer_file(dbm: MongoDatabaseManager, transfer_file: dict[str, Any], target_version: int,
                          components: Sequence[type[TransferComponent]]) -> dict[str, Any]:
    """
    Brings a file of an older version to the importing version; a file of the same version is answered as it is

    Args:
        dbm (MongoDatabaseManager): The database manager
        transfer_file (dict[str, Any]): The file - its envelope judged, its version not newer than the target's
        target_version (int): The importing database's version
        components (Sequence[type[TransferComponent]]): The registered components

    Raises:
        StagingDatabaseError: When no unused name for the temporary database was found
        Exception: Whatever an updater or a database write raised - the temporary database is dropped either way

    Returns:
        dict[str, Any]: The file in the importing version's shape
    """
    file_version: int = transfer_file[TransferFileKey.DB_VERSION.value]

    if file_version == target_version:
        return transfer_file

    db_name: str = draw_staging_name(set(dbm.connector.client.list_database_names()))
    LOGGER.info("[migrate_transfer_file] Migrating a version %s file to %s in '%s'", file_version, target_version,
                db_name)

    try:
        seed_staging_database(dbm, db_name, components, transfer_file)
        registered: list[int] = DatabaseUpdater(dbm, db_name).get_updater_versions()
        run_updaters(dbm, db_name, updater_versions_between(registered, file_version, target_version))

        return read_migrated_file(dbm, db_name, components, transfer_file, target_version)
    finally:
        dbm.connector.client.drop_database(db_name)
