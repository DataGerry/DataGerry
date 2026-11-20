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

# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""
Integration tests of the user sync right against a real MongoDB

Pinned: a user group stored with ``base.user-management.sync.edit`` (or its wildcard) is read back holding it -
the stored name resolves to the catalogue's right instead of being dropped as unknown - and the seeded
administrator group, which holds ``base.*``, is granted it without a stored copy
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.groups_manager import GroupsManager
from cmdb.models.group_model import ADMIN_GROUP_ID, CmdbUserGroup
# -------------------------------------------------------------------------------------------------------------------- #

SYNC_EDIT: str = 'base.user-management.sync.edit'
SYNC_WILDCARD: str = 'base.user-management.sync.*'
GROUP_ID: int = 9831


@pytest.fixture(name='groups_manager')
def fixture_groups_manager(database_manager: MongoDatabaseManager, database_name: str):
    """A GroupsManager on the test database; the group this module stores is removed afterwards"""
    yield GroupsManager(database_manager)

    database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name).delete_many({'public_id': GROUP_ID})


def _group_data(rights: list[str]) -> dict[str, Any]:
    """A user group payload holding the given rights"""
    return {'public_id': GROUP_ID, 'name': f'group-{GROUP_ID}', 'label': 'Sync right', 'rights': rights}


@pytest.mark.parametrize('stored', [SYNC_EDIT, SYNC_WILDCARD])
def test_a_stored_sync_right_is_read_back(groups_manager: GroupsManager, stored: str) -> None:
    """The name resolves to the catalogue's right, and the group is granted the sync right"""
    groups_manager.insert_group(_group_data([stored]))

    group: CmdbUserGroup | None = groups_manager.get_group(GROUP_ID)

    assert group is not None
    assert [right.name for right in group.rights] == [stored]
    assert group.has_right(SYNC_EDIT) or group.has_extended_right(SYNC_EDIT)


def test_the_administrators_hold_it_through_the_master_right(groups_manager: GroupsManager) -> None:
    """No updater is needed: ``base.*`` grants every right below it"""
    admins: CmdbUserGroup | None = groups_manager.get_group(ADMIN_GROUP_ID)

    assert admins is not None
    assert not admins.has_right(SYNC_EDIT)
    assert admins.has_extended_right(SYNC_EDIT)
