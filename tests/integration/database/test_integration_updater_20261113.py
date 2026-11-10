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
Integration tests for cmdb.database.updater.versions.updater_20261113 against a real MongoDB

Seeds a group holding removed rights next to rights the catalogue keeps, a group holding only a family wildcard, and a
group holding none of the removed rights, runs the migration, and asserts:

  - every removed right leaves the group holding it, in the order the kept rights had; nothing else of it changes
  - a wildcard and a group without a removed right stay as they are
  - a second run changes nothing
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20261113 import REMOVED_RIGHTS, Update20261113
from cmdb.models.group_model import CmdbUserGroup, GroupKey
# -------------------------------------------------------------------------------------------------------------------- #

PUBLIC_ID: str = GroupKey.PUBLIC_ID.value
RIGHTS: str = GroupKey.RIGHTS.value

MIXED_GROUP_ID: int = 98771
WILDCARD_GROUP_ID: int = 98772
CLEAN_GROUP_ID: int = 98773
SEEDED_IDS: list[int] = [MIXED_GROUP_ID, WILDCARD_GROUP_ID, CLEAN_GROUP_ID]

KEPT_RIGHTS: list[str] = ['base.framework.rack.view', 'base.framework.type.edit', 'base.system.view']
WILDCARD_RIGHTS: list[str] = ['base.framework.rack.*', 'base.license.activation.*']

# The mixed group holds every removed right, interleaved with the kept ones
SPLIT: int = len(REMOVED_RIGHTS) // 2
MIXED_RIGHTS: list[str] = [
    KEPT_RIGHTS[0], *REMOVED_RIGHTS[:SPLIT], KEPT_RIGHTS[1], *REMOVED_RIGHTS[SPLIT:], KEPT_RIGHTS[2],
]


def _group(public_id: int, rights: list[str]) -> dict[str, Any]:
    """A stored group document"""
    return {PUBLIC_ID: public_id, GroupKey.NAME.value: f'upd-rights-{public_id}',
            GroupKey.LABEL.value: f'upd-rights-{public_id}', RIGHTS: rights}


@pytest.fixture(name='groups', autouse=True)
def fixture_groups(database_manager: MongoDatabaseManager, database_name: str):
    """The three groups - removed again after"""
    groups = database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)
    groups.delete_many({PUBLIC_ID: {'$in': SEEDED_IDS}})
    groups.insert_many([
        _group(MIXED_GROUP_ID, MIXED_RIGHTS),
        _group(WILDCARD_GROUP_ID, WILDCARD_RIGHTS),
        _group(CLEAN_GROUP_ID, KEPT_RIGHTS),
    ])
    yield groups
    groups.delete_many({PUBLIC_ID: {'$in': SEEDED_IDS}})


def _stored(groups: Any) -> dict[int, dict[str, Any]]:
    """The seeded groups as stored, by public_id"""
    return {document[PUBLIC_ID]: document for document in groups.find({PUBLIC_ID: {'$in': SEEDED_IDS}}, {'_id': 0})}


def test_the_removed_rights_leave_and_the_kept_ones_stay_in_order(groups, database_manager, database_name) -> None:
    """Only the ten names go; nothing else of the group changes"""
    before: dict[int, dict[str, Any]] = _stored(groups)

    Update20261113(database_manager, database_name).start_update()

    after: dict[int, dict[str, Any]] = _stored(groups)
    assert after[MIXED_GROUP_ID] == {**before[MIXED_GROUP_ID], RIGHTS: KEPT_RIGHTS}


def test_a_wildcard_and_a_group_without_a_removed_right_stay(groups, database_manager, database_name) -> None:
    """The family wildcards are not removed rights"""
    before: dict[int, dict[str, Any]] = _stored(groups)

    Update20261113(database_manager, database_name).start_update()

    after: dict[int, dict[str, Any]] = _stored(groups)
    assert after[WILDCARD_GROUP_ID] == before[WILDCARD_GROUP_ID]
    assert after[CLEAN_GROUP_ID] == before[CLEAN_GROUP_ID]


def test_a_second_run_changes_nothing(groups, database_manager, database_name) -> None:
    """Re-run safe"""
    Update20261113(database_manager, database_name).start_update()
    first: dict[int, dict[str, Any]] = _stored(groups)

    Update20261113(database_manager, database_name).start_update()

    assert _stored(groups) == first
