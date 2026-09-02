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
Database update 20260902: makes a CmdbExtendableOption's value unique within its OptionType

A CmdbExtendableOption is one selectable entry of one dropdown, so `(option_type, value)` is its
identity - two options with the same pair are the same entry listed twice. Nothing enforced that:
the collection declared a single NON-unique index on `option_type`. The REST create/update routes do
check (`extendable_options_helper.option_value_exists`), but that check is a read followed by a
write, so it cannot stop two concurrent requests, the ISMS CSV importer resolves values through its
own read-then-insert without the check at all, and installations older than 2026-07-06 had no check
whatsoever. This migration de-duplicates whatever accumulated and rebuilds the index as unique.

The rebuild is needed because index reconciliation is name-based and purely additive (see
`CollectionValidator.ensure_indexes`): the new declaration in `CmdbExtendableOption.INDEX_KEYS`
alone would only reach databases whose collection is created from scratch, and would leave every
existing deployment silently non-unique.

**De-duplicating an option is not just deleting a document.** An option's public_id is referenced
from other collections - ISMS threats, vulnerabilities, risks, control measures, risk assessments,
control-measure assignments and object groups. Every reference to a discarded duplicate is therefore
moved onto the keeper first, through the shared map in `cmdb.framework.extendable_options` (the same
map the pre-delete in-use guard uses, so the two cannot disagree about where options are referenced).

**Which duplicate is kept.** A predefined option wins, so a re-seed cannot recreate it; otherwise
the lowest public_id wins, as the oldest and the one most likely to be referenced already.

**Case sensitivity.** The new index is case- and whitespace-sensitive, exactly like the route guard:
'CAT6', 'cat6' and ' CAT6' stay three separate options. Anything else would have rejected values
that existing databases legitimately hold.

