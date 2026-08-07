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
Constants for the object search of DataGerry
"""
import re

from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

#: Flag string handed to `bson.Regex` for every search pattern: case-insensitive, multi-line, and
#: dot-matches-newline, so a search term hits regardless of casing or line breaks in a field value
SEARCH_REGEX_FLAGS: str = 'ims'

#: The `re` module equivalent of `SEARCH_REGEX_FLAGS`, used when a malformed pattern falls back to a
#: literal (escaped) match. Both must stay in sync so a fallback behaves like a successful compile
SEARCH_REGEX_RE_FLAGS: int = re.IGNORECASE | re.MULTILINE | re.DOTALL


class SearchResultKey(BaseStrEnum):
    """
    Enumeration of the keys in a serialized `SearchResult`

    This is the body of `GET|POST /rest/search/`. The Angular `SearchResultList` model mirrors it,
    so the members are a frontend-visible contract
    """
    LIMIT = 'limit'
    SKIP = 'skip'
    GROUPS = 'groups'
    TOTAL_RESULTS = 'total_results'
    NUMBER_OF_RESULTS = 'number_of_results'
    RESULTS = 'results'


class SearchResultMapKey(BaseStrEnum):
    """
    Enumeration of the keys in a serialized `SearchResultMap`

    One entry of `SearchResultKey.RESULTS`. The Angular `SearchResult` model mirrors it, so the
    members are a frontend-visible contract
    """
    RESULT = 'result'
    MATCHES = 'matches'
