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
Database update 20261111: every ISMS source and Risk category names an option of its own list, or nothing

The writes now refuse an IsmsThreat / IsmsVulnerability ``source`` that is no option of the THREAT_VULNERABILITY
list, an IsmsControlMeasure ``source`` that is no CONTROL_MEASURE option and an IsmsRisk ``category_id`` that is no
RISK option - and a value that is no whole number from 1 or a boolean. A document stored before could hold any of
them, and the frontend sends it back as it reads it - so editing it would be refused. This update sets every such
value to null (nothing chosen), changing nothing a reader shows: every label lookup reads within the field's own list,
so the value already rendered blank.

Re-run safe: a second run finds every value null or an option of its list, and writes nothing
"""
from logging import Logger, getLogger
from typing import Any, NamedTuple

from pymongo import UpdateOne

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The literals of this migration are frozen: it must keep meaning what it meant when it shipped
OPTIONS_COLLECTION: str = 'framework.extendableOptions'
MONGO_ID_FIELD: str = '_id'
PUBLIC_ID_FIELD: str = 'public_id'
OPTION_TYPE_FIELD: str = 'option_type'
MIN_PUBLIC_ID: int = 1


class OptionField(NamedTuple):
    """One field holding an option id: its collection, its key and the list it draws from"""
    collection: str
    field: str
    option_type: str


OPTION_FIELDS: tuple[OptionField, ...] = (
    OptionField('isms.threat', 'source', 'THREAT_VULNERABILITY'),
    OptionField('isms.vulnerability', 'source', 'THREAT_VULNERABILITY'),
    OptionField('isms.controlMeasure', 'source', 'CONTROL_MEASURE'),
    OptionField('isms.risk', 'category_id', 'RISK'),
)

# -------------------------------------------------------------------------------------------------------------------- #

def is_public_id(value: Any) -> bool:
    """
    Whether a stored value is a public_id: an int from 1; a bool is none

    Args:
        value (Any): The stored value

    Returns:
        bool: True for an id
    """
    return isinstance(value, int) and not isinstance(value, bool) and value >= MIN_PUBLIC_ID


def needs_reset(value: Any, options: set[int]) -> bool:
    """
    Whether a stored option value is to be set to null

    Args:
        value (Any): The stored value
        options (set[int]): The ids of the field's list

    Returns:
        bool: True for a value that is set and is no option of the list
    """
    return value is not None and not (is_public_id(value) and value in options)

# ---------------------------------------------- Update20261111 - CLASS ---------------------------------------------- #

class Update20261111(BaseDatabaseUpdate):
    """
    Nulls every ISMS source and Risk category that is no option of its own list

    Extends: BaseDatabaseUpdate
    """
    def creation_date(self) -> int:
        return 20261111


    def description(self) -> str:
        return "Nulls ISMS sources and Risk categories that are no option of their own list"


    def start_update(self) -> None:
        """
        Reads each list once, nulls every out-of-list value field by field, then bumps the version

        Raises:
            UpdaterException: If a read or a write fails
        """
        try:
            lists: dict[str, set[int]] = {}

            for option_field in OPTION_FIELDS:
                if option_field.option_type not in lists:
                    lists[option_field.option_type] = self.read_option_ids(option_field.option_type)

                rewritten: int = self.reset_field(option_field, lists[option_field.option_type])
                LOGGER.info("[updater_20261111] %s.%s: nulled %s value(s)", option_field.collection,
                            option_field.field, rewritten)

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(err) from err


    def read_option_ids(self, option_type: str) -> set[int]:
        """
        The public_ids of one option list

        Args:
            option_type (str): The list

        Returns:
            set[int]: Every option id of it
        """
        documents: list[dict[str, Any]] = list(self.dbm.find(
            collection=OPTIONS_COLLECTION, db_name=self.db_name, filter={OPTION_TYPE_FIELD: option_type},
            projection={MONGO_ID_FIELD: 0, PUBLIC_ID_FIELD: 1},
        ))

        return {document[PUBLIC_ID_FIELD] for document in documents if is_public_id(document.get(PUBLIC_ID_FIELD))}


    def reset_field(self, option_field: OptionField, options: set[int]) -> int:
        """
        Nulls one field on every document whose value is no option of the list, in one bulk write

        Args:
            option_field (OptionField): The field
            options (set[int]): The ids of its list

        Returns:
            int: How many documents were rewritten
        """
        operations: list[UpdateOne] = []

        for document in self.dbm.find(collection=option_field.collection, db_name=self.db_name,
                                      filter={option_field.field: {'$ne': None}},
                                      projection={MONGO_ID_FIELD: 1, PUBLIC_ID_FIELD: 1, option_field.field: 1}):
            if needs_reset(document.get(option_field.field), options):
                operations.append(UpdateOne({MONGO_ID_FIELD: document[MONGO_ID_FIELD]},
                                            {'$set': {option_field.field: None}}))
                LOGGER.warning("[updater_20261111] %s ID:%s - %s %r nulled", option_field.collection,
                               document.get(PUBLIC_ID_FIELD), option_field.field, document.get(option_field.field))

        if operations:
            self.dbm.bulk_write(option_field.collection, self.db_name, operations)

        return len(operations)
