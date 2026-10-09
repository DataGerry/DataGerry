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
Integration test for the right a user needs to reach someone else's settings, against real groups in MongoDB

The settings routes let the owner in by the ``excepted`` carve-out and everyone else only with
``base.user-management.user.edit``. That is safe only while the seeded ``user`` group - every default account -
does not hold that right, directly or through a wildcard; ``base.user-management.user.view``, which it does hold,
must not be enough. Pinned through ``user_has_right``, which reads the group from the database.
"""
from datetime import datetime, timezone

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID, USER_GROUP_ID
from cmdb.models.user_model import CmdbUser
from cmdb.interface.route_utils import user_has_right
from cmdb.interface.rest_api.routes.user_management_routes.user_settings_constants import USER_SETTINGS_RIGHT
# -------------------------------------------------------------------------------------------------------------------- #

USER_VIEW_GROUP_ID: int = 89801
USER_WILDCARD_GROUP_ID: int = 89802
GROUPS: dict[int, list[str]] = {
    USER_VIEW_GROUP_ID: ['base.user-management.user.view'],
    USER_WILDCARD_GROUP_ID: ['base.user-management.user.*'],
}


@pytest.fixture(autouse=True)
def _groups(rest_api, database_manager: MongoDatabaseManager, database_name: str):
    """The groups, inside the request context ManagerProvider resolves through"""
    collection = database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)
    collection.delete_many({'public_id': {'$in': list(GROUPS)}})
    collection.insert_many([{'public_id': group_id, 'name': f'settings-right-{group_id}', 'label': str(group_id),
                             'rights': rights} for group_id, rights in GROUPS.items()])

    with rest_api.application.test_request_context():
        yield

    collection.delete_many({'public_id': {'$in': list(GROUPS)}})


def _member(group_id: int) -> CmdbUser:
    """A member of ``group_id``"""
    return CmdbUser(public_id=group_id, user_name=f'settings-right-{group_id}', active=True, group_id=group_id,
                    registration_time=datetime.now(timezone.utc))


@pytest.mark.parametrize('group_id, holds', [
    (USER_GROUP_ID, False),
    (USER_VIEW_GROUP_ID, False),
    (USER_WILDCARD_GROUP_ID, True),
    (ADMIN_GROUP_ID, True),
], ids=['seeded-user-group', 'user-view-only', 'user-wildcard', 'admin'])
def test_who_reaches_someone_elses_settings(group_id: int, holds: bool) -> None:
    """Only user.edit (or a wildcard above it); never the default group, never user.view"""
    assert user_has_right(USER_SETTINGS_RIGHT, _member(group_id)) is holds
