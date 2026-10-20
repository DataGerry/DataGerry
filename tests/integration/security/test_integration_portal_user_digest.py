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
Integration tests, against a real MongoDB: the tenant user created from a portal answer stores a usable digest

``check_user_in_service_portal`` answers the password as its HMAC, and ``set_admin_user`` stores that value as
given - so the stored digest is the one the user's own password produces, and a local check of that password
matches it. Hashing the handed digest a second time stored a value no password could ever match
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import SecurityManager
from cmdb.models.user_model import CmdbUser
from cmdb.interface.route_utils import set_admin_user
from tests.utils.service_portal_answers import portal_login_answer, portal_subscription
# -------------------------------------------------------------------------------------------------------------------- #

PORTAL_EMAIL: str = 'portal-digest@acme.test'
PORTAL_USER_NAME: str = 'portal-digest'
PORTAL_PASSWORD: str = 'the-portal-password'


@pytest.fixture(name='users')
def fixture_users(rest_api, database_manager: MongoDatabaseManager, database_name: str):
    """The users collection of the test database, inside an app context, the portal user removed around the test"""
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    users.delete_many({'email': PORTAL_EMAIL})

    with rest_api.application.app_context():
        yield users

    users.delete_many({'email': PORTAL_EMAIL})


def test_a_created_portal_user_stores_the_digest_of_its_own_password(
        users: Any, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """The stored value is HMAC(password) - what a local check of that password computes"""
    security_manager = SecurityManager(database_manager, database_name)
    answer: dict[str, Any] = portal_login_answer(
        PORTAL_EMAIL, PORTAL_USER_NAME, security_manager.generate_hmac(PORTAL_PASSWORD),
        [portal_subscription(database_name)],
    )

    set_admin_user(answer, answer['subscriptions'][0])

    stored: dict[str, Any] = users.find_one({'email': PORTAL_EMAIL})
    assert stored['password'] == security_manager.generate_hmac(PORTAL_PASSWORD)


def test_a_refresh_leaves_the_stored_digest_alone(
        users: Any, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """The second login refreshes the subscription fields, never the password"""
    security_manager = SecurityManager(database_manager, database_name)
    answer: dict[str, Any] = portal_login_answer(
        PORTAL_EMAIL, PORTAL_USER_NAME, security_manager.generate_hmac(PORTAL_PASSWORD),
        [portal_subscription(database_name)],
    )
    set_admin_user(answer, answer['subscriptions'][0])
    first: str = users.find_one({'email': PORTAL_EMAIL})['password']

    set_admin_user({**answer, 'password': 'a-different-digest'}, answer['subscriptions'][0])

    assert users.find_one({'email': PORTAL_EMAIL})['password'] == first
