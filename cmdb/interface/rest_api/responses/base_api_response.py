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
Implementation of BaseAPIResponse - the envelope every REST route answers through

**What this package is.** A route never builds an HTTP response itself: it hands its payload to one
of these classes, which serializes it, stamps the envelope keys and sets the API headers. One class
per operation, and the class decides the status code so the same operation always answers the same
way:

| Class | Operation | Status | Payload keys |
|---|---|---|---|
| `GetSingleResponse` | GET one resource | 200 | `result` |
| `GetListResponse` | GET a plain list | 200 | `results` (+ `X-Total-Count`) |
| `GetMultiResponse` | GET a paged collection | 200 | `results`, `count`, `total`, pager block |
| `InsertSingleResponse` | POST | 201 | `result_id`, `raw` |
| `UpdateSingleResponse` | PUT / PATCH | 202 | `result` |
| `UpdateMultiResponse` | bulk PUT | 202 | `results`, `failed` |
| `DeleteSingleResponse` | DELETE | 202 with a body, else 204 | `raw` |
| `DefaultResponse` | anything that is just a value | caller's | the value itself |
| `LoginResponse` | the token exchange | 200 | user + token (no envelope keys, by design) |

Every payload passes through `cmdb.database.json_codec.default`, which is what turns a `datetime`
into the `{'$date': millis}` wire format the frontend expects (see the date-format record) and an
`ObjectId` into a string. The envelope's own `time` field is the one deliberate exception: it is an
ISO-8601 string, because the Angular `APIResponse` type declares it as one.

**The bodyless (HEAD) case.** `body=False` means "answer without a payload", which is what a HEAD
request wants; routes get that flag from `routes_helper.request_wants_body()`. Nothing is serialized
in that case - the response carries the status, the mime type and the headers only. Werkzeug would
strip the body of a HEAD response anyway, but it strips it *after* the payload has been built, so
until 2026-09-09 (when the flag was inert - `body or True` could never be False) a HEAD on a large
collection paid the full serialization for nothing.

