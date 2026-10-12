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
Database update 20261011: strip the stored user and group names the name rule refuses

Since this version a user's ``user_name`` and a group's ``name`` must not be blank, start or end with whitespace,
or hold a control character (``cmdb.utils.name_shape_problem``). Every login is stripped before it is looked up,
so a user stored as ``' bob '`` could not log in under any spelling, and every later save of a stored bad name is
refused by the write rule - the whole document is always sent.

This update repairs what stripping alone repairs: ``' bob '`` becomes ``'bob'``, unless another document already
holds ``'bob'``. Whatever it cannot repair - a blank name, a name with a control character, a stripped name that
is taken - is left as it is and logged by collection and public_id, for an administrator to rename.

Users and groups are few, so every name is read (projected) and judged here rather than in a query: a MongoDB
regex's whitespace class misses the Unicode whitespace ``str.strip`` removes. Each repair is one update conditioned
on the name it read, and the unique index refuses a clash a concurrent write made. Re-run safe: a repaired name is
clean and is not touched again; an unrepairable one is logged again
"""
import unicodedata
from logging import Logger, getLogger
from typing import Any

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.errors.database import DocumentDuplicateKeyError
from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The literals and the rule of this migration are frozen: it must keep meaning what it meant when it shipped
USER_COLLECTION: str = 'management.users'
USER_NAME_FIELD: str = 'user_name'
GROUP_COLLECTION: str = 'management.groups'
GROUP_NAME_FIELD: str = 'name'
PUBLIC_ID_FIELD: str = 'public_id'
CONTROL_CHARACTER_CATEGORY: str = 'Cc'

# Every collection whose name field this update repairs, with that field
NAME_FIELDS: tuple[tuple[str, str], ...] = (
    (USER_COLLECTION, USER_NAME_FIELD),
    (GROUP_COLLECTION, GROUP_NAME_FIELD),
)


def is_clean_name(name: Any) -> bool:
    """
    Answers whether a stored name follows the name rule as it shipped with this update

    Args:
        name (Any): The stored value

    Returns:
        bool: True for a non-blank string without surrounding whitespace or control characters
    """
    return (
        isinstance(name, str)
        and bool(name)
        and name == name.strip()
        and not any(unicodedata.category(character) == CONTROL_CHARACTER_CATEGORY for character in name)
    )


def repaired_name(name: Any) -> str | None:
    """
    Answers the name stripping alone turns a stored name into, when that is a clean name

    Args:
        name (Any): The stored value, known not to be clean

    Returns:
        str | None: The stripped name; None when stripping does not make it clean (blank, a control
            character inside, or no string at all)
    """
    if not isinstance(name, str):
        return None

    stripped: str = name.strip()

    return stripped if is_clean_name(stripped) else None


class Update20261011(BaseDatabaseUpdate):
    """
    Strips the stored user and group names the name rule refuses, where stripping is enough and the result is free

    Extends: BaseDatabaseUpdate
    """
    def creation_date(self) -> int:
        return 20261011


    def description(self) -> str:
        return "Strips stored user and group names that start or end with whitespace"


    def start_update(self) -> None:
        """
        Repairs every collection's names, then bumps the version

        Raises:
            UpdaterException: If a read or a write failed for another reason than a taken name
        """
        try:
            for collection, field in NAME_FIELDS:
                self.repair_names(collection, field)

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(err) from err


    def repair_names(self, collection: str, field: str) -> None:
        """
        Reads every name of one collection and repairs or logs each one the rule refuses

        Args:
            collection (str): The collection holding the names
            field (str): The name field
        """
        documents: list[dict[str, Any]] = list(self.dbm.find(
            collection=collection,
            db_name=self.db_name,
            filter={},
            projection={PUBLIC_ID_FIELD: 1, field: 1, '_id': 0},
        ))

        for document in documents:
            name: Any = document.get(field)

            if is_clean_name(name):
                continue

            repaired: str | None = repaired_name(name)

            if repaired is None:
                LOGGER.warning("[Update20261011] '%s' %s %s: %r cannot be repaired by stripping - an administrator "
                               "must rename it", collection, PUBLIC_ID_FIELD, document.get(PUBLIC_ID_FIELD), name)
                continue

            self.repair_name(collection, field, document.get(PUBLIC_ID_FIELD), name, repaired)


    def repair_name(self, collection: str, field: str, public_id: Any, name: str, repaired: str) -> None:
        """
        Stores the stripped name of one document, unless another document already holds it

        The update is conditioned on the name that was read, so a name changed since is left alone

        Args:
            collection (str): The collection holding the document
            field (str): The name field
            public_id (Any): The document's public_id
            name (str): The stored name, as read
            repaired (str): The stripped name to store

        Raises:
            DocumentGetError | DocumentUpdateError: When the read or the write failed for another reason than a
                taken name
        """
        if self.dbm.count(collection, self.db_name, {field: repaired}, limit=1):
            self._log_taken(collection, public_id, name, repaired)
            return

        try:
            self.dbm.update(collection, self.db_name, {PUBLIC_ID_FIELD: public_id, field: name}, {field: repaired})
        except DocumentDuplicateKeyError:
            # A concurrent write took the stripped name between the count and the update
            self._log_taken(collection, public_id, name, repaired)


    @staticmethod
    def _log_taken(collection: str, public_id: Any, name: str, repaired: str) -> None:
        """
        Logs a name left padded because its stripped form is taken

        Args:
            collection (str): The collection holding the document
            public_id (Any): The document's public_id
            name (str): The stored name
            repaired (str): Its stripped form, held by another document
        """
        LOGGER.warning("[Update20261011] '%s' %s %s: %r is left as it is - %r is taken; an administrator must "
                       "rename it", collection, PUBLIC_ID_FIELD, public_id, name, repaired)
