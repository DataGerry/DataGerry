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


class SearchFormType(BaseStrEnum):
    """
    The kinds of search parameter a request may carry

    A **frontend-visible contract**: the Angular search bar builds these strings itself
    (`addTag('text' | 'regex' | 'type' | 'category')`) and the result bar appends the DISJUNCTION
    marker, so a member removed here rejects a payload the UI still sends.

    Four of the six drive a pipeline stage. The other two do not, and both are deliberate:

      - PUBLIC_ID is accepted from API clients; the frontend expresses "search by id" as a TEXT tag
        carrying a `publicID` setting instead
      - DISJUNCTION is a marker the result bar appends when type filtering switches to OR. Nothing
        reads it: the OR itself comes from each TYPE parameter's own `disjunction` flag, which
        defaults to True. It is accepted so the UI's payload validates, and **kept as a documented
        no-op**. Implementing it would make the parameter the UI already sends the switch it looks
        like; dropping it would answer 400 to every type-filter click the UI performs, so it needs
        the frontend to stop sending it first. It is inert rather than merely unused: the builder
        dispatches by form, so the marker reaches no stage, and the highlight matcher reads the
        executed pipeline's `$regex` values - no stage means no bogus match either.
    """
    TEXT = 'text'
    REGEX = 'regex'
    TYPE = 'type'
    CATEGORY = 'category'
    DISJUNCTION = 'disjunction'
    PUBLIC_ID = 'publicID'


class SearchParamKey(BaseStrEnum):
    """
    Keys of one search parameter as the frontend sends it

    Mirrors the Angular `SearchBarTag`, so these spellings are a frontend-visible contract.

    SEARCH_LABEL is sent by the search bar on every tag and is NOT read by `SearchParam.from_request`
    - the backend derives what it needs from SEARCH_TEXT and SETTINGS. It is named here because the
    per-type groups of a search response carry it back (see `SearchGroupKey`), and the result bar
    re-submits a group as a tag
    """
    SEARCH_TEXT = 'searchText'
    SEARCH_FORM = 'searchForm'
    SEARCH_LABEL = 'searchLabel'
    SETTINGS = 'settings'
    DISJUNCTION = 'disjunction'


class SearchFacetKey(BaseStrEnum):
    """
    The three branches of the object search's `$facet` stage

    One aggregation answers a whole search: METADATA counts every match, DATA carries the requested
    page and GROUP the per-type tallies. The names are pipeline-internal - the searcher reads them
    off the single document `$facet` emits and none of them reaches a client
    """
    METADATA = 'metadata'
    DATA = 'data'
    GROUP = 'group'


class SearchGroupKey(BaseStrEnum):
    """
    Keys of one per-type group in a search response (`SearchResultKey.GROUPS`)

    A **frontend-visible contract**: the Angular result bar reads SEARCH_LABEL and TOTAL to draw the
    type filter and re-submits the entry as a TYPE tag, which is why the first four members are
    deliberately the same strings as the matching `SearchParamKey` members - a group IS a ready-made
    search parameter. TOTAL is the group's own addition (how many matches carry that type) and TYPES
    is the key inside SETTINGS holding the single type id, the shape a TYPE parameter expects
    """
    SEARCH_TEXT = SearchParamKey.SEARCH_TEXT.value
    SEARCH_FORM = SearchParamKey.SEARCH_FORM.value
    SEARCH_LABEL = SearchParamKey.SEARCH_LABEL.value
    SETTINGS = SearchParamKey.SETTINGS.value
    TOTAL = 'total'
    TYPES = 'types'


class SearchQueryKey(BaseStrEnum):
    """
    The query-string parameters the search routes read

    Distinct from `SearchResultKey` even where the spelling matches: LIMIT and SKIP name what the
    *request* asks for, `SearchResultKey.LIMIT` / `SKIP` what the *response* reports back. The two
    happen to agree today and are still separate members, because a route reading a response key
    would be a bug that spells correctly.

    QUERY carries the search parameters themselves - a JSON array of `SearchParamKey` objects, the
    same payload a POST sends as its body. SEARCH_VALUE is the quick counter's single regex term
    """
    LIMIT = 'limit'
    SKIP = 'skip'
    QUERY = 'query'
    RESOLVE = 'resolve'
    SEARCH_VALUE = 'searchValue'


class QuickSearchCountKey(BaseStrEnum):
    """
    Keys of the quick-search counter body (`GET /rest/search/quick/count/`)

    A **frontend-visible contract**: the Angular `NumberSearchResults` model declares exactly these
    three fields. `QuickSearchPipelineBuilder` projects them and the route repeats them as its
    empty-result fallback, so they are named here rather than spelled in both places
    """
    ACTIVE = 'active'
    INACTIVE = 'inactive'
    TOTAL = 'total'
