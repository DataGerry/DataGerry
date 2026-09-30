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
Integration tests for a deactivated tenant account against the real cloud user resolution

Both cloud paths - the login and a Basic + `x-api-key` request - first run `set_admin_user` (which
refreshes the tenant's copy of the portal user) and then `retrieve_user`, and refuse the result
with `refuse_inactive_user`. Against a real stored user this shows what the unit tests cannot: the
refresh never re-activates the account, so the flag the tenant stored is still the one refused
"""
from datetime import datetime, timezone
from typing import Any

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.database import MongoDatabaseManager
from cmdb.models.user_model import CmdbUser
from cmdb.interface.route_utils import (
    USER_DEACTIVATED_MESSAGE,
    refuse_inactive_user,
    retrieve_user,
    set_admin_user,
)
# -------------------------------------------------------------------------------------------------------------------- #

USER_ID: int = 93996
EMAIL: str = 'deactivated-tenant@x.io'
API_LEVEL: int = 2
CONFIG_ITEMS_LIMIT: int = 25


@pytest.fixture(name='portal_user')
def fixture_portal_user(rest_api, database_manager: MongoDatabaseManager, database_name: str):
    """Stores a deactivated tenant user; yields the portal payload for it inside an app context."""
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    users.delete_many({'public_id': USER_ID})
    users.insert_one({
        'public_id': USER_ID, 'user_name': 'deactivated-tenant', 'email': EMAIL, 'active': False,
        'group_id': 1, 'database': database_name, 'api_level': 1,
        'registration_time': datetime.now(timezone.utc),
    })

    portal: dict[str, Any] = {
        'email': EMAIL, 'user_name': 'deactivated-tenant', 'password': 'pw',
        'subscriptions': [{'id': 1, 'name': 'sub', 'database': database_name, 'api_level': API_LEVEL,
                           'config_item_limit': CONFIG_ITEMS_LIMIT}],
    }

    with rest_api.application.app_context():
        yield portal

    users.delete_many({'public_id': USER_ID})


def test_the_refresh_keeps_the_account_deactivated(portal_user: dict[str, Any], database_name: str) -> None:
    """set_admin_user rewrites the subscription values and leaves `active` as the tenant stored it"""
    set_admin_user(portal_user, portal_user['subscriptions'][0])

    user: CmdbUser = retrieve_user(portal_user, database_name)

    assert user.public_id == USER_ID
    assert user.api_level == API_LEVEL
    assert user.active is False


def test_the_resolved_deactivated_user_is_refused(portal_user: dict[str, Any], database_name: str) -> None:
    """What both cloud paths run on that result: a 401 naming the deactivation"""
    set_admin_user(portal_user, portal_user['subscriptions'][0])

    with pytest.raises(HTTPException) as refused:
        refuse_inactive_user(retrieve_user(portal_user, database_name))

    assert refused.value.code == 401
    assert refused.value.description == USER_DEACTIVATED_MESSAGE
