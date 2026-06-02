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

Covers the contract metadata (creation_date / description) of every updater and the bulk
start_update logic of the three updaters that were optimized to a single update_many_raw per field
(20200513, 20240603, 20251203). The remaining updaters' start_update is heavy I/O orchestration
covered by the integration/functional suites.
"""
from unittest.mock import MagicMock

import pytest

from cmdb.models.ci_explorer_model import CmdbCiExplorerProfile
from cmdb.errors.updater import UpdaterException
from cmdb.database.updater.base_database_update import BaseDatabaseUpdate
from cmdb.database.updater.versions.updater_20200512 import Update20200512
from cmdb.database.updater.versions.updater_20200513 import Update20200513
from cmdb.database.updater.versions.updater_20240603 import Update20240603
from cmdb.database.updater.versions.updater_20250619 import Update20250619
from cmdb.database.updater.versions.updater_20251203 import Update20251203
from cmdb.database.updater.versions.updater_20260225 import Update20260225
from cmdb.database.updater.versions.updater_20260226 import Update20260226
from cmdb.database.updater.versions.updater_20260417 import Update20260417
# -------------------------------------------------------------------------------------------------------------------- #


def _new(updater_cls: type[BaseDatabaseUpdate]) -> BaseDatabaseUpdate:
    """Builds an updater without its real __init__ (caller attaches the mocks it needs)"""
    return updater_cls.__new__(updater_cls)

# -------------------------------------------------------------------------------------------------------------------- #
#                                          contract metadata (all updaters)                                           #
# -------------------------------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize('updater_cls, expected_date', [
    (Update20200512, 20200512),
    (Update20200513, 20200513),
    (Update20240603, 20240603),
    (Update20250619, 20250619),
    (Update20251203, 20251203),
    (Update20260225, 20260225),
    (Update20260226, 20260226),
    (Update20260417, 20260417),
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

def test_20200513_bulk_adds_two_type_fields_and_bumps_version() -> None:
    """20200513 backfills 'global_template_ids' and 'selectable_as_parent' with one bulk update each"""
    updater = _new(Update20200513)
    updater.types_manager = types_manager = MagicMock()
    updater.settings_manager = settings_manager = MagicMock()

    updater.start_update()

    calls = types_manager.update_many_raw.call_args_list
    assert len(calls) == 2
    assert calls[0].kwargs == {
        'filter_query': {'global_template_ids': {'$exists': False}},
        'update': {'$set': {'global_template_ids': []}},
    }
    assert calls[1].kwargs == {
        'filter_query': {'selectable_as_parent': {'$exists': False}},
        'update': {'$set': {'selectable_as_parent': True}},
    }
    settings_manager.write.assert_called_once_with(
        _id='updater', data={'_id': 'updater', 'version': 20200513},
    )


def test_20240603_bulk_adds_multi_data_sections_and_bumps_version() -> None:
    """20240603 backfills 'multi_data_sections' with a single bulk update on objects"""
    updater = _new(Update20240603)
    updater.objects_manager = objects_manager = MagicMock()
    updater.settings_manager = settings_manager = MagicMock()

    updater.start_update()

    objects_manager.update_many_raw.assert_called_once_with(
        filter_query={'multi_data_sections': {'$exists': False}},
        update={'$set': {'multi_data_sections': []}},
    )
    settings_manager.write.assert_called_once_with(
        _id='updater', data={'_id': 'updater', 'version': 20240603},
    )


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


def test_start_update_wraps_failures_in_updater_exception() -> None:
    """A failure during the migration is re-raised as UpdaterException"""
    updater = _new(Update20240603)
    updater.objects_manager = objects_manager = MagicMock()
    updater.settings_manager = MagicMock()
    objects_manager.update_many_raw.side_effect = RuntimeError("db down")

    with pytest.raises(UpdaterException):
        updater.start_update()
