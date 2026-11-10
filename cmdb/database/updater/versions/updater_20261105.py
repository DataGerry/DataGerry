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
Database update 20261105: an object relation names each of its fields once

The field cascade of a relation definition update appended an empty entry for every field it took for new, also to
an instance that already held a value under that name - so a stored instance can name a field twice, which its own
write refuses. This update keeps the FIRST entry of each name (the value the instance held before the cascade) and
drops the later ones, in one pipeline update over the instances that repeat a name.

Re-run safe: only an instance whose ``field_values`` repeats a name is matched, and the rewrite leaves every name
once - a second run matches nothing
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The literals of this migration are frozen: it must keep meaning what it meant when it shipped
OBJECT_RELATIONS_COLLECTION: str = 'framework.objectRelations'
FIELD_VALUES_FIELD: str = 'field_values'
FIELD_NAME_KEY: str = 'name'
ARRAY_BSON_TYPE: str = 'array'

# The names an instance holds, a missing list read as empty
_HELD_NAMES: dict[str, Any] = {'$ifNull': [f'${FIELD_VALUES_FIELD}.{FIELD_NAME_KEY}', []]}

# The instances the update rewrites: a field_values list naming some field more than once
REPEATED_NAME_CRITERIA: dict[str, Any] = {
    FIELD_VALUES_FIELD: {'$type': ARRAY_BSON_TYPE},
    '$expr': {'$ne': [{'$size': _HELD_NAMES}, {'$size': {'$setUnion': [_HELD_NAMES, []]}}]},
}

# One write: walk the entries in order and keep an entry only while its name is not kept yet
FIRST_ENTRY_PER_NAME_REWRITE: list[dict[str, Any]] = [
    {'$set': {FIELD_VALUES_FIELD: {'$reduce': {
        'input': f'${FIELD_VALUES_FIELD}',
        'initialValue': [],
        'in': {'$cond': [
            {'$in': [f'$$this.{FIELD_NAME_KEY}', f'$$value.{FIELD_NAME_KEY}']},
            '$$value',
            {'$concatArrays': ['$$value', ['$$this']]},
        ]},
    }}}},
]

# ---------------------------------------------- Update20261105 - CLASS ---------------------------------------------- #

class Update20261105(BaseDatabaseUpdate):
    """
    Drops the repeated field entries of the stored object relations, keeping the first of each name

    Extends: BaseDatabaseUpdate
    """
    def creation_date(self) -> int:
        return 20261105


    def description(self) -> str:
        return "Keeps one field value per field name on every object relation"


    def start_update(self) -> None:
        """
        Rewrites the object relations that repeat a field name, then bumps the version

        Raises:
            UpdaterException: If the rewrite fails
        """
        try:
            rewritten: int = self.dbm.update_many_raw(
                OBJECT_RELATIONS_COLLECTION, self.db_name, REPEATED_NAME_CRITERIA, FIRST_ENTRY_PER_NAME_REWRITE,
            ).modified_count

            if rewritten:
                LOGGER.info("[updater_20261105] Removed repeated field values from %s object relation(s)", rewritten)

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(err) from err
