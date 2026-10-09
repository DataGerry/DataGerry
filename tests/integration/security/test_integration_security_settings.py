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
Integration tests for the ``security`` settings document against MongoDB, on premise

SecurityManager and KeyHolder read and write it through ``security_settings`` and hold no SettingsManager. The symmetric
key tests run on a throwaway database: generating a key in the suite's own database would invalidate every password
digest the other tests store. KeyHolder reads the default database's keypair, which the test session seeds - read only
"""
import os

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import SecurityManager
from cmdb.manager.system_manager.settings_manager import SettingsManager
from cmdb.security.key.holder import KeyHolder
from cmdb.security.key.secret_resolver import ASYMMETRIC_KEY_SETTING, SECURITY_SECTION, SYMMETRIC_KEY_SETTING
from cmdb.security.key.security_settings import read_security_setting, write_security_setting
# -------------------------------------------------------------------------------------------------------------------- #

THROWAWAY_DATABASE: str = f'itest_security_settings_{os.getpid()}'
PASSWORD: str = 'correct-horse'
OTHER_SETTING: str = 'itest_other_value'


@pytest.fixture(name='on_premise')
def fixture_on_premise(rest_api, monkeypatch: pytest.MonkeyPatch):
    """The REST app's context, on premise - the only mode that reads the stored document"""
    monkeypatch.setattr(rest_api.application, 'cloud_mode', False)

    with rest_api.application.app_context():
        yield


@pytest.fixture(name='throwaway')
def fixture_throwaway(database_manager: MongoDatabaseManager):
    """A database with no security document yet, dropped afterwards"""
    client = database_manager.connector.client
    client.drop_database(THROWAWAY_DATABASE)

    yield THROWAWAY_DATABASE

    client.drop_database(THROWAWAY_DATABASE)


@pytest.mark.usefixtures('on_premise')
def test_the_first_use_generates_the_key_and_later_managers_read_it(
        database_manager: MongoDatabaseManager, throwaway: str) -> None:
    """Generated once into the document; a second manager reads the same key, so digests stay comparable"""
    first = SecurityManager(database_manager, throwaway)
    digest: str = first.generate_hmac(PASSWORD)
    stored_key = read_security_setting(database_manager, throwaway, SYMMETRIC_KEY_SETTING)

    assert stored_key
    assert SecurityManager(database_manager, throwaway).generate_hmac(PASSWORD) == digest
    assert SecurityManager(database_manager, throwaway).get_symmetric_aes_key() == stored_key


@pytest.mark.usefixtures('on_premise')
def test_the_document_is_the_one_the_settings_manager_reads(
        database_manager: MongoDatabaseManager, throwaway: str) -> None:
    """Same collection, same _id: nothing else that reads settings sees a different document"""
    SecurityManager(database_manager, throwaway).generate_symmetric_aes_key()

    assert SettingsManager(database_manager, throwaway).get_value(SYMMETRIC_KEY_SETTING, SECURITY_SECTION) == \
        read_security_setting(database_manager, throwaway, SYMMETRIC_KEY_SETTING)


@pytest.mark.usefixtures('on_premise')
def test_a_write_keeps_the_other_keys_of_the_document(database_manager: MongoDatabaseManager, throwaway: str) -> None:
    """A $set upsert: regenerating the AES key must not drop the keypair stored beside it"""
    write_security_setting(database_manager, throwaway, {OTHER_SETTING: 'kept'})

    SecurityManager(database_manager, throwaway).generate_symmetric_aes_key()

    assert read_security_setting(database_manager, throwaway, OTHER_SETTING) == 'kept'
    assert read_security_setting(database_manager, throwaway, SYMMETRIC_KEY_SETTING)


@pytest.mark.usefixtures('on_premise')
def test_the_key_holder_reads_the_stored_keypair(database_manager: MongoDatabaseManager) -> None:
    """Both halves are the ones the session stored, read through the same document"""
    stored = SettingsManager(database_manager).get_value(ASYMMETRIC_KEY_SETTING, SECURITY_SECTION)
    holder = KeyHolder(database_manager)

    assert holder.rsa_public == stored['public']
    assert holder.rsa_private == stored['private']
