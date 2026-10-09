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
Unit tests for cmdb.security.key.security_settings - the one reader and writer of the ``security`` settings document

The database manager is a MagicMock: what is pinned is the query - the settings collection, the section's ``_id``, the
database passed through as given, a ``$set`` upsert - and that the names agree with SettingsManager's, which the module
spells itself to stay out of an import cycle
"""
from unittest.mock import MagicMock

from cmdb.manager.system_manager.settings_manager import SETTINGS_SECTION_ID_KEY as MANAGER_SECTION_ID_KEY
from cmdb.manager.system_manager.settings_manager import SettingsManager
from cmdb.security.key.secret_resolver import SECURITY_SECTION, SYMMETRIC_KEY_SETTING
from cmdb.security.key.security_settings import (
    SETTINGS_COLLECTION,
    SETTINGS_SECTION_ID_KEY,
    read_security_setting,
    write_security_setting,
)
# -------------------------------------------------------------------------------------------------------------------- #

TENANT_DB: str = 'tenant_db'
STORED_KEY: bytes = b'k' * 32


def test_the_names_agree_with_the_settings_manager() -> None:
    """Spelled here to avoid the cycle - so the two must not drift apart"""
    assert SETTINGS_COLLECTION == SettingsManager.COLLECTION
    assert SETTINGS_SECTION_ID_KEY == MANAGER_SECTION_ID_KEY


def test_a_read_finds_the_security_section_in_the_given_database() -> None:
    """One find_one_by, by _id, in the database passed"""
    dbm = MagicMock()
    dbm.find_one_by.return_value = {'_id': SECURITY_SECTION, SYMMETRIC_KEY_SETTING: STORED_KEY}

    assert read_security_setting(dbm, TENANT_DB, SYMMETRIC_KEY_SETTING) == STORED_KEY
    dbm.find_one_by.assert_called_once_with(
        collection=SETTINGS_COLLECTION, db_name=TENANT_DB, filter={SETTINGS_SECTION_ID_KEY: SECURITY_SECTION},
    )


def test_none_is_the_default_database() -> None:
    """The database manager resolves None to its own default - passed through, not replaced"""
    dbm = MagicMock()
    dbm.find_one_by.return_value = None

    read_security_setting(dbm, None, SYMMETRIC_KEY_SETTING)

    assert dbm.find_one_by.call_args.kwargs['db_name'] is None


def test_a_missing_section_or_key_reads_as_none() -> None:
    """No document, and a document without the key, both answer None - the caller decides what that means"""
    dbm = MagicMock()

    dbm.find_one_by.return_value = None
    assert read_security_setting(dbm, TENANT_DB, SYMMETRIC_KEY_SETTING) is None

    dbm.find_one_by.return_value = {'_id': SECURITY_SECTION}
    assert read_security_setting(dbm, TENANT_DB, SYMMETRIC_KEY_SETTING) is None


def test_a_write_is_an_upsert_of_the_given_keys() -> None:
    """A $set upsert (dbm.update wraps the values) - the first write creates the document, a later one merges"""
    dbm = MagicMock()
    values = {SYMMETRIC_KEY_SETTING: STORED_KEY}

    result = write_security_setting(dbm, TENANT_DB, values)

    assert result is dbm.update.return_value
    dbm.update.assert_called_once_with(
        collection=SETTINGS_COLLECTION, db_name=TENANT_DB, criteria={SETTINGS_SECTION_ID_KEY: SECURITY_SECTION},
        data=values, upsert=True,
    )
