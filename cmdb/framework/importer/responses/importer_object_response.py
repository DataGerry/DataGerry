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
from cmdb.framework.importer.messages.import_success_message import ImportSuccessMessage
from cmdb.framework.importer.messages.import_failed_message import ImportFailedMessage
from cmdb.framework.importer.responses.import_report_response import ImportReportResponse
# -------------------------------------------------------------------------------------------------------------------- #

class ImporterObjectResponse:
    """
    Outcome of a bulk object import, as the importer produces it

    This is the importer's INTERNAL result, not the response body: it keeps one message per imported
    object because the route needs their public_ids to write the CREATE logs. `as_report()` turns it
    into what the caller receives, where the imported objects are a plain count
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


    def as_report(self) -> ImportReportResponse:
        """
        Converts the import outcome into the partial report the caller receives

        The imported objects collapse to their count - the caller does not need them echoed back - while
        every rejected object keeps its data and reasons. The summary line is the one the importer
        already built from the same counts

        Returns:
            ImportReportResponse: The report to serialize into the response body
        """
        return ImportReportResponse(
            message=self.message,
            success_imports=len(self.success_imports),
            failed_imports=self.failed_imports,
        )
