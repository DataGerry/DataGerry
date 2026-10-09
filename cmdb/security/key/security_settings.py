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
The ``security`` settings document: where an on-premise installation stores its key material

One document of the settings collection (``_id`` 'security') holds the symmetric AES key that keys the password HMAC
and the RSA keypair that signs tokens. ``SecurityManager`` and ``KeyHolder`` read and write it through these two
functions rather than each holding a ``SettingsManager`` - a manager holds no other manager, and the document is the
key package's, next to the rules that decide when it is consulted at all (``secret_resolver``: only on premise).

The two functions do exactly what ``SettingsManager.get_value`` / ``write`` do on that document - one ``find_one_by`` by
``_id``, one ``$set`` upsert - so the storage is unchanged and anything else reading the settings collection sees the
same document. The collection name and id key are spelled here rather than imported: ``cmdb.manager`` imports this
package, so importing it back would close the cycle ``secret_resolver`` already avoids. A unit test pins that the names
agree with ``SettingsManager``'s.
"""
from typing import Any

from pymongo.results import UpdateResult

from cmdb.database import MongoDatabaseManager
from cmdb.security.key.secret_resolver import SECURITY_SECTION
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'SETTINGS_COLLECTION',
    'SETTINGS_SECTION_ID_KEY',
    'read_security_setting',
    'write_security_setting',
]

# The settings collection and the key a section is addressed by - SettingsManager.COLLECTION / SETTINGS_SECTION_ID_KEY
SETTINGS_COLLECTION: str = 'settings.conf'
SETTINGS_SECTION_ID_KEY: str = '_id'


def read_security_setting(dbm: MongoDatabaseManager, database: str | None, key: str) -> Any:
    """
    Reads one value of the ``security`` settings document

    Args:
        dbm (MongoDatabaseManager): The database manager
        database (str | None): The database to read; None is the manager's default database
        key (str): The value's key within the section (``SYMMETRIC_KEY_SETTING`` / ``ASYMMETRIC_KEY_SETTING``)

    Returns:
        Any: The stored value, or None when the document or the key does not exist
    """
    section: dict[str, Any] | None = dbm.find_one_by(
        collection=SETTINGS_COLLECTION,
        db_name=database,
        filter={SETTINGS_SECTION_ID_KEY: SECURITY_SECTION},
    )

    return section.get(key) if section else None


def write_security_setting(dbm: MongoDatabaseManager, database: str | None, values: dict[str, Any]) -> UpdateResult:
    """
    Writes values into the ``security`` settings document, creating it when absent

    A ``$set`` upsert: the given keys are set, every other key of the document is kept

    Args:
        dbm (MongoDatabaseManager): The database manager
        database (str | None): The database to write; None is the manager's default database
        values (dict[str, Any]): The keys and values to set

    Returns:
        UpdateResult: The result of the upsert
    """
    return dbm.update(
        collection=SETTINGS_COLLECTION,
        db_name=database,
        criteria={SETTINGS_SECTION_ID_KEY: SECURITY_SECTION},
        data=values,
        upsert=True,
    )
