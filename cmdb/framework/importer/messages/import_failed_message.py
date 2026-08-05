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
Import of ImportFailedMessage
"""
from cmdb.framework.importer.messages.import_message import ImportMessage
# -------------------------------------------------------------------------------------------------------------------- #

class ImportFailedMessage(ImportMessage):
    """Message wrapper for failed imported objects"""

    def __init__(self, error_message: str, obj: dict | None = None):
        """Init message
        Args:
            error_message: reason why it failed - exception error or something
            obj (optional): failed dict
        """
        self.error_message = error_message
        super().__init__(obj=obj)
