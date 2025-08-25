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
Implementation of RegexConverter
"""
from logging import Logger, getLogger
from werkzeug.routing import BaseConverter
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                RegexConverter - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class RegexConverter(BaseConverter):
    """
    RegexConverter extends BaseConverter to allow regex-based URL matching
    """
    def __init__(self, url_map) -> None:
        super().__init__(url_map)
