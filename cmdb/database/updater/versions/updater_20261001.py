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
Database update 20261001: stores every CmdbType's ``acl.activated`` as a real boolean

The type write schema accepts only a boolean ``activated``, but a CmdbType written before it may carry any value
there - ``"yes"``, ``0``, ``""``. Two readers decide on that value and they read a non-boolean differently: the
single read (``acl_grants_access``) takes the value's truthiness, the listing query matched "present and not
False / None". For ``0`` and ``""`` the single read said "off" and the listing said "on", so a listing hid the
objects a direct read granted.

Each such value is rewritten to the boolean the single read already decided on (Python truthiness), so no single
read changes its answer and the listing joins it. That is what lets the listing query test ``activated: True``.
An absent or null ``activated`` is left alone: both readers already read it as "off".

Idempotent by construction: the selection matches only a value that is neither a boolean nor null, and every
write stores a boolean, so a second run selects nothing
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.models.type_model import TypeSchemaKey
from cmdb.security.acl.acl_constants import AclKey

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The dotted path of the flag inside a stored CmdbType
ACL_ACTIVATED_PATH: str = f'{TypeSchemaKey.ACL.value}.{AclKey.ACTIVATED.value}'

# The BSON types a stored flag may already have: a boolean is the target, a null reads as "off" either way
SETTLED_ACTIVATED_TYPES: list[str] = ['bool', 'null']

# A stored flag that is not yet a boolean
NON_BOOLEAN_ACTIVATED_CRITERIA: dict[str, Any] = {
    ACL_ACTIVATED_PATH: {'$exists': True, '$not': {'$type': SETTLED_ACTIVATED_TYPES}},
}

# Only what the rewrite needs to know
ACTIVATED_PROJECTION: dict[str, int] = {TypeSchemaKey.PUBLIC_ID.value: 1, ACL_ACTIVATED_PATH: 1, '_id': 0}


def ids_by_reading(documents: list[dict[str, Any]]) -> dict[bool, list[int]]:
    """
    Groups the selected CmdbTypes by the boolean their stored flag reads as

    Args:
        documents (list[dict[str, Any]]): The selected types, projected to ``public_id`` and ``acl.activated``

    Returns:
        dict[bool, list[int]]: True / False -> the public_ids whose flag reads that way, sorted
    """
    grouped: dict[bool, list[int]] = {True: [], False: []}

    for document in documents:
        stored: Any = (document.get(TypeSchemaKey.ACL.value) or {}).get(AclKey.ACTIVATED.value)
        grouped[bool(stored)].append(document[TypeSchemaKey.PUBLIC_ID.value])

    return {reading: sorted(public_ids) for reading, public_ids in grouped.items()}

# -------------------------------------------------------------------------------------------------------------------- #
#                                                Update20261001 - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class Update20261001(BaseDatabaseUpdate):
    """
    Rewrites every non-boolean ``acl.activated`` to the boolean the single read decides on

    Extends: BaseDatabaseUpdate
    """
    def creation_date(self) -> int:
        return 20261001


    def description(self) -> str:
        return "Stores every Type's 'acl.activated' as a real boolean"


    def start_update(self) -> None:
        """
        Reads the types whose flag is no boolean, writes one boolean per reading, then bumps the version

        Raises:
            UpdaterException: If the read or a rewrite failed
        """
        try:
            documents: list[dict[str, Any]] = self.types_manager.find(
                criteria=NON_BOOLEAN_ACTIVATED_CRITERIA, projection=ACTIVATED_PROJECTION,
            )

            for reading, public_ids in ids_by_reading(documents).items():
                if not public_ids:
                    continue

                result = self.types_manager.update_many(
                    criteria={
                        TypeSchemaKey.PUBLIC_ID.value: {'$in': public_ids},
                        **NON_BOOLEAN_ACTIVATED_CRITERIA,
                    },
                    update={ACL_ACTIVATED_PATH: reading},
                )

                LOGGER.info(
                    "[Update20261001] Stored 'acl.activated' as %s on %s Type(s)", reading, result.modified_count,
                )

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(err) from err
