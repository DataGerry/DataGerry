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
Implementation of ImportSuccessMessage
"""
from typing import Any

from cmdb.framework.importer.messages.import_message import ImportMessage
# -------------------------------------------------------------------------------------------------------------------- #

class ImportSuccessMessage(ImportMessage):
    """
    Message wrapper for successfully imported CmdbObjects
    
    Extends: ImportMessage
    """

    def __init__(self,
                 public_id: int,
                 obj: dict[str, Any] | None = None,
                 changes: dict[str, Any] | None = None) -> None:
        """
        Initialises the ImportSuccessMessage

        Args:
            public_id (int): public_id of the imported CmdbObject
            obj (dict[str, Any] | None): CmdbObject instance
            changes (dict[str, Any] | None): The diff of an overwrite, which edited the stored object; None for an
                object the import created. Defaults to None
        """
        self.public_id = public_id
        self.changes = changes
        super().__init__(obj=obj)


    @property
    def overwritten(self) -> bool:
        """
        Whether the import overwrote a stored object instead of creating one

        Returns:
            bool: True when the message carries an overwrite's diff
        """
        return self.changes is not None
