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
The vocabulary of the REST API response envelope

Every route answers through one of the classes in this package, and the keys those classes write are
a **frontend contract**: `app/src/app/services/models/api-response.ts` declares them, and four
services read the `X-Total-Count` header. They were bare string literals in eight modules until
2026-09-09, so a rename could pass the whole backend suite while breaking the Angular app - naming
them here is what makes such a rename a compile-time-visible change on this side

The mime type, the API version and the JSON indent live here for the same reason: they are part of
what every response sends
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

DEFAULT_MIME_TYPE: str = 'application/json'
API_VERSION: str = '1.0'

# Every response body is pretty-printed. Measured on a 50-object page of `GET /objects/`: +63% body
# size and 5.7x the serialization time against a compact dump, with no compression anywhere in the
# backend. Kept deliberately - changing it is discussion-backlog #215
DEFAULT_JSON_INDENT: int = 2


class ResponseKey(BaseStrEnum):
    """
    Keys of the response envelope, as the frontend's `APIResponse` types declare them

    RESPONSE_TYPE and TIME are written by every class (`BaseAPIResponse.export`); the rest belong to
    the individual responses - RESULT for a single resource, RESULTS/COUNT/TOTAL for a collection,
    RAW plus RESULT_ID for an insert, FAILED for a partial bulk update, and PARAMETERS/PAGER/
    PAGINATION for the pager block a GetMultiResponse adds unless a route asks for `pagination=False`
    """
    RESPONSE_TYPE = 'response_type'
    TIME = 'time'
    RESULT = 'result'
    RESULTS = 'results'
    RESULT_ID = 'result_id'
    RAW = 'raw'
    COUNT = 'count'
    TOTAL = 'total'
    FAILED = 'failed'
    PARAMETERS = 'parameters'
    PAGER = 'pager'
    PAGINATION = 'pagination'


class ResponseHeader(BaseStrEnum):
    """
    Response headers the API sets itself

    TOTAL_COUNT is read by four Angular services (type, object, group, user) to size a collection
    without parsing its body, which is also why it is set on a bodyless HEAD response
    """
    API_VERSION = 'X-API-Version'
    TOTAL_COUNT = 'X-Total-Count'
