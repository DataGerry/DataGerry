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
Implementation of SearchResultMap
"""
from logging import Logger, getLogger
from typing import TypeVar, Generic
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

R = TypeVar('R')

# -------------------------------------------------------------------------------------------------------------------- #
#                                                SearchResultMap - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class SearchResultMap(Generic[R]):
    """
    Result mapper for Result/Match binding
    """
    def __init__(self, result: R, matches: list[str] = None) -> None:
        self.result: R = result
        self.matches: list[str] = matches


    def to_json(self) -> dict:
        """
        Quick convert for the database
        """
        return {'result': self.result.__dict__, 'matches': self.matches}
