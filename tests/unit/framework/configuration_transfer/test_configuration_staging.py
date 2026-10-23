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
Unit tests for cmdb.framework.configuration_transfer.configuration_staging

Pure tests: no Mongo. What is pinned here: a staging name carries the prefix and 32 hex characters, a name that
exists is drawn again and too many clashes refuse; the updaters a file needs are exactly the registered ones after
its version up to the target's, ascending; the updaters run in the order given on the staging database; a file of
the importing version is answered as it is, without touching the database; and the temporary database is dropped
when the migration fails
"""
import re
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from cmdb.framework.configuration_transfer import (
    TransferFileKey,
    TransferInformationKey,
    build_component_section,
    build_transfer_file,
    migrate_transfer_file,
)
from cmdb.framework.configuration_transfer import configuration_staging as module
from cmdb.framework.configuration_transfer.configuration_staging import (
    draw_staging_name,
    read_migrated_file,
    run_updaters,
    updater_versions_between,
)
from cmdb.framework.configuration_transfer.configuration_transfer_constants import (
    MAX_STAGING_NAME_ATTEMPTS,
    NO_STAGING_NAME,
    STAGING_DATABASE_PREFIX,
)
from cmdb.errors.configuration_transfer import StagingDatabaseError
# -------------------------------------------------------------------------------------------------------------------- #

# What the transfer file is called in its information section
EXPORT_NAME: str = 'Test export'

REGISTERED: list[int] = [20261012, 20261003, 20261014, 20261010, 20261013]
TAKEN: str = 'a' * 32
FREE: str = 'b' * 32


def test_a_staging_name_is_the_prefix_and_32_hex_characters() -> None:
    """The real draw: prefix + a uuid4's hex"""
    assert re.fullmatch(f'{STAGING_DATABASE_PREFIX}[0-9a-f]{{32}}', draw_staging_name(set()))


def test_a_name_that_exists_is_drawn_again() -> None:
    """The first draw clashes with an existing database; the second is used"""
    draws = iter([TAKEN, FREE])

    assert draw_staging_name({f'{STAGING_DATABASE_PREFIX}{TAKEN}'}, lambda: next(draws)) == \
        f'{STAGING_DATABASE_PREFIX}{FREE}'


def test_too_many_clashes_refuse() -> None:
    """Every attempt clashes -> StagingDatabaseError naming the attempts"""
    draw: MagicMock = MagicMock(return_value=TAKEN)

    with pytest.raises(StagingDatabaseError) as exc_info:
        draw_staging_name({f'{STAGING_DATABASE_PREFIX}{TAKEN}'}, draw)

    assert str(exc_info.value) == NO_STAGING_NAME.format(attempts=MAX_STAGING_NAME_ATTEMPTS)
    assert draw.call_count == MAX_STAGING_NAME_ATTEMPTS


@pytest.mark.parametrize('file_version,target_version,expected', [
    (20261010, 20261014, [20261012, 20261013, 20261014]),
    (20261003, 20261012, [20261010, 20261012]),
    (20261014, 20261014, []),
    (20250101, 20261003, [20261003]),
])
def test_updater_versions_between(file_version: int, target_version: int, expected: list[int]) -> None:
    """After the file's version, up to and including the target's, ascending"""
    assert updater_versions_between(REGISTERED, file_version, target_version) == expected


def test_run_updaters_runs_each_class_on_the_staging_database_in_order() -> None:
    """Loaded by version, built on the staging database, started - in the order given"""
    dbm: MagicMock = MagicMock()
    classes: dict[str, MagicMock] = {}

    def _load(path: str) -> MagicMock:
        classes[path] = MagicMock(name=path)
        return classes[path]

    with patch.object(module, 'load_class', side_effect=_load):
        run_updaters(dbm, 'staging', [20261013, 20261014])

    assert [path.rsplit('.', 1)[1] for path in classes] == ['Update20261013', 'Update20261014']
    for updater_class in classes.values():
        assert updater_class.mock_calls == [call(dbm, 'staging'), call().start_update()]


def test_a_file_of_the_importing_version_is_answered_as_it_is() -> None:
    """No staging database at all"""
    dbm: MagicMock = MagicMock()
    transfer_file: dict[str, Any] = build_transfer_file(20261014, {}, name=EXPORT_NAME)

    assert migrate_transfer_file(dbm, transfer_file, 20261014, []) is transfer_file
    assert not dbm.mock_calls


def test_the_staging_database_is_dropped_when_the_migration_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """An updater raising -> the error surfaces and the drawn database is dropped"""
    dbm: MagicMock = MagicMock()
    dbm.connector.client.list_database_names.return_value = []
    monkeypatch.setattr(module, 'draw_staging_name', lambda existing: 'tmp_test_configuration_import_x')
    monkeypatch.setattr(module, 'seed_staging_database', MagicMock())
    monkeypatch.setattr(module, 'DatabaseUpdater', MagicMock())
    monkeypatch.setattr(module, 'run_updaters', MagicMock(side_effect=RuntimeError('updater failed')))

    with pytest.raises(RuntimeError):
        migrate_transfer_file(dbm, {TransferFileKey.DB_VERSION.value: 20261010}, 20261014, [])

    dbm.connector.client.drop_database.assert_called_once_with('tmp_test_configuration_import_x')


def test_the_migrated_file_carries_the_migrated_entries_and_their_counts() -> None:
    """An updater removed an entry: the counter stays the file's, the count follows the entries, the rest is kept"""
    types_component: MagicMock = MagicMock(COLLECTION='framework.types')
    types_component.NAME.value = 'types'
    stored: list[dict[str, Any]] = [{'public_id': 4}]
    dbm: MagicMock = MagicMock()
    dbm.get_collection.return_value.find.return_value = stored
    transfer_file: dict[str, Any] = build_transfer_file(
        20261010, {'types': build_component_section(9, [{'public_id': 4}, {'public_id': 8}])},
        name=EXPORT_NAME, description='kept',
    )

    migrated: dict[str, Any] = read_migrated_file(dbm, 'staging', [types_component], transfer_file, 20261014)

    assert migrated[TransferFileKey.DB_VERSION.value] == 20261014
    assert migrated[TransferFileKey.COMPONENTS.value] == {'types': build_component_section(9, stored)}
    assert migrated[TransferFileKey.INFORMATION.value] == {
        **transfer_file[TransferFileKey.INFORMATION.value], TransferInformationKey.COUNTS.value: {'types': 1},
    }
    assert transfer_file[TransferFileKey.INFORMATION.value][TransferInformationKey.COUNTS.value] == {'types': 2}
    assert migrated[TransferFileKey.META.value] is transfer_file[TransferFileKey.META.value]
