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
Implementation of ImportReportResponse and the summary line every bulk import reports

Both bulk imports - Objects and Types - report the same way: every entry is processed on its own, so a
single bad entry never discards the rest of the batch, and the response carries a summary line, the
NUMBER of imported entries and one message per rejected entry. The shape lives here once so the two
reports cannot drift apart

The asymmetry is deliberate. A successful entry needs no explaining, so `success_imports` is a plain
count; a rejected one has to say what was refused and why, and that message is the only thing the two
imports do not share: objects report `ImportFailedMessage` (`failed_object`), types
`TypeImportFailedMessage` (`failed_type`)
"""
from typing import Any

from cmdb.framework.importer.importer_constants import (
    IMPORT_NOUN_PLURAL_SUFFIX,
    IMPORT_SUMMARY_MESSAGE,
    ImportNoun,
)
# -------------------------------------------------------------------------------------------------------------------- #

def build_import_summary_message(
        success_count: int,
        failed_count: int,
        noun: ImportNoun = ImportNoun.OBJECT,
    ) -> str:
    """
    Builds the human-readable summary line of a bulk import

    A batch that imported nothing is still a completed request, so the summary reports what happened
    rather than reading like an error. Both counts and the submitted total are always stated, zeroes
    included, so the outcome can be read off the one line without comparing it against the request

    Args:
        success_count (int): Number of entries that were imported
        failed_count (int): Number of entries that were rejected or failed to import
        noun (ImportNoun): What was imported, pluralized unless the batch held exactly one entry

    Returns:
        str: The summary line, e.g. `Imported 2 of 3 objects, 1 failed`
    """
    total = success_count + failed_count

    return IMPORT_SUMMARY_MESSAGE.format(
        success=success_count,
        total=total,
        noun=noun.value if total == 1 else f'{noun.value}{IMPORT_NOUN_PLURAL_SUFFIX}',
        failed=failed_count,
    )


class ImportReportResponse:
    """
    Partial report of a bulk import: the summary line, the imported count and the rejected entries
    """

    def __init__(
            self,
            message: str,
            success_imports: int = 0,
            failed_imports: list | None = None,
        ) -> None:
        """
        Initializes the ImportReportResponse for a bulk import

        Args:
            message (str): A human-readable summary of the import result
            success_imports (int): How many entries were imported. Defaults to 0
            failed_imports (list | None): The failure messages of the import (ImportFailedMessage for
                                          objects, TypeImportFailedMessage for types). Defaults to an
                                          empty list
        """
        self.message: str = message
        self.success_imports: int = success_imports
        self.failed_imports: list[Any] = failed_imports or []