Re-run safe throughout: the duplicate groups are recomputed from the current collection state, the
reference re-pointing is idempotent in both its scalar and its array form, an index that is already
unique is left alone, and the version is bumped only after both halves complete.
"""
from logging import Logger, getLogger
from typing import Any

from pymongo import IndexModel

from cmdb.database.mongo_database_manager import MongoDatabaseManager
from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.framework.extendable_options import repoint_option_references

from cmdb.models.extendable_option_model import (
    CmdbExtendableOption,
    ExtendableOptionKey,
    OPTION_TYPE_VALUE_INDEX_NAME,
    LEGACY_OPTION_TYPE_INDEX_NAME,
)

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# Aggregation output keys of the duplicate-group pipeline
GROUP_IDENTITY_KEY: str = '_id'
GROUP_OPTIONS_KEY: str = 'options'

# The 'unique' flag is only present in index_information() output when the index actually is unique
INDEX_UNIQUE_KEY: str = 'unique'

# -------------------------------------------------------------------------------------------------------------------- #

def find_duplicate_option_groups(dbm: MongoDatabaseManager, db_name: str) -> list[dict[str, Any]]:
    """
    Finds every (option_type, value) pair that more than one CmdbExtendableOption carries

    Groups the whole collection by the identity pair and keeps only the groups holding at least two
    documents, carrying each member's public_id and predefined flag so a keeper can be chosen without
    a second read. Documents missing 'value' or 'option_type' group under null, which is deliberate:
    a unique index treats every missing value as the same null, so those collide too and have to be
    resolved here as well

    Args:
        dbm (MongoDatabaseManager): Database manager used for the aggregation
        db_name (str): Name of the database to inspect

    Returns:
        list[dict[str, Any]]: One entry per duplicated identity, each with the group's '_id' (the
            option_type/value pair) and 'options' (a list of {'public_id', 'predefined'} dicts)
    """
    pipeline: list[dict[str, Any]] = [
        {
            '$group': {
                GROUP_IDENTITY_KEY: {
                    ExtendableOptionKey.OPTION_TYPE.value: f'${ExtendableOptionKey.OPTION_TYPE.value}',
                    ExtendableOptionKey.VALUE.value: f'${ExtendableOptionKey.VALUE.value}',
                },
                GROUP_OPTIONS_KEY: {
                    '$push': {
                        ExtendableOptionKey.PUBLIC_ID.value: f'${ExtendableOptionKey.PUBLIC_ID.value}',
                        ExtendableOptionKey.PREDEFINED.value: f'${ExtendableOptionKey.PREDEFINED.value}',
                    },
                },
            },
        },
        {
            '$match': {f'{GROUP_OPTIONS_KEY}.1': {'$exists': True}},
        },
    ]

    return list(dbm.aggregate(CmdbExtendableOption.COLLECTION, db_name, pipeline))


def select_keeper(options: list[dict[str, Any]]) -> int:
    """
    Chooses which of several identical CmdbExtendableOptions survives

    A predefined option wins: it is undeletable through the API and would be recreated by the
    predefined-data seeding anyway, so discarding it would only bring the duplicate back. Among
    equals the lowest public_id wins - the oldest entry, and the one existing documents are most
    likely to reference already

    Args:
        options (list[dict[str, Any]]): The duplicate group's members, each with 'public_id' and
            'predefined'

    Returns:
        int: public_id of the option to keep
    """
    predefined_ids: list[int] = [
        option[ExtendableOptionKey.PUBLIC_ID.value] for option in options
        if option.get(ExtendableOptionKey.PREDEFINED.value) is True
    ]

    if predefined_ids:
        return min(predefined_ids)

    return min(option[ExtendableOptionKey.PUBLIC_ID.value] for option in options)


def deduplicate_options(dbm: MongoDatabaseManager, db_name: str) -> int:
    """
    Removes duplicate CmdbExtendableOptions so that a value appears at most once per OptionType

    For each duplicate group the keeper is chosen, every reference to the discarded members is moved
    onto it, and only then are they deleted - in that order, so an interruption leaves references
    pointing at an option that still exists.

    Re-run safe: the groups are recomputed from the current collection state on every call, so a
    completed run finds nothing to do and an interrupted one resumes where it stopped

    Args:
        dbm (MongoDatabaseManager): Database manager used for the reads and writes
        db_name (str): Name of the database to clean up

    Returns:
        int: Number of duplicate options that were removed
    """
    groups: list[dict[str, Any]] = find_duplicate_option_groups(dbm, db_name)

    if not groups:
        return 0

    removed: int = 0

    for group in groups:
        identity: dict[str, Any] = group[GROUP_IDENTITY_KEY]
        options: list[dict[str, Any]] = group[GROUP_OPTIONS_KEY]
        option_type: Any = identity.get(ExtendableOptionKey.OPTION_TYPE.value)

        keeper_id: int = select_keeper(options)
        dropped_ids: list[int] = [
            option[ExtendableOptionKey.PUBLIC_ID.value]
            for option in options
            if option[ExtendableOptionKey.PUBLIC_ID.value] != keeper_id
        ]

        LOGGER.warning(
            "[updater_20260902] %s '%s' existed %s times - keeping ID:%s, removing %s",
            option_type, identity.get(ExtendableOptionKey.VALUE.value), len(options), keeper_id, dropped_ids,
        )

        for dropped_id in dropped_ids:
            repoint_option_references(dbm, db_name, option_type, dropped_id, keeper_id)

        dbm.delete_many_raw(
            CmdbExtendableOption.COLLECTION,
            db_name,
            {ExtendableOptionKey.PUBLIC_ID.value: {'$in': dropped_ids}},
        )

        removed += len(dropped_ids)

    return removed


def rebuild_value_index(dbm: MongoDatabaseManager, db_name: str) -> bool:
    """
    Builds the unique (option_type, value) index and drops the superseded 'option_type' one

    The old index is dropped rather than kept because the new one has option_type as its prefix and
    therefore already serves every query the old one served. An index of the target name that is
    already unique is left alone, which makes the call idempotent; one that exists but is NOT unique
    (a name collision from an older declaration) is dropped first, since MongoDB refuses to recreate
    an index under the same name with different options

    Args:
        dbm (MongoDatabaseManager): Database manager used for the index operations
        db_name (str): Name of the database owning the collection

    Returns:
        bool: True if the unique index was (re)created, False if it was already in place
    """
    index_info: dict[str, Any] = dict(dbm.get_index_info(CmdbExtendableOption.COLLECTION, db_name))
    existing: dict[str, Any] | None = index_info.get(OPTION_TYPE_VALUE_INDEX_NAME)

    if existing is not None and existing.get(INDEX_UNIQUE_KEY, False):
        # Already unique - but a run interrupted between the two index operations may still have to
        # finish dropping the legacy index
        _drop_legacy_option_type_index(dbm, db_name, index_info)
        return False

    if existing is not None:
        dbm.drop_index(CmdbExtendableOption.COLLECTION, db_name, OPTION_TYPE_VALUE_INDEX_NAME)

    declaration: dict[str, Any] | None = next(
        (index for index in CmdbExtendableOption.INDEX_KEYS
         if index.get('name') == OPTION_TYPE_VALUE_INDEX_NAME),
        None,
    )

    if declaration is None:
        return False

    dbm.create_indexes(CmdbExtendableOption.COLLECTION, db_name, [IndexModel(**declaration)])

    _drop_legacy_option_type_index(dbm, db_name, index_info)

    return True


def _drop_legacy_option_type_index(
        dbm: MongoDatabaseManager,
        db_name: str,
        index_info: dict[str, Any]) -> None:
    """
    Drops the superseded non-unique 'option_type' index when the collection still carries it

    Args:
        dbm (MongoDatabaseManager): Database manager used for the drop
        db_name (str): Name of the database owning the collection
        index_info (dict[str, Any]): The collection's index information, as read before the rebuild
    """
    if LEGACY_OPTION_TYPE_INDEX_NAME not in index_info:
        return

    dbm.drop_index(CmdbExtendableOption.COLLECTION, db_name, LEGACY_OPTION_TYPE_INDEX_NAME)

    LOGGER.info(
        "[updater_20260902] Dropped the superseded '%s' index, now covered by '%s'",
        LEGACY_OPTION_TYPE_INDEX_NAME, OPTION_TYPE_VALUE_INDEX_NAME,
    )

# -------------------------------------------------------------------------------------------------------------------- #
# ---------------------------------------------- Update20260902 - CLASS ---------------------------------------------- #
# -------------------------------------------------------------------------------------------------------------------- #
class Update20260902(BaseDatabaseUpdate):
    """
    De-duplicates CmdbExtendableOptions per OptionType and makes (option_type, value) unique

    Extends: BaseDatabaseUpdate
    """
    def creation_date(self) -> int:
        return 20260902


    def description(self) -> str:
        return "De-duplicates CmdbExtendableOptions and makes their value unique within an OptionType"


    def start_update(self) -> None:
        """
        De-duplicates first, then rebuilds the index, then bumps the version

        The order is not optional: MongoDB refuses to build a unique index over a collection that
        still holds duplicates, so a crash between the two halves must leave the version untouched
        and start over

        Raises:
            UpdaterException: If either half fails
        """
        try:
            removed: int = deduplicate_options(self.dbm, self.db_name)

            if removed:
                LOGGER.info("[updater_20260902] Removed %s duplicate CmdbExtendableOption(s)", removed)

            if rebuild_value_index(self.dbm, self.db_name):
                LOGGER.info(
                    "[updater_20260902] Built the unique '%s' index on %s",
                    OPTION_TYPE_VALUE_INDEX_NAME, CmdbExtendableOption.COLLECTION,
                )

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(str(err)) from err
