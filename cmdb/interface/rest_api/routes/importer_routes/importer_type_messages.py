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
Implementation of the per-entry report message of a type import

The type import fills the same partial report as the object import (`ImportReportResponse`): the
imported types are a plain count, and only a rejected entry carries a message. That message names what
was refused - `{failed_type, errors}`, where the object import reports `{failed_object, errors}` - which
is the only difference between the two reports
"""
from typing import Any
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
