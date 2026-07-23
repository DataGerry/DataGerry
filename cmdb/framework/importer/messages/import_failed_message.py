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
Implementation of ImportFailedMessage
"""
from typing import Any

from cmdb.framework.importer.messages.import_message import ImportMessage
# -------------------------------------------------------------------------------------------------------------------- #

class ImportFailedMessage(ImportMessage):
    """Message wrapper for failed imported objects"""

    def __init__(self, error_message: Any, obj: dict | None = None) -> None:
        """
        Initialises the ImportFailedMessage

        Args:
            error_message (Any): The failure reason (an exception or string); coerced to str so it
                serializes as readable text rather than an empty object
            obj (dict | None): The object dict that failed to import
        """
        self.error_message: str = str(error_message)
        super().__init__(obj=obj)
