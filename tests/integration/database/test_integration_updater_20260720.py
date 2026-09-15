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
Integration tests for cmdb.database.updater.versions.updater_20260720 against a real MongoDB

Seeds two user groups - one holding the removed 'base.framework.type.clean' right alongside another
right, one holding only the other right - runs the migration and asserts the removed right is pulled
from the group that had it, the other right and the untouched group are left intact, the persisted
updater version is bumped, and a second run is a no-op (idempotent).
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.group_model.cmdb_user_group import CmdbUserGroup
from cmdb.database.updater.versions.updater_20260720 import Update20260720, REMOVED_RIGHT
# -------------------------------------------------------------------------------------------------------------------- #

GROUP_WITH_RIGHT_ID: int = 9560
GROUP_WITHOUT_RIGHT_ID: int = 9561
GROUP_IDS: list[int] = [GROUP_WITH_RIGHT_ID, GROUP_WITHOUT_RIGHT_ID]

OTHER_RIGHT: str = 'base.framework.type.edit'

UPDATER_SETTINGS_ID: str = 'updater'
SETTINGS_COLLECTION: str = 'settings.conf'


def _group_doc(public_id: int, rights: list[str]) -> dict[str, Any]:
    """Builds a minimal CmdbUserGroup document carrying the given right-name strings."""
    return {'public_id': public_id, 'name': f'grp-{public_id}', 'label': f'Group {public_id}', 'rights': rights}


def _rights(groups, public_id: int) -> list[str]:
    """Returns the stored rights list of the seeded group."""
    return groups.find_one({'public_id': public_id})['rights']


@pytest.fixture(name='groups')
def fixture_groups(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the two groups + preserves the updater setting, restoring everything afterwards."""
    groups = database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)
    settings = database_manager.get_collection(SETTINGS_COLLECTION, database_name)
    previous_setting: dict[str, Any] | None = settings.find_one({'_id': UPDATER_SETTINGS_ID})

    groups.delete_many({'public_id': {'$in': GROUP_IDS}})
    groups.insert_many([
        _group_doc(GROUP_WITH_RIGHT_ID, [REMOVED_RIGHT, OTHER_RIGHT]),
        _group_doc(GROUP_WITHOUT_RIGHT_ID, [OTHER_RIGHT]),
    ])

    yield groups

    groups.delete_many({'public_id': {'$in': GROUP_IDS}})
    if previous_setting is not None:
        settings.replace_one({'_id': UPDATER_SETTINGS_ID}, previous_setting, upsert=True)
    else:
        settings.delete_many({'_id': UPDATER_SETTINGS_ID})


class TestUpdater20260720:
    """The migration pulls the removed clean right from every group and bumps the version."""

    def test_removed_right_pulled_keeping_other_rights(
        self, groups, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The clean right is dropped from the group that held it; its other right survives."""
        Update20260720(database_manager, database_name).start_update()

        assert _rights(groups, GROUP_WITH_RIGHT_ID) == [OTHER_RIGHT]

    def test_group_without_the_right_is_untouched(
        self, groups, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A group that never held the clean right is left unchanged."""
        Update20260720(database_manager, database_name).start_update()

        assert _rights(groups, GROUP_WITHOUT_RIGHT_ID) == [OTHER_RIGHT]

    def test_version_bumped(
        self, groups, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The persisted updater version records the migration."""
        del groups
        Update20260720(database_manager, database_name).start_update()

        settings = database_manager.get_collection(SETTINGS_COLLECTION, database_name)
        assert settings.find_one({'_id': UPDATER_SETTINGS_ID})['version'] == 20260720

    def test_second_run_is_idempotent(
        self, groups, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Re-running the migration changes nothing (the right is already gone)."""
        Update20260720(database_manager, database_name).start_update()
        Update20260720(database_manager, database_name).start_update()

        assert _rights(groups, GROUP_WITH_RIGHT_ID) == [OTHER_RIGHT]
