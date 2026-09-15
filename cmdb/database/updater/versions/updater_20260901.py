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
Database update 20260901: Port Connectivity groundwork

Two independent jobs, both for installations that already exist when the feature ships.

**The extendable options.** Port Connectivity backs four select fields with `CmdbExtendableOption`
lists - `PORT_STATUS`, `PORT_TYPE`, `PORT_SPEED` and `CABLE_TYPE`. Their predefined values are seeded
by `CollectionValidator` only when the extendable-option collection is *created*, which never happens
again on a running installation, so every existing database would start the feature with four empty
dropdowns. This migration inserts the ones that are missing.

Re-run safety here is provided by this module, not by the database: the missing set is computed
explicitly, from what the collection already holds. When this migration was written that was the
*only* protection, because `CmdbExtendableOption` declared a single NON-unique index on `option_type`
and a second run would have inserted 44 duplicates. `updater_20260902` has since made
`(option_type, value)` unique, so the explicit comparison is now also what keeps a re-run from
failing on a duplicate-key error instead of quietly doing nothing.

**The `uses_ports` backfill.** Step 1 added `CmdbType.uses_ports`, defaulting an absent key to False
in `from_data` and writing the key on the next save through the Cerberus schema - which is why it
needed no migration to be *correct*. This fills the key in on every type that has not been saved
since, so the whole collection carries the field before the feature goes live. It also removes a
sharp edge: a `{'uses_ports': False}` filter does not match a document where the key is absent, so
until this has run, code has to spell that query `{'$ne': True}`.

