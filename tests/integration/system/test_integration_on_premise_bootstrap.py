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
Integration tests for what ``bring_database_up_to_date(on_premise=...)`` seeds into a new database, against MongoDB

``on_premise`` - formerly ``local_mode``, which on the app means the opposite (the cloud product on a developer
machine) - decides two things for a database the call creates: the installation's keys (the RSA keypair and the
HMAC key, in the ``security`` settings) and the default admin user. The on-premise boot passes True; the cloud
product's tenants pass nothing and get neither - their keys come from the environment or the app, their first user
from the service portal.

A database manager is bound to a throwaway database, because the keys are written to a manager's DEFAULT database:
built on the suite's own manager, the on-premise case would overwrite the session's keypair
"""
import os
from typing import Iterator

import pytest
from flask import Flask

from cmdb.database import MongoDatabaseManager
from cmdb.interface.rest_api.init_rest_api import bring_database_up_to_date
from cmdb.models.user_model import CmdbUser
from cmdb.security.key.holder import PRIVATE_HALF, PUBLIC_HALF
from cmdb.security.key.secret_resolver import ASYMMETRIC_KEY_SETTING, SYMMETRIC_KEY_SETTING
from cmdb.security.key.security_settings import read_security_setting
# -------------------------------------------------------------------------------------------------------------------- #

BOOTSTRAP_DATABASE: str = f'itest_bootstrap_{os.getpid()}'
DEFAULT_ADMIN_NAME: str = 'admin'


def _on_premise_app() -> Flask:
    """An on-premise app context: the admin's password digest is keyed with the stored HMAC key"""
    app = Flask(__name__)
    app.cloud_mode = False
    app.local_mode = False

    return app


@pytest.fixture(name='bootstrap_dbm')
def fixture_bootstrap_dbm(mongodb_parameters: tuple) -> Iterator[MongoDatabaseManager]:
    """A database manager whose default database is a throwaway that does not exist yet; dropped afterwards"""
    host, port, _database = mongodb_parameters
    dbm = MongoDatabaseManager(host, port, BOOTSTRAP_DATABASE)
    dbm.connector.client.drop_database(BOOTSTRAP_DATABASE)

    yield dbm

    dbm.connector.client.drop_database(BOOTSTRAP_DATABASE)


def _users(dbm: MongoDatabaseManager) -> list[dict]:
    """The stored users of the throwaway database"""
    return list(dbm.get_collection(CmdbUser.COLLECTION, BOOTSTRAP_DATABASE).find({}))


def test_the_on_premise_boot_seeds_the_keys_and_the_admin(bootstrap_dbm: MongoDatabaseManager) -> None:
    """A database the on-premise boot creates is one an administrator can log into"""
    with _on_premise_app().app_context():
        bring_database_up_to_date(bootstrap_dbm, BOOTSTRAP_DATABASE, on_premise=True)

    keypair = read_security_setting(bootstrap_dbm, None, ASYMMETRIC_KEY_SETTING)

    assert keypair[PUBLIC_HALF] and keypair[PRIVATE_HALF]
    assert read_security_setting(bootstrap_dbm, None, SYMMETRIC_KEY_SETTING)
    assert [user['user_name'] for user in _users(bootstrap_dbm)] == [DEFAULT_ADMIN_NAME]


def test_a_cloud_tenant_gets_neither(bootstrap_dbm: MongoDatabaseManager) -> None:
    """The default: no keys - the cloud product never reads them from a database - and no admin/admin account"""
    with _on_premise_app().app_context():
        bring_database_up_to_date(bootstrap_dbm, BOOTSTRAP_DATABASE)

    assert read_security_setting(bootstrap_dbm, None, ASYMMETRIC_KEY_SETTING) is None
    assert read_security_setting(bootstrap_dbm, None, SYMMETRIC_KEY_SETTING) is None
    assert not _users(bootstrap_dbm)
