# DataGerry - OpenSource Enterprise CMDB
# Copyright (C) 2025 becon GmbH
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
Implementation of ObjectParserResponse
"""
from cmdb.framework.importer.responses.base_parser_response import BaseParserResponse
# -------------------------------------------------------------------------------------------------------------------- #

class ObjectParserResponse(BaseParserResponse):
    """Response for object imports"""

    def __init__(self, count: int, entries: list = None):
        self.entries: list = entries or []
        super().__init__(count=count)


    def output(self) -> dict:
        return self.__dict__