Response keys and header names come from `response_constants.py`; they are a frontend contract
"""
from abc import ABC, abstractmethod
from logging import Logger, getLogger
from typing import Any
from json import dumps
from datetime import datetime, timezone

from flask import abort, make_response as flask_response
from werkzeug.wrappers import Response

from cmdb.database.json_codec import default
from cmdb.interface.rest_api.responses.helpers.api_projection import APIProjection
from cmdb.interface.rest_api.responses.helpers.api_projector import APIProjector
from cmdb.interface.rest_api.responses.helpers.operation_type_enum import OperationType
from cmdb.interface.rest_api.responses.response_constants import (
    API_VERSION,
    DEFAULT_JSON_INDENT,
    DEFAULT_MIME_TYPE,
    ResponseHeader,
    ResponseKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                BaseAPIResponse - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class BaseAPIResponse(ABC):
    """
    Base class for the API responses: the envelope, the serialization and the HTTP headers

    Abstract on purpose - `make_response` is what a route calls, and only a concrete response knows
    its status code and its payload keys. Subclasses build their payload in `export` and hand it over
    through `make_body_response`, so the bodyless case and the header stamping exist once
    """
    def __init__(
            self,
            operation_type: OperationType,
            url: str | None = None,
            body: bool | None = True) -> None:
        """
        Stores what every response envelope needs

        Args:
            operation_type (OperationType): The operation being answered; becomes `response_type`
            url (str | None): The requested url, used by the pager to build its page links. Stored as
                an empty string when not given, because `APIPagination` builds on it
            body (bool | None): Whether the response should carry a payload. False answers without
                one (the HEAD case). None means True: it is the default the Get* constructors pass
                when a route does not care
        """
        self.operation_type: OperationType = operation_type
        self.url: str = url or ''
        self.body: bool = True if body is None else bool(body)
        self.time: str = datetime.now(timezone.utc).isoformat()


    @abstractmethod
    def make_response(self, *args: Any, **kwargs: Any) -> Response:
        """
        Builds the http response a route returns

        Implemented by every concrete response, which knows its own status code. Arguments are
        forwarded to `export`, which is how `GetMultiResponse.make_response(pagination=False)`
        suppresses the pager block

        Returns:
            Response: The http response
        """


    def export(self) -> dict[str, Any]:
        """
        Returns the envelope keys every response carries

        Returns:
            dict[str, Any]: The operation type and the response time
        """
        return {
            ResponseKey.RESPONSE_TYPE.value: self.operation_type.value,
            ResponseKey.TIME.value: self.time,
        }


    def make_body_response(self, *args: Any, status: int = 200, **kwargs: Any) -> Response:
        """
        Answers with the exported payload, or without a payload when the caller asked for none

        The one place the `body` flag is honoured: a bodyless response never builds the payload and
        never serializes it. Lifted here from the three Get* classes, which each held their own copy

        Args:
            *args (Any): Positional arguments forwarded to `export`
            status (int): The http status code, 200 unless a response states otherwise
            **kwargs (Any): Keyword arguments forwarded to `export`

        Raises:
            HTTPException: 500 when the payload cannot be serialized

        Returns:
            Response: The http response, with or without a payload
        """
        if not self.body:
            return self.make_empty_response(status)

        return self.make_api_response(self.export(*args, **kwargs), status)


    def make_empty_response(self, status: int = 200, mime: str = DEFAULT_MIME_TYPE) -> Response:
        """
        Answers with no payload at all - the HEAD case

        Deliberately does not serialize `None` either: a HEAD on a paged collection should cost
        nothing beyond the reads the route already did

        Args:
            status (int): The http status code
            mime (str): The mime type to report

        Returns:
            Response: The http response, carrying the headers and an empty body
        """
        return self._http_response('', status, mime)


    def make_api_response(
        self,
        body: Any,
        status: int = 200,
        mime: str = DEFAULT_MIME_TYPE,
        indent: int = DEFAULT_JSON_INDENT
    ) -> Response:
        """
        Serializes a payload into a valid http response

        The single serialization point of the whole REST API: `json_codec.default` is applied here,
        which is what encodes a `datetime` as `{'$date': millis}` and an `ObjectId` as a string

        Args:
            body (Any): The payload to serialize
            status (int): The http status code
            mime (str): The mime type to report
            indent (int): JSON indent; every response is pretty-printed (see DEFAULT_JSON_INDENT)

        Raises:
            HTTPException: 500 when the payload cannot be serialized - the failure is logged with its
                traceback, because the caller only learns that "something" could not be built

        Returns:
            Response: The http response carrying the serialized payload
        """
        try:
            return self._http_response(dumps(body, default=default, indent=indent), status, mime)
        except Exception as err:
            LOGGER.error("[make_api_response] Failed to serialize the response payload: %s. Type: %s",
                         err, type(err), exc_info=True)
            abort(500, "Failed to create a response from the given data!")


    @staticmethod
    def apply_projection(data: dict | list[dict], projection: dict | list | None) -> dict | list[dict]:
        """
        Trims result document(s) down to a client-requested `?projection=`

        Shared by the three Get* responses, which asked the same question in three different spellings.
        A falsy projection returns the data untouched, so a caller can pass whatever it holds

        Args:
            data (dict | list[dict]): The result document, or a list of them
            projection (dict | list | None): The `projection` query parameter - a MongoDB-style
                `{field: 1|0}` mapping, a list of field names, or None

        Returns:
            dict | list[dict]: The projected data, in the shape it came in
        """
        if not projection:
            return data

        return APIProjector(data, APIProjection(projection)).project


    @staticmethod
    def _http_response(payload: str, status: int, mime: str) -> Response:
        """
        Wraps an already-serialized payload into a Response carrying the API headers

        Args:
            payload (str): The serialized body, empty for a bodyless response
            status (int): The http status code
            mime (str): The mime type to report

        Returns:
            Response: The http response
        """
        response: Response = flask_response(payload, status)
        response.mimetype = mime
        response.headers[ResponseHeader.API_VERSION.value] = API_VERSION

        return response
