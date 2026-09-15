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
Shared constants of the REST API request/response parameters

``ParameterKey`` names the query-string keys the pager is parsed FROM and, for most of them, the keys
of the ``parameters`` block a ``GetMultiResponse`` echoes back - so these strings are **frontend
contract on both sides** and may not be renamed without an Angular change. ``BuilderParamKey`` names
the keys of the ``get_builder_params`` output, which is the internal hand-off to ``BuilderParameters``
and is NOT part of that contract

The defaults and bounds are named here too, because the pager applies them in more than one place
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'ParameterKey',
    'BuilderParamKey',
    'DEFAULT_LIMIT',
    'DEFAULT_SORT',
    'FIRST_PAGE',
    'UNLIMITED_LIMIT',
    'SORT_ASCENDING',
    'SORT_DESCENDING',
    'VALID_SORT_ORDERS',
]


class ParameterKey(BaseStrEnum):
    """
    Query-string keys of the REST pager, and the keys echoed in a GetMultiResponse's `parameters`

    Frontend contract: the Angular services build these query keys and read the echoed block back
    (`api-parameter.ts` / every `*.service.ts` list call), so the string values are fixed
    """
    QUERY_STRING = 'query_string'
    LIMIT = 'limit'
    SORT = 'sort'
    ORDER = 'order'
    PAGE = 'page'
    FILTER = 'filter'
    PROJECTION = 'projection'
    OPTIONAL = 'optional'
    ACTIVE = 'active'
    ACTION = 'action'
    GROUP_ID = 'group_id'


class BuilderParamKey(BaseStrEnum):
    """
    Keys of the ``CollectionParameters.get_builder_params`` output

    Internal only - this dict is splatted into ``BuilderParameters(...)``, so the names match that
    constructor rather than the query string. Note ``CRITERIA``: what the wire calls ``filter`` is
    called ``criteria`` from here inward
    """
    CRITERIA = 'criteria'
    LIMIT = 'limit'
    SORT = 'sort'
    ORDER = 'order'
    SKIP = 'skip'


#: Page size applied when the caller sends no `limit`
DEFAULT_LIMIT: int = 10

#: Sort key applied when the caller sends no `sort`
DEFAULT_SORT: str = 'public_id'

#: Lowest page number there is. A caller asking for page 0 or a negative page is asking for the start
#: of the collection, so the pager clamps to this rather than refusing - see CollectionParameters
FIRST_PAGE: int = 1

#: `limit=0` means "no limit" rather than "no results"; BuilderParameters.has_limit keys off it and the
#: frontend relies on it for its unbounded reads
UNLIMITED_LIMIT: int = 0

#: The only two values MongoDB's `$sort` accepts
SORT_ASCENDING: int = 1
SORT_DESCENDING: int = -1
VALID_SORT_ORDERS: frozenset[int] = frozenset({SORT_ASCENDING, SORT_DESCENDING})
