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
Integration tests for cmdb.database.updater.versions.updater_20260901 against a real MongoDB

Reproduces a pre-migration database - no Port Connectivity extendable options, CmdbTypes carrying no
'uses_ports' key - and asserts both jobs land, that a second run is a no-op, and that neither job
disturbs data it does not own.

The double run is the point of this suite. The option half has NO database-level protection against
duplicates (CmdbExtendableOption declares a single non-unique index on option_type), so its
idempotence lives entirely in the migration's own diff and has to be proven against a real
collection, not a stub.
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.predefined_data.port_data import get_default_port_extendable_options
from cmdb.database.updater.versions.updater_20260901 import Update20260901
from cmdb.models.extendable_option_model import CmdbExtendableOption, OptionType, ExtendableOptionKey
from cmdb.models.type_model import CmdbType, TypeSchemaKey
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

PORT_OPTION_TYPES: list[str] = [
    OptionType.PORT_STATUS.value,
    OptionType.PORT_TYPE.value,
    OptionType.PORT_SPEED.value,
    OptionType.CABLE_TYPE.value,
]

TOTAL_OPTIONS: int = 44

# Types seeded without the 'uses_ports' key - the state every type is in before this migration
LEGACY_TYPE_ID: int = 9930
SECOND_LEGACY_TYPE_ID: int = 9931
# A type that already carries the flag set to True, which the backfill must not touch
PORT_BEARING_TYPE_ID: int = 9932

ALL_TYPE_IDS: list[int] = [LEGACY_TYPE_ID, SECOND_LEGACY_TYPE_ID, PORT_BEARING_TYPE_ID]

# An unrelated extendable option that must survive both runs untouched
FOREIGN_OPTION_VALUE: str = 'integration-foreign-option'


@pytest.fixture(name='pre_migration_db', autouse=True)
def fixture_pre_migration_db(database_manager: MongoDatabaseManager, database_name: str):
    """Clears the port options and seeds types in their pre-migration shape, cleaning up after"""
    options = database_manager.get_collection(CmdbExtendableOption.COLLECTION, database_name)
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)

    def _purge() -> None:
        options.delete_many({ExtendableOptionKey.OPTION_TYPE: {'$in': PORT_OPTION_TYPES}})
        options.delete_many({ExtendableOptionKey.VALUE: FOREIGN_OPTION_VALUE})
        types.delete_many({'public_id': {'$in': ALL_TYPE_IDS}})

    _purge()

    legacy_one = make_type_doc(LEGACY_TYPE_ID, 'migration-legacy-one')
    legacy_two = make_type_doc(SECOND_LEGACY_TYPE_ID, 'migration-legacy-two')
    port_bearing = make_type_doc(PORT_BEARING_TYPE_ID, 'migration-port-bearing')

    for doc in (legacy_one, legacy_two):
        doc.pop(TypeSchemaKey.USES_PORTS.value, None)  # the pre-migration shape: no key at all

    port_bearing[TypeSchemaKey.USES_PORTS.value] = True

    types.insert_many([legacy_one, legacy_two, port_bearing])
    options.insert_one({
        ExtendableOptionKey.VALUE: FOREIGN_OPTION_VALUE,
        ExtendableOptionKey.OPTION_TYPE: OptionType.RISK.value,
        ExtendableOptionKey.PREDEFINED: True,
        'public_id': 999301,
    })

    yield

    _purge()


