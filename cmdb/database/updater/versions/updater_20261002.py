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
Database update 20261002: keeps only the right names the right tree knows in every CmdbUserGroup's ``rights``

The group writes accept only strings the right tree holds, but a CmdbUserGroup written before that may carry
anything there. An entry that is not a string is the dangerous one: a dict or a list cannot be hashed, so the group
cannot be read at all - its GET, PUT and DELETE answer 400, and every member is refused every request with a 500,
because each right check reads the group. A string the tree does not know grants nothing and is already dropped
by every read; it is stripped too, so the stored list holds exactly what a write would accept.

Each selected group keeps its known names, in their stored order. A ``rights`` that is not a list at all (only
writable by hand) is reset to an empty list; an absent or null ``rights`` is left alone, every reader treats it as
no rights.

Idempotent by construction: the selection matches only a group holding an entry outside the known names (or a
non-list ``rights``), and every write stores known names only, so a second run selects nothing
"""
from logging import Logger, getLogger
from typing import Any

from pymongo import UpdateOne

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.group_model import CmdbUserGroup, GroupKey
from cmdb.models.right_model.all_rights import ALL_RIGHTS, flat_rights_tree

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# Every right name the right tree holds - the only entries a stored ``rights`` may keep
KNOWN_RIGHT_NAMES: list[str] = sorted({right.name for right in flat_rights_tree(ALL_RIGHTS)})

# The BSON types a stored ``rights`` may have without being reset: a list is the target, a null reads as no rights
SETTLED_RIGHTS_TYPES: list[str] = ['array', 'null']

# A group whose ``rights`` holds an entry outside the known names, or is no list at all
UNREPAIRED_RIGHTS_CRITERIA: dict[str, Any] = {
    '$or': [
        {GroupKey.RIGHTS.value: {'$elemMatch': {'$nin': KNOWN_RIGHT_NAMES}}},
        {GroupKey.RIGHTS.value: {'$exists': True, '$not': {'$type': SETTLED_RIGHTS_TYPES}}},
    ],
}

# Only what the repair needs to know
RIGHTS_PROJECTION: dict[str, int] = {CmdbDAO.PUBLIC_ID_KEY: 1, GroupKey.RIGHTS.value: 1, '_id': 0}


def known_rights_of(stored_rights: Any, known_names: frozenset[str]) -> list[str]:
    """
    The entries of a stored ``rights`` value that a group write would accept

    Args:
        stored_rights (Any): The stored ``rights`` value, whatever its shape
        known_names (frozenset[str]): Every right name the right tree holds

    Returns:
        list[str]: The known right names, in their stored order; empty when the value is no list
    """
    if not isinstance(stored_rights, list):
        return []

    return [entry for entry in stored_rights if isinstance(entry, str) and entry in known_names]

# -------------------------------------------------------------------------------------------------------------------- #
#                                                Update20261002 - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class Update20261002(BaseDatabaseUpdate):
    """
    Strips every entry the right tree does not know from each CmdbUserGroup's ``rights``

    Extends: BaseDatabaseUpdate
    """
    def creation_date(self) -> int:
        return 20261002


    def description(self) -> str:
        return "Keeps only known right names in every user group's 'rights'"


    def start_update(self) -> None:
        """
        Reads the groups holding an unknown entry, writes each one's known names back, then bumps the version

        Raises:
            UpdaterException: If the read or the rewrite failed
        """
        try:
            known_names: frozenset[str] = frozenset(KNOWN_RIGHT_NAMES)

            groups: list[dict[str, Any]] = list(self.dbm.find(
                collection=CmdbUserGroup.COLLECTION,
                db_name=self.db_name,
                filter=UNREPAIRED_RIGHTS_CRITERIA,
                projection=RIGHTS_PROJECTION,
            ))

            operations: list[UpdateOne] = []

            for group in groups:
                public_id: Any = group.get(CmdbDAO.PUBLIC_ID_KEY)
                stored_rights: Any = group.get(GroupKey.RIGHTS.value)
                kept: list[str] = known_rights_of(stored_rights, known_names)

                LOGGER.info(
                    "[Update20261002] UserGroup %s: kept %s right(s), stripped %r",
                    public_id, len(kept), stored_rights if not isinstance(stored_rights, list)
                    else [entry for entry in stored_rights if entry not in kept],
                )

                operations.append(UpdateOne(
                    {CmdbDAO.PUBLIC_ID_KEY: public_id, **UNREPAIRED_RIGHTS_CRITERIA},
                    {'$set': {GroupKey.RIGHTS.value: kept}},
                ))

            if operations:
                self.dbm.bulk_write(CmdbUserGroup.COLLECTION, self.db_name, operations)

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(err) from err
