# DATAGERRY - OpenSource Enterprise CMDB
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
Unit tests for the versioned database updaters

Covers the contract metadata (creation_date / description) of every registered updater, the two
registries a new migration has to be added to by hand (DatabaseUpdater.__UPDATE_VERSIONS__ and the
Makefile's PyInstaller --hidden-import list - forgetting either fails silently: the migration never
runs, or it is missing from the binary) and the bulk start_update logic of the two updaters whose
whole migration is server-side update_many_raw work (20251203 and 20260731). The remaining updaters'
start_update is heavy I/O orchestration covered by their own unit suites and the integration suites.
"""
import re
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

from cmdb.models.ci_explorer_model import CmdbCiExplorerProfile
from cmdb.models.group_model.cmdb_user_group import CmdbUserGroup
from cmdb.models.reports_model.cmdb_report import CmdbReport
from cmdb.errors.updater import UpdaterException
from cmdb.database.database_services.database_updater import DatabaseUpdater
from cmdb.database.updater.base_database_update import BaseDatabaseUpdate
from cmdb.database.updater.versions.updater_20250619 import Update20250619
from cmdb.database.updater.versions.updater_20251203 import Update20251203
from cmdb.database.updater.versions.updater_20260225 import Update20260225
from cmdb.database.updater.versions.updater_20260226 import Update20260226
from cmdb.database.updater.versions.updater_20260417 import Update20260417
from cmdb.database.updater.versions.updater_20260604 import Update20260604
from cmdb.database.updater.versions.updater_20260720 import Update20260720
from cmdb.database.updater.versions.updater_20260731 import (
    Update20260731,
    DEFAULT_MDS_MODE,
    DEFAULT_PREDEFINED,
    MDS_MODE_KEY,
    PREDEFINED_KEY,
)
from cmdb.database.updater.versions.updater_20260804 import Update20260804
from cmdb.database.updater.versions.updater_20260824 import Update20260824
from cmdb.database.updater.versions.updater_20260901 import Update20260901
from cmdb.database.updater.versions.updater_20260902 import Update20260902
# -------------------------------------------------------------------------------------------------------------------- #


def _new(updater_cls: type[BaseDatabaseUpdate]) -> BaseDatabaseUpdate:
    """Builds an updater without its real __init__ (caller attaches the mocks it needs)"""
    return updater_cls.__new__(updater_cls)

# Repo paths / patterns for the two hand-maintained registries a new migration must be added to
REPO_ROOT: Path = Path(__file__).resolve().parents[4]
VERSIONS_DIR: Path = REPO_ROOT / 'cmdb' / 'database' / 'updater' / 'versions'
MAKEFILE: Path = REPO_ROOT / 'Makefile'
UPDATER_MODULE_PATTERN: re.Pattern = re.compile(r'^updater_(\d{8})\.py$')
HIDDEN_IMPORT_PATTERN: str = 'cmdb.database.updater.versions.updater_{version}'


def _updater_module_versions() -> set[int]:
    """The version of every updater module present under cmdb/database/updater/versions"""
    return {
        int(match.group(1))
        for match in (UPDATER_MODULE_PATTERN.match(path.name) for path in VERSIONS_DIR.iterdir())
        if match
    }

# -------------------------------------------------------------------------------------------------------------------- #
#                                        hand-maintained registries (all updaters)                                     #
# -------------------------------------------------------------------------------------------------------------------- #

def test_every_updater_module_is_registered() -> None:
    """An updater missing from __UPDATE_VERSIONS__ is never executed - and nothing else complains"""
    assert _updater_module_versions() == set(DatabaseUpdater.__UPDATE_VERSIONS__)


def test_registry_is_sorted_ascending() -> None:
    """Migrations run in registry order, so the list has to be ascending"""
    registered: list[int] = list(DatabaseUpdater.__UPDATE_VERSIONS__)

    assert registered == sorted(registered)


def test_every_registered_updater_has_a_pyinstaller_hidden_import() -> None:
    """A migration without its Makefile --hidden-import line is missing from the built binary"""
    makefile: str = MAKEFILE.read_text(encoding='utf-8')

    missing: list[int] = [
        version for version in DatabaseUpdater.__UPDATE_VERSIONS__
        if HIDDEN_IMPORT_PATTERN.format(version=version) not in makefile
    ]

    assert not missing

# -------------------------------------------------------------------------------------------------------------------- #
#                                          contract metadata (all updaters)                                           #
# -------------------------------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize('updater_cls, expected_date', [
    (Update20250619, 20250619),
    (Update20251203, 20251203),
    (Update20260225, 20260225),
    (Update20260226, 20260226),
    (Update20260417, 20260417),
    (Update20260604, 20260604),
    (Update20260720, 20260720),
    (Update20260731, 20260731),
    (Update20260804, 20260804),
    (Update20260824, 20260824),
    (Update20260901, 20260901),
    (Update20260902, 20260902),
], ids=str)
def test_creation_date_and_description(updater_cls: type[BaseDatabaseUpdate], expected_date: int) -> None:
    """Each updater reports the date encoded in its name and a non-empty description"""
    updater = updater_cls.__new__(updater_cls)

    assert updater.creation_date() == expected_date
    assert isinstance(updater.description(), str)
    assert updater.description().strip()

# -------------------------------------------------------------------------------------------------------------------- #
#                                      bulk start_update (optimized updaters)                                          #
# -------------------------------------------------------------------------------------------------------------------- #

def test_20251203_bulk_adds_with_locations_and_bumps_version() -> None:
    """20251203 backfills 'with_locations' on the CI-Explorer profile collection via the dbm"""
    updater = _new(Update20251203)
    updater.dbm = dbm = MagicMock()
    updater.db_name = "testdb"
    updater.settings_manager = settings_manager = MagicMock()

    updater.start_update()

    dbm.update_many_raw.assert_called_once_with(
        collection=CmdbCiExplorerProfile.COLLECTION,
        db_name="testdb",
        filter_query={'with_locations': {'$exists': False}},
        update={'$set': {'with_locations': True}},
    )
    settings_manager.write.assert_called_once_with(
        _id='updater', data={'_id': 'updater', 'version': 20251203},
    )


def test_20260720_pulls_clean_right_and_bumps_version() -> None:
    """20260720 pulls the removed 'base.framework.type.clean' right from every user group"""
    updater = _new(Update20260720)
    updater.dbm = dbm = MagicMock()
    updater.db_name = "testdb"
    updater.settings_manager = settings_manager = MagicMock()

    updater.start_update()

    dbm.update_many_raw.assert_called_once_with(
        collection=CmdbUserGroup.COLLECTION,
        db_name="testdb",
        filter_query={'rights': 'base.framework.type.clean'},
        update={'$pull': {'rights': 'base.framework.type.clean'}},
    )
    settings_manager.write.assert_called_once_with(
        _id='updater', data={'_id': 'updater', 'version': 20260720},
    )


def test_start_update_wraps_failures_in_updater_exception() -> None:
    """A failure during the migration is re-raised as UpdaterException"""
    updater = _new(Update20251203)
    updater.dbm = dbm = MagicMock()
    updater.settings_manager = MagicMock()
    dbm.update_many_raw.side_effect = RuntimeError("db down")

    with pytest.raises(UpdaterException):
        updater.start_update()


def test_20260731_backfills_both_report_keys_and_bumps_version() -> None:
    """20260731 sets the default mds_mode / predefined on the reports missing each key"""
    updater = _new(Update20260731)
    updater.dbm = dbm = MagicMock()
    updater.db_name = "testdb"
    updater.settings_manager = settings_manager = MagicMock()

    updater.start_update()

    assert dbm.update_many_raw.call_args_list == [
        call(
            collection=CmdbReport.COLLECTION,
            db_name="testdb",
            filter_query={MDS_MODE_KEY: {'$exists': False}},
            update={'$set': {MDS_MODE_KEY: DEFAULT_MDS_MODE}},
        ),
        call(
            collection=CmdbReport.COLLECTION,
            db_name="testdb",
            filter_query={PREDEFINED_KEY: {'$exists': False}},
            update={'$set': {PREDEFINED_KEY: DEFAULT_PREDEFINED}},
        ),
    ]
    settings_manager.write.assert_called_once_with(
        _id='updater', data={'_id': 'updater', 'version': 20260731},
    )


def test_20260731_only_targets_documents_missing_the_key() -> None:
    """Both filters are '$exists: False', which is what makes a re-run a no-op"""
    updater = _new(Update20260731)
    updater.dbm = dbm = MagicMock()
    updater.db_name = "testdb"
    updater.settings_manager = MagicMock()

    updater.start_update()

    for a_call in dbm.update_many_raw.call_args_list:
        assert list(a_call.kwargs['filter_query'].values()) == [{'$exists': False}]


def test_20260731_wraps_a_failure_as_an_updater_exception() -> None:
    """A database failure surfaces as UpdaterException and the version is not bumped"""
    updater = _new(Update20260731)
    updater.dbm = dbm = MagicMock()
    updater.db_name = "testdb"
    updater.settings_manager = settings_manager = MagicMock()
    dbm.update_many_raw.side_effect = RuntimeError('boom')

    with pytest.raises(UpdaterException):
        updater.start_update()

    settings_manager.write.assert_not_called()
