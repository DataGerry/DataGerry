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
Integration tests for the user-update guard against a real MongoDB

The route's two collaborators, run on real data: `route_utils.user_has_right` asks the seeded groups through the
request's GroupsManager (the admin group holds the user edit right, the "user" group does not), and
`complete_user_update` + `guard_user_update` feed a real `UsersManager.update_user` - so what these pin is the
stored document after an update, not a dict in memory. The password digest in particular is only worth anything if
it is still in the collection afterwards
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.users_manager import UsersManager
from cmdb.models.user_model import CmdbUser, CmdbUserKey
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID, USER_GROUP_ID
from cmdb.interface.rest_api.routes.user_management_routes.users_constants import UserAccessRight
from cmdb.interface.route_utils import user_has_right
from cmdb.interface.rest_api.routes.user_management_routes.users_helper import (
    complete_user_update,
    guard_user_update,
)
# -------------------------------------------------------------------------------------------------------------------- #

USER_ID: int = 9721
STORED_DIGEST: str = 'integration-digest'
TENANT: str = 'integration-tenant'


@pytest.fixture(name='users_manager')
def fixture_users_manager(database_manager: MongoDatabaseManager) -> UsersManager:
    """A UsersManager wired to the test database."""
    return UsersManager(database_manager)


@pytest.fixture(name='stored_user')
def fixture_stored_user(database_manager: MongoDatabaseManager, database_name: str, users_manager: UsersManager):
    """Stores a local "user"-group account with a digest and a tenant; yields it as read back."""
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    users.delete_many({'public_id': USER_ID})
    users.insert_one({
        'public_id': USER_ID,
        'user_name': 'guarded-user',
        'active': True,
        'group_id': USER_GROUP_ID,
        'registration_time': datetime.now(timezone.utc),
        'database': TENANT,
        'password': STORED_DIGEST,
    })
    yield users_manager.get_user(USER_ID)
    users.delete_many({'public_id': USER_ID})


def _save(users_manager: UsersManager, stored_user: CmdbUser, data: dict[str, Any], may_administer: bool) -> CmdbUser:
    """The route's write path: complete, guard, rebuild, store - then the user as the database now holds it."""
    data = complete_user_update(data, stored_user)
    guard_user_update(stored_user, data, may_administer=may_administer)
    data[CmdbUserKey.PUBLIC_ID.value] = USER_ID
    users_manager.update_user(USER_ID, CmdbUser.from_data(data))

    return users_manager.get_user(USER_ID)


def _sent_back(stored_user: CmdbUser, **overrides: Any) -> dict[str, Any]:
    """The public document a client reads, edited - without the digest and the wire-shaped date."""
    document: dict[str, Any] = CmdbUser.to_public_json(stored_user)
    document.pop(CmdbUserKey.REGISTRATION_TIME.value)

    return {**document, **overrides}


@pytest.mark.usefixtures('rest_api_app_context')
class TestHoldsRightOnTheSeededGroups:
    """The fixed groups decide who is an administrator of users"""

    def test_the_admin_group_holds_the_edit_right(self) -> None:
        """An admin-group user may change administrative fields"""
        admin = CmdbUser(public_id=1, user_name='admin', active=True, group_id=ADMIN_GROUP_ID)

        assert user_has_right(UserAccessRight.EDIT.value, admin) is True

    def test_the_user_group_does_not(self) -> None:
        """A "user"-group account reaches the update only through the self-edit carve-out"""
        user = CmdbUser(public_id=USER_ID, user_name='u', active=True, group_id=USER_GROUP_ID)

        assert user_has_right(UserAccessRight.EDIT.value, user) is False


class TestTheStoredDocumentAfterAnUpdate:
    """What survives in the collection once an update has gone through the guard"""

    def test_a_profile_edit_keeps_the_digest_and_the_tenant(
            self, users_manager: UsersManager, stored_user: CmdbUser) -> None:
        """The body never carries the digest; the stored one is still there afterwards"""
        saved = _save(users_manager, stored_user, _sent_back(stored_user, first_name='Edited'),
                      may_administer=False)

        assert saved.first_name == 'Edited'
        assert saved.password == STORED_DIGEST
        assert saved.database == TENANT
        assert saved.group_id == USER_GROUP_ID

    def test_a_body_that_leaves_the_guarded_fields_out_does_not_reset_them(
            self, users_manager: UsersManager, stored_user: CmdbUser) -> None:
        """A minimal body keeps group, tenant, digest and registration - none falls back to its default"""
        minimal: dict[str, Any] = {CmdbUserKey.FIRST_NAME.value: 'Renamed'}

        saved = _save(users_manager, stored_user, minimal, may_administer=False)

        assert (saved.group_id, saved.database, saved.password) == (USER_GROUP_ID, TENANT, STORED_DIGEST)
        assert (saved.user_name, saved.active, saved.first_name) == (stored_user.user_name, True, 'Renamed')
        assert saved.registration_time == stored_user.registration_time

    def test_an_administrator_changes_the_group_and_nothing_else_moves(
            self, users_manager: UsersManager, stored_user: CmdbUser) -> None:
        """The right unlocks the group; the digest and the tenant stay as they were"""
        saved = _save(users_manager, stored_user, _sent_back(stored_user, group_id=ADMIN_GROUP_ID),
                      may_administer=True)

        assert saved.group_id == ADMIN_GROUP_ID
        assert (saved.database, saved.password) == (TENANT, STORED_DIGEST)
