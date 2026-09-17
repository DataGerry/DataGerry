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
    'ALLOWED_PIPELINE_STAGES',
    'ALLOWED_LOOKUP_COLLECTIONS',
    'WRITE_PIPELINE_STAGES',
    'DENIED_EXPRESSION_OPERATORS',
    'LookupKey',
]


class LookupKey(BaseStrEnum):
    """
    Keys of a ``$lookup`` stage that the client-pipeline guard has to read

    FROM names the target collection, which is allow-listed; PIPELINE and LET are the two places a
    ``$lookup`` can nest further client-supplied expressions, so both are walked rather than trusted
    """
    FROM = 'from'
    PIPELINE = 'pipeline'
    LET = 'let'


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
    CATEGORY = 'category'
    UNCATEGORIZED = 'uncategorized'
    ACL = 'acl'


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


# -------------------------------------------------------------------------------------------------------------------- #
#                                        CLIENT AGGREGATION-PIPELINE ALLOW-LISTS                                       #
# -------------------------------------------------------------------------------------------------------------------- #

#: Aggregation stages a client may send in ``?filter=``
#:
#: A list-shaped filter is spliced into the aggregation verbatim, so this list - not MongoDB - decides
#: what a caller can make the database do. It holds **exactly** the stages the Angular frontend builds
#: into a filter today, counted across ``app/src``, and nothing else: widening it is a decision, not a
#: convenience. ``$sort`` / ``$limit`` / ``$skip`` are deliberately absent - the pager appends its own
#: and the frontend never sends them - and so is every stage that reads or writes another collection
#: apart from the two ``$lookup`` targets below
#:
#: ``$lookup`` and ``$group`` are here **only because the frontend depends on them** and removing them
#: would break live screens; both are recorded as tier 2 T204 / T205 with the call sites that have to
#: move server-side first
ALLOWED_PIPELINE_STAGES: frozenset[str] = frozenset({
    '$match',
    '$addFields',
    '$project',
    '$group',
    '$lookup',
})

#: Collections a client-supplied ``$lookup`` may target
#:
#: The two the frontend actually joins against (categories for the uncategorized-types screen, objects
#: for the object search and the reference tables). Without this bound, ``$lookup`` reads ANY collection
#: in the database - ``management.users`` included, which is how a caller could read password digests
#: through any list route
ALLOWED_LOOKUP_COLLECTIONS: frozenset[str] = frozenset({
    'framework.categories',
    'framework.objects',
})

#: Stages that WRITE, refused by name so the rejection says why
#:
#: They are already outside ALLOWED_PIPELINE_STAGES. They are named again because until this guard
#: existed they were refused only by accident: the pager appends ``$sort`` / ``$skip`` after the
#: client's stages and ``$out`` / ``$merge`` must be last, so MongoDB rejected them for the wrong
#: reason. An ordering accident is not a guard
WRITE_PIPELINE_STAGES: frozenset[str] = frozenset({
    '$out',
    '$merge',
})

#: Expression operators refused ANYWHERE inside a filter, at any nesting depth
#:
#: These are not stages, they are expressions, so they ride inside a stage that is itself permitted -
#: ``$function`` inside ``$match``/``$expr`` executes server-side JavaScript on a plain filtered read.
#: A stage-name allow-list alone therefore does not close them, which is why the guard walks values
DENIED_EXPRESSION_OPERATORS: frozenset[str] = frozenset({
    '$function',
    '$accumulator',
    '$where',
})
