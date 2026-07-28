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
Implementation of ImporterObjectResponse
"""
from cmdb.framework.importer.importer_constants import IMPORT_SUMMARY_MESSAGE
from cmdb.framework.importer.messages.import_success_message import ImportSuccessMessage
from cmdb.framework.importer.messages.import_failed_message import ImportFailedMessage
# -------------------------------------------------------------------------------------------------------------------- #

def build_import_summary_message(success_count: int, failed_count: int) -> str:
    """
    Builds the human-readable summary line of a bulk object import

    A batch that imported nothing is still a completed request, so the summary reports what happened
    rather than reading like an error. Both counts and the submitted total are always stated, zeroes
    included, so the outcome can be read off the one line without comparing it against the request

    Args:
        success_count (int): Number of objects that were imported
        failed_count (int): Number of objects that were rejected or failed to import

    Returns:
        str: The summary line, e.g. `Imported 2 of 3 objects, 1 failed`
    """
    total = success_count + failed_count

    return IMPORT_SUMMARY_MESSAGE.format(
        success=success_count,
        total=total,
        noun='object' if total == 1 else 'objects',
        failed=failed_count,
    )



class ImporterObjectResponse:
    """
    Response of a bulk object import
    """

    def __init__(
            self,
            message: str,
            success_imports: list | None = None,
            failed_imports: list | None = None,
        ) -> None:
        """
        Initializes the ImporterObjectResponse for a bulk object import

        Args:
            message (str): A human-readable summary of the import result
            success_imports (list | None): The ImportSuccessMessage entries. Defaults to an empty list
            failed_imports (list | None): The ImportFailedMessage entries. Defaults to an empty list
        """
        self.message: str = message
        self.success_imports: list[ImportSuccessMessage] = success_imports or []
        self.failed_imports: list[ImportFailedMessage] = failed_imports or []
