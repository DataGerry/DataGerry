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
Implementation of the per-entry report message of a type import, and the type import's report

The type import fills the same partial report as the object import (`ImportReportResponse`): the
imported types are a plain count, and only a rejected entry carries a message. That message names what
was refused - `{failed_type, errors}`, where the object import reports `{failed_object, errors}`. The type
import's report adds one count: the imported entries whose uploaded ``acl`` was activated - an ACL is not imported
(`TypeImportReportResponse.access_not_imported`)
"""
from typing import Any

from cmdb.framework.importer.responses.import_report_response import ImportReportResponse
# -------------------------------------------------------------------------------------------------------------------- #

class TypeImportFailedMessage:
    """
    Report entry for a single rejected CmdbType of a type import

    Serializes (via ``__dict__``) to ``{failed_type, errors}``: the entry exactly as the user uploaded
    it, plus every reason it could not be imported
    """

    def __init__(self, failed_type: Any, errors: list[str]) -> None:
        """
        Initializes the TypeImportFailedMessage

        Args:
            failed_type (Any): The entry as provided by the user (normally a type dictionary, but an
                               unusable entry is reported with whatever value the upload carried)
            errors (list[str]): The reasons the entry was rejected or failed to import
        """
        self.failed_type: Any = failed_type
        self.errors: list[str] = errors


class TypeImportReportResponse(ImportReportResponse):
    """
    The partial report of a type import: the object import's report plus ``access_not_imported``

    Serializes (via ``__dict__``) to ``{message, success_imports, failed_imports, access_not_imported}``
    """

    def __init__(self, message: str, success_imports: int = 0,
                 failed_imports: list['TypeImportFailedMessage'] | None = None,
                 access_not_imported: int = 0) -> None:
        """
        Initializes the TypeImportReportResponse

        Args:
            message (str): The summary line
            success_imports (int): How many entries were imported. Defaults to 0
            failed_imports (list[TypeImportFailedMessage] | None): One message per rejected entry. Defaults to none
            access_not_imported (int): How many imported entries carried an activated ``acl`` - not imported.
                Defaults to 0
        """
        super().__init__(message, success_imports, failed_imports)
        self.access_not_imported: int = access_not_imported
