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
Integration tests for `route_utils.resolve_api_key_user` against a real MongoDB

The real `set_admin_user` wraps every failure in a `UsersManagerInsertError`; with a lost connection under it, the
resolution re-raises the outage itself, so the app answers 503 instead of the old 400. A stored active user is
resolved and brought up to date, a deactivated one is the 401, and an account without a subscription the 401 too
"""
from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.database import MongoDatabaseManager
from cmdb.errors.database import DocumentNetworkError
from cmdb.interface.route_utils import NO_SUBSCRIPTION_MESSAGE, USER_DEACTIVATED_MESSAGE, resolve_api_key_user
from cmdb.manager.users_manager import UsersManager
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

USER_ID: int = 97201
EMAIL: str = 'api-key-resolution@x.io'
API_LEVEL: int = 2


@pytest.fixture(name='portal_user')
def fixture_portal_user(rest_api, database_manager: MongoDatabaseManager, database_name: str):
    """Stores the tenant user; answers a factory of its portal payload, inside the app's context"""
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)

    def store(active: bool) -> dict[str, Any]:
        users.delete_many({'email': EMAIL})
        users.insert_one({
            'public_id': USER_ID, 'user_name': 'api-key-resolution', 'email': EMAIL, 'active': active,
            'group_id': 1, 'database': database_name, 'api_level': 1, 'registration_time': datetime.now(timezone.utc),
        })

        return {'email': EMAIL, 'user_name': 'api-key-resolution', 'password': 'pw', 'api_level': API_LEVEL,
                'subscriptions': [{'id': 1, 'name': 'sub', 'database': database_name, 'api_level': API_LEVEL,
                                   'config_item_limit': 25}]}

    with rest_api.application.app_context():
        yield store

    users.delete_many({'email': EMAIL})


def test_an_active_user_is_resolved_and_brought_up_to_date(portal_user) -> None:
    """The subscription's level is stored on the way"""
    user: CmdbUser = resolve_api_key_user(portal_user(True))

    assert (user.public_id, user.api_level) == (USER_ID, API_LEVEL)


def test_a_deactivated_user_is_a_401(portal_user) -> None:
    """The tenant's flag decides"""
    with pytest.raises(HTTPException) as refused:
        resolve_api_key_user(portal_user(False))

    assert (refused.value.code, refused.value.description) == (401, USER_DEACTIVATED_MESSAGE)


def test_an_outage_under_the_user_sync_is_re_raised_as_itself(portal_user) -> None:
    """The real set_admin_user wraps it into UsersManagerInsertError; the outage is what reaches the app"""
    payload: dict[str, Any] = portal_user(True)

    with patch.object(UsersManager, 'get_user_by', side_effect=DocumentNetworkError('lost')):
        with pytest.raises(DocumentNetworkError):
            resolve_api_key_user(payload)


def test_an_account_without_a_subscription_is_a_401(portal_user) -> None:
    """Nothing to act in"""
    payload: dict[str, Any] = {**portal_user(True), 'subscriptions': []}

    with pytest.raises(HTTPException) as refused:
        resolve_api_key_user(payload)

    assert (refused.value.code, refused.value.description) == (401, NO_SUBSCRIPTION_MESSAGE)
