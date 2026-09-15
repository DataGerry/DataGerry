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
Database update 20260909: no CmdbPerson or CmdbPersonGroup key holds null any more

Both models used to write null for every optional key that the payload did not carry: a person's
``phone_number`` / ``email`` / ``groups``, a group's ``email`` / ``group_members``. Their own Cerberus
schemas type those keys ``string`` and ``list``, so the document the API handed out could not be sent
back unchanged - a GET followed by an unmodified PUT was answered ``400 Invalid data provided!``. On the
group side it was worse than a refusal: the update route reads the stored membership as
``set(document['group_members'])``, and a null there raised ``TypeError`` inside the route's try block,
which surfaced as a 500 that said nothing about what was wrong.

The models now coerce null to the empty string / empty list, and the schemas accept null on the wire so
a client may still say "no value". This migration converges what is already stored, so those documents
stop being the exception:

* ``management.person`` - ``phone_number`` and ``email`` become ``''``, ``groups`` becomes ``[]``
* ``management.personGroup`` - ``email`` becomes ``''``, ``group_members`` becomes ``[]``

A key that was never written at all is filled too, which is what makes the result uniform: after this
runs, every document of both collections carries every key, and none of them is null.

Every literal this module writes or queries is a **local, frozen constant**: a migration is a record of
what was done to a database on a given day, and it has to keep doing exactly that even if the live
models rename their keys later.

Idempotent: the filter of each write matches only the two states being normalised - null and absent - so
a document already carrying an empty value is not touched and a second run modifies nothing. The
version is bumped once both collections are done, so an interrupted run repeats harmlessly
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The collections and, per collection, the keys to normalise onto each empty value. Frozen at
# migration time on purpose - see the module docstring
PERSON_COLLECTION: str = 'management.person'
PERSON_GROUP_COLLECTION: str = 'management.personGroup'

EMPTY_TEXT: str = ''
EMPTY_LIST: list[Any] = []

# collection -> {key: the empty value it should hold instead of null}
NULLABLE_KEYS_BY_COLLECTION: dict[str, dict[str, Any]] = {
    PERSON_COLLECTION: {
        'phone_number': EMPTY_TEXT,
        'email': EMPTY_TEXT,
        'groups': EMPTY_LIST,
    },
    PERSON_GROUP_COLLECTION: {
        'email': EMPTY_TEXT,
        'group_members': EMPTY_LIST,
    },
}


def build_unset_or_null_criteria(key: str) -> dict[str, Any]:
    """
    Builds the filter selecting the documents whose key needs normalising

    Deliberately narrow: it matches the two states this migration exists for - the key holding null and
    the key not being there - and nothing else. A document already carrying an empty value does not
    match, which is what makes a re-run a no-op, and one carrying a real value is never touched

    Args:
        key (str): The document key to normalise

    Returns:
        dict[str, Any]: The filter for that one key
    """
    return {
        '$or': [
            {key: None},
            {key: {'$exists': False}},
        ]
    }

# -------------------------------------------------------------------------------------------------------------------- #
#                                                Update20260909 - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class Update20260909(BaseDatabaseUpdate):
    """
    Normalises the null and missing optional keys of the CmdbPerson / CmdbPersonGroup collections
    """
    def creation_date(self) -> int:
        return 20260909


    def description(self) -> str:
        return ("Replaces the null and missing optional values of Persons and PersonGroups with the "
                "empty string / empty list, so a stored document can be sent back unchanged")


    def start_update(self) -> None:
        """
        Normalises every nullable key of both collections, then bumps the updater version

        Raises:
            UpdaterException: If any of the collections could not be updated
        """
        try:
            for collection, empty_value_by_key in NULLABLE_KEYS_BY_COLLECTION.items():
                for key, empty_value in empty_value_by_key.items():
                    normalised: int = self._normalise_key(collection, key, empty_value)

                    if normalised:
                        LOGGER.info(
                            "[Update20260909] Normalised '%s' on %s document(s) of %s",
                            key, normalised, collection,
                        )

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(err) from err


    def _normalise_key(self, collection: str, key: str, empty_value: Any) -> int:
        """
        Rewrites one key of one collection wherever it is null or absent

        Args:
            collection (str): Name of the collection to update
            key (str): The document key to normalise
            empty_value (Any): The empty value the key should hold instead

        Returns:
            int: Number of documents whose key was rewritten
        """
        result = self.dbm.update_many(
            collection,
            self.db_name,
            build_unset_or_null_criteria(key),
            {key: empty_value},
        )

        return result.modified_count