Both jobs are individually idempotent and the version is bumped only after both complete, so an
interrupted run simply starts over.
"""
from enum import Enum
from logging import Logger, getLogger
from typing import Any

from cmdb.database.mongo_database_manager import MongoDatabaseManager
from cmdb.database.updater.base_database_update import BaseDatabaseUpdate
from cmdb.database.predefined_data.port_data import get_default_port_extendable_options

from cmdb.models.extendable_option_model import CmdbExtendableOption, ExtendableOptionKey
from cmdb.models.type_model import CmdbType, TypeSchemaKey

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

def _as_stored_value(value: Any) -> str:
    """
    Returns the plain string a value has once it is in MongoDB

    The two sides of the comparison do not carry the same Python type: a predefined document holds
    the `OptionType` **member**, a stored one the plain string it was serialised to. `str()` is NOT
    the way to bridge that - `BaseStrEnum` extends `(str, Enum)` without overriding `__str__`, so
    `str(OptionType.CABLE_TYPE)` is `'OptionType.CABLE_TYPE'`, not `'CABLE_TYPE'`

    Args:
        value (Any): A value from either an in-memory or a stored option document

    Returns:
        str: The value as it is (or would be) stored
    """
    return value.value if isinstance(value, Enum) else str(value)


def _option_identity(option: dict[str, Any]) -> tuple[str, str]:
    """
    Reduces an extendable-option document to what makes it a duplicate

    The pair a customer would recognise as "the same entry": its value within its own list. The
    `predefined` flag is deliberately NOT part of the identity - a customer who added 'Cat8' by hand
    before upgrading must not end up with a second, predefined copy of it

    Args:
        option (dict[str, Any]): An extendable-option document, stored or predefined

    Returns:
        tuple[str, str]: The (option_type, value) identity pair, both as plain strings
    """
    return (
        _as_stored_value(option.get(ExtendableOptionKey.OPTION_TYPE, '')),
        _as_stored_value(option.get(ExtendableOptionKey.VALUE, '')),
    )


def get_missing_port_options(dbm: MongoDatabaseManager, db_name: str) -> list[dict[str, Any]]:
    """
    Returns the predefined Port Connectivity options the database does not carry yet

    The whole of the re-run safety of the option half. Read once, compare in memory, insert only the
    difference - so a second run finds nothing missing and inserts nothing, and a partially completed
    first run resumes exactly where it stopped

    Args:
        dbm (MongoDatabaseManager): Database manager to read the existing options with
        db_name (str): Name of the database to migrate

    Returns:
        list[dict[str, Any]]: The option documents still to be inserted, empty when none are
    """
    wanted: list[dict[str, Any]] = get_default_port_extendable_options()
    # Narrowed to this feature's four lists, so an ISMS installation's own options are not read
    owned_types: list[str] = sorted({_as_stored_value(option[ExtendableOptionKey.OPTION_TYPE])
                                     for option in wanted})

    # 'filter' and 'projection' are passed as keywords: find_all forwards **kwargs straight to the
    # cursor, so there is no 'criteria' parameter here (that name belongs to update_many)
    stored: list[dict[str, Any]] = dbm.find_all(
        CmdbExtendableOption.COLLECTION,
        db_name,
        filter={ExtendableOptionKey.OPTION_TYPE: {'$in': owned_types}},
        projection={ExtendableOptionKey.OPTION_TYPE: 1, ExtendableOptionKey.VALUE: 1, '_id': 0},
    )
    present: set[tuple[str, str]] = {_option_identity(option) for option in stored}

    return [option for option in wanted if _option_identity(option) not in present]


def insert_missing_port_options(dbm: MongoDatabaseManager, db_name: str) -> int:
    """
    Inserts every predefined Port Connectivity option the database is missing

    Args:
        dbm (MongoDatabaseManager): Database manager performing the inserts
        db_name (str): Name of the database to migrate

    Returns:
        int: How many options were inserted
    """
    missing: list[dict[str, Any]] = get_missing_port_options(dbm, db_name)

    for option in missing:
        dbm.insert(CmdbExtendableOption.COLLECTION, db_name, option)

    return len(missing)


def backfill_uses_ports(dbm: MongoDatabaseManager, db_name: str) -> int:
    """
    Sets 'uses_ports' to False on every CmdbType that does not carry the key

    Idempotent by construction: the '$exists: False' filter matches nothing once the field is
    present, so a second run reports zero modified. A type that already carries the flag - True or
    False - is never touched, so a port-bearing type set up between the release and this migration
    keeps its value

    Args:
        dbm (MongoDatabaseManager): Database manager performing the update
        db_name (str): Name of the database to migrate

    Returns:
        int: How many CmdbTypes were given the field
    """
    result = dbm.update_many(
        CmdbType.COLLECTION,
        db_name,
        criteria={TypeSchemaKey.USES_PORTS.value: {'$exists': False}},
        update={TypeSchemaKey.USES_PORTS.value: False},
    )

    return result.modified_count

# -------------------------------------------------------------------------------------------------------------------- #
# ---------------------------------------------- Update20260901 - CLASS ---------------------------------------------- #
# -------------------------------------------------------------------------------------------------------------------- #
class Update20260901(BaseDatabaseUpdate):
    """
    Seeds the Port Connectivity extendable options and backfills CmdbType.uses_ports

    Extends: BaseDatabaseUpdate
    """
    def creation_date(self) -> int:
        return 20260901


    def description(self) -> str:
        return "Seeds the Port Connectivity extendable options and backfills 'uses_ports' on all Types"


    def start_update(self) -> None:
        """
        Runs both jobs, then bumps the version

        Options first, then the type backfill; the two are independent, so the order only decides
        which one a crash leaves undone. Neither is destructive and both are idempotent, so an
        interrupted run is re-runnable from the top

        Raises:
            UpdaterException: If either job fails
        """
        try:
            inserted: int = insert_missing_port_options(self.dbm, self.db_name)

            if inserted:
                LOGGER.info("[updater_20260901] Inserted %s predefined Port Connectivity option(s)", inserted)

            backfilled: int = backfill_uses_ports(self.dbm, self.db_name)

            if backfilled:
                LOGGER.info("[updater_20260901] Backfilled 'uses_ports' on %s Type(s)", backfilled)

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(str(err)) from err
