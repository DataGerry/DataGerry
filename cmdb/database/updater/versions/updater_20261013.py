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
Database update 20261013: report every stored field pattern the browser and the server read differently

Since this version a CmdbType, a CmdbSectionTemplate and a type import refuse a field ``regex`` the two dialects part
on (``cmdb.framework.field_pattern_rule``) - but only a pattern the write adds or changes: one stored before stays,
and its type or template stays saveable until somebody edits that pattern. This update lists those stored
patterns so an administrator can decide; it writes nothing.

Unlike the updaters that write, this one asks the LIVE rule rather than a frozen copy: it only reports, so a later
change to the rule changes what a re-run lists and can never change what is stored. A re-run reports the same
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate
from cmdb.framework.field_pattern_rule import field_pattern_problem

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The collections and keys this report reads
TYPE_COLLECTION: str = 'framework.types'
SECTION_TEMPLATE_COLLECTION: str = 'framework.sectionTemplates'
PUBLIC_ID_FIELD: str = 'public_id'
NAME_FIELD: str = 'name'
FIELDS_FIELD: str = 'fields'
FIELD_NAME_KEY: str = 'name'
FIELD_REGEX_KEY: str = 'regex'

# The documents this report visits: those with at least one field declaring a pattern
WITH_PATTERN_CRITERIA: dict[str, Any] = {f'{FIELDS_FIELD}.{FIELD_REGEX_KEY}': {'$exists': True}}


def stored_pattern_problems(document: dict[str, Any]) -> list[str]:
    """
    Answers the refusal of every field pattern a stored type or template carries

    Args:
        document (dict[str, Any]): The stored document, projected to its fields

    Returns:
        list[str]: One message per field whose pattern the rule refuses, in field order
    """
    fields: Any = document.get(FIELDS_FIELD)
    problems: list[str] = []

    for field in fields if isinstance(fields, list) else []:
        if isinstance(field, dict):
            if problem := field_pattern_problem(field.get(FIELD_NAME_KEY), field.get(FIELD_REGEX_KEY)):
                problems.append(problem)

    return problems


class Update20261013(BaseDatabaseUpdate):
    """
    Reports the stored CmdbType and CmdbSectionTemplate field patterns the pattern rule refuses

    Extends: BaseDatabaseUpdate
    """
    def creation_date(self) -> int:
        return 20261013


    def description(self) -> str:
        return "Reports stored field patterns the browser and the server read differently (writes nothing)"


    def start_update(self) -> None:
        """
        Reports the patterns of the types and the section templates, then bumps the version

        Raises:
            UpdaterException: If a read failed
        """
        try:
            for collection in (TYPE_COLLECTION, SECTION_TEMPLATE_COLLECTION):
                self.report_collection(collection)

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(err) from err


    def report_collection(self, collection: str) -> None:
        """
        Logs every refused pattern of one collection, by document

        Args:
            collection (str): The collection holding field definitions
        """
        documents: list[dict[str, Any]] = list(self.dbm.find(
            collection=collection,
            db_name=self.db_name,
            filter=WITH_PATTERN_CRITERIA,
            projection={PUBLIC_ID_FIELD: 1, NAME_FIELD: 1, FIELDS_FIELD: 1, '_id': 0},
        ))

        for document in documents:
            for problem in stored_pattern_problems(document):
                LOGGER.warning("[Update20261013] '%s' %s %s (%r): %s - kept as it is; its next edit must fix it",
                               self.db_name, collection, document.get(PUBLIC_ID_FIELD), document.get(NAME_FIELD),
                               problem)
