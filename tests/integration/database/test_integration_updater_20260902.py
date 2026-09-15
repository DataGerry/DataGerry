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
Integration tests for cmdb.database.updater.versions.updater_20260902 against a real MongoDB

Reproduces a pre-migration database: the collection carries only the non-unique 'option_type' index,
and holds two duplicated values - a RISK category duplicated three times (one of the copies
predefined, so the keeper is NOT the lowest public_id) and an OBJECT_GROUP category duplicated twice.
Documents reference the copies that are about to be deleted, through both reference shapes: an
IsmsRisk's scalar 'category_id' and a CmdbObjectGroup's 'categories' array.

Asserts the migration keeps the predefined copy, re-points both reference shapes onto it, leaves
unrelated options and references alone, builds the unique index, drops the superseded one, bumps the
persisted updater version, is idempotent on a second run, and that a duplicate is refused afterwards
- both raw and through the MongoDatabaseManager, which must report it as a duplicate instead of
burning public_ids on retries. That refusal is the guarantee the whole migration exists to establish.
"""
from typing import Any

import pytest
from pymongo.errors import DuplicateKeyError

from cmdb.database import MongoDatabaseManager
from cmdb.errors.database import DocumentInsertError
from cmdb.database.updater.versions.updater_20260902 import Update20260902
from cmdb.models.extendable_option_model import (
    CmdbExtendableOption,
    ExtendableOptionKey,
    OptionType,
    OPTION_TYPE_VALUE_INDEX_NAME,
    LEGACY_OPTION_TYPE_INDEX_NAME,
)
from cmdb.models.isms_model.isms_risk import IsmsRisk
from cmdb.models.object_group_model.cmdb_object_group import CmdbObjectGroup
# -------------------------------------------------------------------------------------------------------------------- #

# The duplicated RISK category: three copies, the predefined one deliberately NOT the lowest id
RISK_VALUE: str = 'integration-duplicated-risk-category'
RISK_LOWEST_ID: int = 999410
RISK_PREDEFINED_ID: int = 999412       # the keeper: predefined beats a lower public_id
RISK_THIRD_ID: int = 999414

# The duplicated OBJECT_GROUP category: two copies, neither predefined -> lowest id keeps
GROUP_VALUE: str = 'integration-duplicated-group-category'
GROUP_KEEPER_ID: int = 999420
GROUP_DROPPED_ID: int = 999422

# An option that is not duplicated at all and must survive every run untouched
UNIQUE_VALUE: str = 'integration-unique-option'
UNIQUE_ID: int = 999430

# The same value under a DIFFERENT OptionType - not a duplicate, since identity includes the type
FOREIGN_TYPE_ID: int = 999432

# A value differing only in case, which stays a separate option (the index is case-sensitive)
CASE_VARIANT_ID: int = 999434

OPTION_IDS: list[int] = [
    RISK_LOWEST_ID, RISK_PREDEFINED_ID, RISK_THIRD_ID,
    GROUP_KEEPER_ID, GROUP_DROPPED_ID,
    UNIQUE_ID, FOREIGN_TYPE_ID, CASE_VARIANT_ID,
]

# The referencing documents
RISK_DOC_ID: int = 999440
UNRELATED_RISK_DOC_ID: int = 999442
OBJECT_GROUP_DOC_ID: int = 999450
UNRELATED_CATEGORY_ID: int = 999460       # another id in the categories array, which must stay

RISK_CATEGORY_FIELD: str = 'category_id'
OBJECT_GROUP_CATEGORIES_FIELD: str = 'categories'

UPDATER_SETTINGS_ID: str = 'updater'
SETTINGS_COLLECTION: str = 'settings.conf'


def _option_doc(public_id: int, value: str, option_type: str, predefined: bool = False) -> dict[str, Any]:
    """Builds a CmdbExtendableOption document"""
    return {
        ExtendableOptionKey.PUBLIC_ID.value: public_id,
        ExtendableOptionKey.VALUE.value: value,
        ExtendableOptionKey.OPTION_TYPE.value: option_type,
        ExtendableOptionKey.PREDEFINED.value: predefined,
    }


@pytest.fixture(name='pre_migration_options', autouse=True)
def fixture_pre_migration_options(database_manager: MongoDatabaseManager, database_name: str):
    """
    Recreates a pre-migration collection: the non-unique 'option_type' index, plus duplicates

    The unique index has to be absent before the duplicates can be inserted at all - which is exactly
    the state every database created before this migration is in.
    """
    options = database_manager.get_collection(CmdbExtendableOption.COLLECTION, database_name)
    risks = database_manager.get_collection(IsmsRisk.COLLECTION, database_name)
    groups = database_manager.get_collection(CmdbObjectGroup.COLLECTION, database_name)
    settings = database_manager.get_collection(SETTINGS_COLLECTION, database_name)
    previous_setting: dict[str, Any] | None = settings.find_one({'_id': UPDATER_SETTINGS_ID})

    def _purge() -> None:
        options.delete_many({ExtendableOptionKey.PUBLIC_ID.value: {'$in': OPTION_IDS}})
        risks.delete_many({'public_id': {'$in': [RISK_DOC_ID, UNRELATED_RISK_DOC_ID]}})
        groups.delete_many({'public_id': {'$in': [OBJECT_GROUP_DOC_ID]}})

    _purge()

    if OPTION_TYPE_VALUE_INDEX_NAME in options.index_information():
        options.drop_index(OPTION_TYPE_VALUE_INDEX_NAME)

    if LEGACY_OPTION_TYPE_INDEX_NAME not in options.index_information():
        options.create_index([(ExtendableOptionKey.OPTION_TYPE.value, 1)],
                             name=LEGACY_OPTION_TYPE_INDEX_NAME)

    options.insert_many([
        _option_doc(RISK_LOWEST_ID, RISK_VALUE, OptionType.RISK.value),
        _option_doc(RISK_PREDEFINED_ID, RISK_VALUE, OptionType.RISK.value, predefined=True),
        _option_doc(RISK_THIRD_ID, RISK_VALUE, OptionType.RISK.value),
        _option_doc(GROUP_KEEPER_ID, GROUP_VALUE, OptionType.OBJECT_GROUP.value),
        _option_doc(GROUP_DROPPED_ID, GROUP_VALUE, OptionType.OBJECT_GROUP.value),
        _option_doc(UNIQUE_ID, UNIQUE_VALUE, OptionType.RISK.value),
        # Same value, different OptionType - identity is the pair, so this is not a duplicate
        _option_doc(FOREIGN_TYPE_ID, UNIQUE_VALUE, OptionType.CONTROL_MEASURE.value),
        # Same value bar its case - the index is case-sensitive, so this is not a duplicate either
        _option_doc(CASE_VARIANT_ID, UNIQUE_VALUE.upper(), OptionType.RISK.value),
    ])
    risks.insert_many([
        {'public_id': RISK_DOC_ID, 'name': 'referencing-risk', RISK_CATEGORY_FIELD: RISK_THIRD_ID},
        {'public_id': UNRELATED_RISK_DOC_ID, 'name': 'unrelated-risk', RISK_CATEGORY_FIELD: UNIQUE_ID},
    ])
    groups.insert_one({
        'public_id': OBJECT_GROUP_DOC_ID,
        'name': 'referencing-group',
        OBJECT_GROUP_CATEGORIES_FIELD: [UNRELATED_CATEGORY_ID, GROUP_DROPPED_ID],
    })

    yield options, risks, groups

    _purge()

    if previous_setting is not None:
        settings.replace_one({'_id': UPDATER_SETTINGS_ID}, previous_setting, upsert=True)
    else:
        settings.delete_many({'_id': UPDATER_SETTINGS_ID})

    # Leave the collection carrying what the model declares, so later tests see a normal collection
    if OPTION_TYPE_VALUE_INDEX_NAME not in options.index_information():
        database_manager.create_indexes(
            CmdbExtendableOption.COLLECTION, database_name, CmdbExtendableOption.get_index_keys(),
        )


def _run_migration(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """Runs the migration against the test database"""
    Update20260902(database_manager, database_name).start_update()


def _values(options, value: str, option_type: str) -> list[dict[str, Any]]:
    """Every stored option carrying the given identity pair"""
    return list(options.find({
        ExtendableOptionKey.VALUE.value: value,
        ExtendableOptionKey.OPTION_TYPE.value: option_type,
    }))

# -------------------------------------------------------------------------------------------------------------------- #

def test_keeps_the_predefined_duplicate(
        pre_migration_options, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """The predefined copy survives even though another copy has a lower public_id"""
    options, _, _ = pre_migration_options

    _run_migration(database_manager, database_name)

    remaining = _values(options, RISK_VALUE, OptionType.RISK.value)

    assert len(remaining) == 1
    assert remaining[0][ExtendableOptionKey.PUBLIC_ID.value] == RISK_PREDEFINED_ID


def test_keeps_the_lowest_id_when_no_duplicate_is_predefined(
        pre_migration_options, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """Among customer-created equals the oldest entry survives"""
    options, _, _ = pre_migration_options

    _run_migration(database_manager, database_name)

    remaining = _values(options, GROUP_VALUE, OptionType.OBJECT_GROUP.value)

    assert len(remaining) == 1
    assert remaining[0][ExtendableOptionKey.PUBLIC_ID.value] == GROUP_KEEPER_ID


def test_repoints_a_scalar_reference_onto_the_keeper(
        pre_migration_options, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """An IsmsRisk must never be left pointing at a category that was deleted"""
    _, risks, _ = pre_migration_options

    _run_migration(database_manager, database_name)

    assert risks.find_one({'public_id': RISK_DOC_ID})[RISK_CATEGORY_FIELD] == RISK_PREDEFINED_ID


def test_repoints_an_array_reference_and_keeps_its_other_entries(
        pre_migration_options, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """The discarded id leaves the categories array, the keeper joins it, everything else stays"""
    _, _, groups = pre_migration_options

    _run_migration(database_manager, database_name)

    categories = groups.find_one({'public_id': OBJECT_GROUP_DOC_ID})[OBJECT_GROUP_CATEGORIES_FIELD]

    assert GROUP_DROPPED_ID not in categories
    assert sorted(categories) == sorted([UNRELATED_CATEGORY_ID, GROUP_KEEPER_ID])


def test_leaves_unrelated_options_and_references_alone(
        pre_migration_options, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """A value that is not duplicated is untouched, and so is the document referencing it"""
    options, risks, _ = pre_migration_options

    _run_migration(database_manager, database_name)

    assert options.find_one({ExtendableOptionKey.PUBLIC_ID.value: UNIQUE_ID}) is not None
    assert risks.find_one({'public_id': UNRELATED_RISK_DOC_ID})[RISK_CATEGORY_FIELD] == UNIQUE_ID


def test_the_same_value_under_another_option_type_is_not_a_duplicate(
        pre_migration_options, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """Identity is the (option_type, value) pair - the same text in two dropdowns is two options"""
    options, _, _ = pre_migration_options

    _run_migration(database_manager, database_name)

    assert options.find_one({ExtendableOptionKey.PUBLIC_ID.value: FOREIGN_TYPE_ID}) is not None


def test_a_case_variant_is_not_a_duplicate(
        pre_migration_options, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """The index is case-sensitive, so values differing only in case both survive"""
    options, _, _ = pre_migration_options

    _run_migration(database_manager, database_name)

    assert options.find_one({ExtendableOptionKey.PUBLIC_ID.value: CASE_VARIANT_ID}) is not None


def test_builds_the_unique_index_drops_the_legacy_one_and_bumps_the_version(
        pre_migration_options, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """The declared unique index is in place, the index it supersedes is gone, the run is recorded"""
    options, _, _ = pre_migration_options
    settings = database_manager.get_collection(SETTINGS_COLLECTION, database_name)

    _run_migration(database_manager, database_name)

    index_info = options.index_information()

    assert index_info[OPTION_TYPE_VALUE_INDEX_NAME].get('unique') is True
    assert LEGACY_OPTION_TYPE_INDEX_NAME not in index_info
    assert settings.find_one({'_id': UPDATER_SETTINGS_ID})['version'] == 20260902


def test_a_second_run_changes_nothing(
        pre_migration_options, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """Re-run safety: the migration is allowed to be interrupted and started again"""
    options, risks, groups = pre_migration_options

    _run_migration(database_manager, database_name)

    after_first = (
        sorted(option[ExtendableOptionKey.PUBLIC_ID.value] for option in options.find(
            {ExtendableOptionKey.PUBLIC_ID.value: {'$in': OPTION_IDS}})),
        risks.find_one({'public_id': RISK_DOC_ID})[RISK_CATEGORY_FIELD],
        sorted(groups.find_one({'public_id': OBJECT_GROUP_DOC_ID})[OBJECT_GROUP_CATEGORIES_FIELD]),
        sorted(options.index_information()),
    )

    _run_migration(database_manager, database_name)

    after_second = (
        sorted(option[ExtendableOptionKey.PUBLIC_ID.value] for option in options.find(
            {ExtendableOptionKey.PUBLIC_ID.value: {'$in': OPTION_IDS}})),
        risks.find_one({'public_id': RISK_DOC_ID})[RISK_CATEGORY_FIELD],
        sorted(groups.find_one({'public_id': OBJECT_GROUP_DOC_ID})[OBJECT_GROUP_CATEGORIES_FIELD]),
        sorted(options.index_information()),
    )

    assert after_first == after_second


def test_a_duplicate_is_refused_afterwards(
        pre_migration_options, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """The point of the whole migration: the database itself now rejects the second copy"""
    options, _, _ = pre_migration_options

    _run_migration(database_manager, database_name)

    with pytest.raises(DuplicateKeyError):
        options.insert_one(_option_doc(999470, RISK_VALUE, OptionType.RISK.value))


def test_the_manager_reports_a_duplicate_without_burning_public_ids(
        pre_migration_options, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """A duplicate insert must fail as a duplicate, not as ten exhausted public_id retries"""
    _run_migration(database_manager, database_name)

    before: int = database_manager.get_next_public_id(CmdbExtendableOption.COLLECTION, database_name)

    with pytest.raises(DocumentInsertError) as raised:
        database_manager.insert(CmdbExtendableOption.COLLECTION, database_name, {
            ExtendableOptionKey.VALUE.value: RISK_VALUE,
            ExtendableOptionKey.OPTION_TYPE.value: OptionType.RISK.value,
            ExtendableOptionKey.PREDEFINED.value: False,
        })

    after: int = database_manager.get_next_public_id(CmdbExtendableOption.COLLECTION, database_name)

    assert 'Duplicate key error' in str(raised.value)
    # One id was reserved for the attempt; the ten-retry loop would have consumed ten
    assert after - before == 1