def _run_migration(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """Runs the migration against the test database"""
    Update20260901(database_manager, database_name).start_update()


def _stored_port_options(
    database_manager: MongoDatabaseManager, database_name: str
) -> list[dict[str, Any]]:
    """Every stored extendable option belonging to Port Connectivity"""
    return list(database_manager.get_collection(CmdbExtendableOption.COLLECTION, database_name)
                .find({ExtendableOptionKey.OPTION_TYPE: {'$in': PORT_OPTION_TYPES}}))


def _type(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> dict[str, Any]:
    """Reads one seeded CmdbType back"""
    return database_manager.get_collection(CmdbType.COLLECTION, database_name)\
        .find_one({'public_id': public_id})


class TestTheOptionHalf:
    """Seeding the four predefined option lists into an existing installation."""

    def test_seeds_every_option(
        self, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """All 44 predefined options land, each with a public_id assigned by the insert."""
        _run_migration(database_manager, database_name)

        stored = _stored_port_options(database_manager, database_name)

        assert len(stored) == TOTAL_OPTIONS
        assert all(option[ExtendableOptionKey.PREDEFINED] is True for option in stored)
        assert all(option.get('public_id') for option in stored)

    def test_the_stored_values_match_the_declared_ones(
        self, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """What reaches the database is exactly what the data module declares."""
        _run_migration(database_manager, database_name)

        stored = {(option[ExtendableOptionKey.OPTION_TYPE], option[ExtendableOptionKey.VALUE])
                  for option in _stored_port_options(database_manager, database_name)}
        declared = {(option[ExtendableOptionKey.OPTION_TYPE].value, option[ExtendableOptionKey.VALUE])
                    for option in get_default_port_extendable_options()}

        assert stored == declared

    def test_a_second_run_inserts_nothing(
        self, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """
        The re-run test this migration exists to pass.

        There is no unique index on (option_type, value), so without the migration's own diff a
        second run would leave 88 options and every port dropdown would show each entry twice.
        """
        _run_migration(database_manager, database_name)
        _run_migration(database_manager, database_name)

        assert len(_stored_port_options(database_manager, database_name)) == TOTAL_OPTIONS

    def test_a_partially_seeded_database_is_topped_up_without_duplicates(
        self, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """An interrupted first run resumes cleanly rather than duplicating what it already wrote."""
        options = database_manager.get_collection(CmdbExtendableOption.COLLECTION, database_name)
        options.insert_one({
            ExtendableOptionKey.VALUE: 'Up',
            ExtendableOptionKey.OPTION_TYPE: OptionType.PORT_STATUS.value,
            ExtendableOptionKey.PREDEFINED: True,
            'public_id': 999302,
        })

        _run_migration(database_manager, database_name)

        stored = _stored_port_options(database_manager, database_name)
        ups = [o for o in stored
               if o[ExtendableOptionKey.VALUE] == 'Up'
               and o[ExtendableOptionKey.OPTION_TYPE] == OptionType.PORT_STATUS.value]

        assert len(stored) == TOTAL_OPTIONS
        assert len(ups) == 1

    def test_another_features_options_are_untouched(
        self, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """An ISMS installation's own options survive both runs."""
        _run_migration(database_manager, database_name)
        _run_migration(database_manager, database_name)

        foreign = list(database_manager.get_collection(CmdbExtendableOption.COLLECTION, database_name)
                       .find({ExtendableOptionKey.VALUE: FOREIGN_OPTION_VALUE}))

        assert len(foreign) == 1


class TestTheBackfillHalf:
    """Filling 'uses_ports' in on types that predate the field."""

    def test_a_type_without_the_key_gains_it_as_false(
        self, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """The pre-migration shape - no key at all - becomes an explicit False."""
        assert TypeSchemaKey.USES_PORTS.value not in _type(
            database_manager, database_name, LEGACY_TYPE_ID
        )

        _run_migration(database_manager, database_name)

        assert _type(database_manager, database_name, LEGACY_TYPE_ID)[
            TypeSchemaKey.USES_PORTS.value] is False

    def test_a_port_bearing_type_keeps_its_value(
        self, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """
        A type set up between the release and this migration is not reset.

        The filter matches on the key's ABSENCE, so an existing True is never overwritten - the
        difference between a backfill and a destructive reset.
        """
        _run_migration(database_manager, database_name)

        assert _type(database_manager, database_name, PORT_BEARING_TYPE_ID)[
            TypeSchemaKey.USES_PORTS.value] is True

    def test_every_type_carries_the_field_afterwards(
        self, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """The point of the backfill: no type in the collection is left without the key."""
        _run_migration(database_manager, database_name)

        remaining = database_manager.get_collection(CmdbType.COLLECTION, database_name)\
            .count_documents({TypeSchemaKey.USES_PORTS.value: {'$exists': False}})

        assert remaining == 0

    def test_the_plain_false_filter_is_safe_afterwards(
        self, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """
        What the backfill buys, stated as a test.

        Before it, {'uses_ports': False} silently skipped every legacy type and callers had to spell
        the query {'$ne': True}. After it, both spellings agree.
        """
        _run_migration(database_manager, database_name)

        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        plain = {doc['public_id'] for doc in types.find({TypeSchemaKey.USES_PORTS.value: False})}
        ne_true = {doc['public_id'] for doc in types.find(
            {TypeSchemaKey.USES_PORTS.value: {'$ne': True}})}

        assert LEGACY_TYPE_ID in plain
        assert SECOND_LEGACY_TYPE_ID in plain
        assert plain == ne_true

    def test_a_second_run_changes_nothing(
        self, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """Idempotent by construction: '$exists: False' matches nothing the second time."""
        _run_migration(database_manager, database_name)
        before = _type(database_manager, database_name, PORT_BEARING_TYPE_ID)

        _run_migration(database_manager, database_name)

        assert _type(database_manager, database_name, PORT_BEARING_TYPE_ID) == before
