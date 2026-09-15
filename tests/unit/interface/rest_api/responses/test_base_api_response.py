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
Unit tests for cmdb.interface.rest_api.responses.base_api_response

The envelope every REST route answers through had **no test module of its own** until 2026-09-09: it
was exercised only incidentally, through the functional route tests. That is how three defects lived
in 32 statements - an inert `body` flag, a dead type guard, and a serialization failure logged below
the production log level.

What is pinned here: the `body` flag really suppresses the payload (and does not serialize it), the
envelope keys and the two API headers are what the Angular `APIResponse` types expect, a payload
passes through `json_codec.default` so a datetime leaves as `{'$date': millis}`, a payload that
cannot be serialized becomes a 500 that is LOGGED, and `apply_projection` answers in the shape it was
given.
"""
from datetime import datetime, timezone
from json import loads
from typing import Any
from unittest.mock import patch

import pytest
from bson import ObjectId
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.interface.rest_api.responses.base_api_response import BaseAPIResponse
from cmdb.interface.rest_api.responses.helpers.operation_type_enum import OperationType
from cmdb.interface.rest_api.responses.response_constants import (
    API_VERSION,
    DEFAULT_MIME_TYPE,
    ResponseHeader,
    ResponseKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

BASE_PATH: str = 'cmdb.interface.rest_api.responses.base_api_response'

PAYLOAD: dict[str, Any] = {'value': 1}


class _Response(BaseAPIResponse):
    """A minimal concrete response, so the base class can be exercised on its own"""

    def make_response(self, *args: Any, **kwargs: Any):
        """Answers with the exported envelope"""
        return self.make_body_response(*args, **kwargs)


@pytest.fixture(autouse=True)
def _app_ctx():
    """
    A request context around every test: `make_response` and `abort` both need one

    Autouse because it is taken for its side effect only - no test reads the app itself.
    """
    with Flask(__name__).test_request_context('/rest/whatever'):
        yield


def _response(**kwargs: Any) -> _Response:
    """A concrete response over the base class"""
    return _Response(OperationType.GET, **kwargs)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  the body flag                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBodyFlag:
    """`body` decides whether the response carries a payload - it used to decide nothing at all."""

    def test_false_really_means_no_body(self) -> None:
        """
        The defect this pins: `self.body = body or True` could never be False

        So the no-body branch of all three Get* responses was unreachable, and a HEAD request paid the
        full serialization of a payload werkzeug then dropped.
        """
        assert _response(body=False).body is False

    def test_true_means_a_body(self) -> None:
        """The normal case"""
        assert _response(body=True).body is True

    def test_none_means_a_body(self) -> None:
        """None is what the Get* constructors default to: a route that does not care gets a payload"""
        assert _response(body=None).body is True

    def test_the_default_is_a_body(self) -> None:
        """Every write response relies on this: they never pass the flag"""
        assert _response().body is True

    @pytest.mark.parametrize('given, expected', [(0, False), (1, True), ('', False)],
                             ids=['zero', 'one', 'empty-string'])
    def test_a_truthy_value_is_normalised_to_a_bool(self, given: Any, expected: bool) -> None:
        """The flag is stored as a bool, so `is True` / `is False` hold for a caller passing 0 or 1"""
        assert _response(body=given).body is expected


# -------------------------------------------------------------------------------------------------------------------- #
#                                              the envelope + the url                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class TestEnvelope:
    """The two keys every response carries, and the url the pager builds on."""

    def test_export_carries_the_operation_and_the_time(self) -> None:
        """`response_type` and `time` are declared by the Angular APIResponse type"""
        exported = _response().export()

        assert exported[ResponseKey.RESPONSE_TYPE.value] == OperationType.GET.value
        assert set(exported) == {ResponseKey.RESPONSE_TYPE.value, ResponseKey.TIME.value}

    def test_the_time_is_an_iso_string_in_utc(self) -> None:
        """
        The one deliberate exception to the project's `{'$date': millis}` wire format

        The frontend types it as a string, which is why it is not migrated.
        """
        stamped = datetime.fromisoformat(_response().time)

        assert stamped.tzinfo == timezone.utc
        assert (datetime.now(timezone.utc) - stamped).total_seconds() < 5

    def test_a_missing_url_becomes_an_empty_string(self) -> None:
        """APIPagination builds on it, so it may not be None"""
        assert _response().url == ''

    def test_a_given_url_is_kept(self) -> None:
        """The pager needs the requested url to build its page links"""
        assert _response(url='/rest/objects/').url == '/rest/objects/'

    def test_the_operation_type_is_kept_as_the_member(self) -> None:
        """The type guard that used to sit here could never fire, and raised the wrong error anyway"""
        assert _response().operation_type is OperationType.GET


def test_the_base_class_can_not_be_instantiated() -> None:
    """`make_response` is abstract: only a concrete response knows its status code and its keys"""
    with pytest.raises(TypeError):
        BaseAPIResponse(OperationType.GET)  # pylint: disable=abstract-class-instantiated


# -------------------------------------------------------------------------------------------------------------------- #
#                                            make_body_response                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestMakeBodyResponse:
    """The one place the body flag is honoured - lifted out of the three Get* classes."""

    def test_a_wanted_body_is_serialized(self) -> None:
        """The normal answer: the exported envelope as JSON"""
        response = _response().make_body_response()

        assert response.status_code == 200
        assert loads(response.get_data())[ResponseKey.RESPONSE_TYPE.value] == OperationType.GET.value

    def test_a_suppressed_body_answers_empty(self) -> None:
        """The HEAD case: status and headers, no payload - not even a serialized `null`"""
        response = _response(body=False).make_body_response()

        assert response.status_code == 200
        assert response.get_data() == b''

    def test_a_suppressed_body_is_never_built(self) -> None:
        """
        Nothing is serialized, and `export` is not even called

        A HEAD on a paged collection must not cost the payload the client then throws away - which is
        what it did while the flag was inert.
        """
        with patch.object(_Response, 'export') as export, \
             patch(f'{BASE_PATH}.dumps') as dumps:
            _response(body=False).make_body_response()

        export.assert_not_called()
        dumps.assert_not_called()

    def test_the_status_code_can_be_chosen(self) -> None:
        """It is a keyword, so a subclass can answer 201/202 without colliding with export's args"""
        assert _response().make_body_response(status=202).status_code == 202

    def test_the_status_code_survives_a_suppressed_body(self) -> None:
        """A bodyless answer is still the same answer"""
        assert _response(body=False).make_body_response(status=202).status_code == 202

    def test_arguments_reach_export(self) -> None:
        """This is how `GetMultiResponse.make_response(pagination=False)` suppresses its pager block"""
        with patch.object(_Response, 'export', return_value={}) as export:
            _response().make_body_response('positional', pagination=False)

        export.assert_called_once_with('positional', pagination=False)


# -------------------------------------------------------------------------------------------------------------------- #
#                                             make_api_response                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestMakeApiResponse:
    """The single serialization point of the whole REST API."""

    def test_the_payload_is_serialized_as_json(self) -> None:
        """What every route ultimately answers with"""
        response = _response().make_api_response(PAYLOAD)

        assert loads(response.get_data()) == PAYLOAD
        assert response.mimetype == DEFAULT_MIME_TYPE

    def test_the_api_version_header_is_set(self) -> None:
        """Part of the contract every response carries"""
        response = _response().make_api_response(PAYLOAD)

        assert response.headers[ResponseHeader.API_VERSION.value] == API_VERSION

    def test_the_body_is_pretty_printed(self) -> None:
        """
        Pinned deliberately: it costs +63% body size on a 50-object page (backlog #215)

        The test is here so that changing it is a decision rather than an accident.
        """
        assert b'\n' in _response().make_api_response(PAYLOAD).get_data()

    def test_a_compact_dump_can_be_asked_for(self) -> None:
        """The indent is a parameter, which is what a later decision on #215 would flip"""
        assert _response().make_api_response(PAYLOAD, indent=None).get_data() == b'{"value": 1}'

    def test_a_datetime_leaves_in_the_projects_wire_format(self) -> None:
        """`json_codec.default` is applied here - this is where `{'$date': millis}` is produced"""
        stamp = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)

        answered = loads(_response().make_api_response({'creation_time': stamp}).get_data())

        assert answered == {'creation_time': {'$date': int(stamp.timestamp() * 1000)}}

    def test_an_object_id_leaves_in_extended_json(self) -> None:
        """
        The other half of what the codec is for: a raw Mongo document may be answered directly

        `_id` is answered as MongoDB extended JSON (`{'$oid': hex}`), which is what pymongo's own
        encoder produces - routes that must not expose it project it away instead.
        """
        oid = ObjectId()

        assert loads(_response().make_api_response({'_id': oid}).get_data()) == {'_id': {'$oid': str(oid)}}

    def test_a_chosen_status_and_mime_are_used(self) -> None:
        """Both are parameters because the insert/update/delete responses set their own status"""
        response = _response().make_api_response(PAYLOAD, 201, mime='text/plain')

        assert response.status_code == 201
        assert response.mimetype == 'text/plain'

    def test_an_unserializable_payload_aborts_with_500(self) -> None:
        """A payload the codec cannot encode is a server fault, not a bad request"""
        with pytest.raises(HTTPException) as exc_info:
            _response().make_api_response({'ports': {1, 2}})

        assert exc_info.value.code == 500
        assert 'Failed to create a response' in exc_info.value.description

    def test_the_failure_is_logged_with_its_traceback(self, caplog) -> None:
        """
        It was logged at DEBUG, below the WARNING the product runs at

        So the caller got "Failed to create a response from the given data!" and operations got
        nothing at all - for the one function every response passes through.
        """
        with caplog.at_level('ERROR'):
            with pytest.raises(HTTPException):
                _response().make_api_response({'ports': {1, 2}})

        assert '[make_api_response]' in caplog.text
        assert 'Traceback' in caplog.text


class TestMakeEmptyResponse:
    """The bodyless answer, on its own."""

    def test_it_carries_the_headers_but_no_payload(self) -> None:
        """A HEAD answer still has to be a valid API response"""
        response = _response().make_empty_response()

        assert response.get_data() == b''
        assert response.headers[ResponseHeader.API_VERSION.value] == API_VERSION
        assert response.mimetype == DEFAULT_MIME_TYPE

    def test_nothing_is_serialized(self) -> None:
        """Not even `None`: the point is to pay nothing"""
        with patch(f'{BASE_PATH}.dumps') as dumps:
            _response().make_empty_response()

        dumps.assert_not_called()

    def test_the_status_is_honoured(self) -> None:
        """The delete response answers 204, and it may want to do so without a payload"""
        assert _response().make_empty_response(204).status_code == 204


# -------------------------------------------------------------------------------------------------------------------- #
#                                              apply_projection                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestApplyProjection:
    """One implementation of `?projection=`, shared by the three Get* responses."""

    DOCUMENT: dict[str, Any] = {'public_id': 1, 'name': 'server', 'label': 'Server'}

    def test_no_projection_returns_the_data_untouched(self) -> None:
        """Most requests carry none, and the caller passes whatever it holds"""
        assert BaseAPIResponse.apply_projection(self.DOCUMENT, None) is self.DOCUMENT

    def test_an_empty_projection_returns_the_data_untouched(self) -> None:
        """An empty dict means the client asked for nothing in particular"""
        assert BaseAPIResponse.apply_projection(self.DOCUMENT, {}) is self.DOCUMENT

    def test_a_single_document_is_trimmed(self) -> None:
        """The GetSingleResponse case"""
        assert BaseAPIResponse.apply_projection(self.DOCUMENT, {'public_id': 1}) == {'public_id': 1}

    def test_a_list_is_trimmed_element_by_element(self) -> None:
        """The GetListResponse / GetMultiResponse case: the shape is preserved"""
        projected = BaseAPIResponse.apply_projection([self.DOCUMENT, self.DOCUMENT], ['name'])

        assert projected == [{'name': 'server'}, {'name': 'server'}]

    def test_a_list_projection_is_read_as_all_includes(self) -> None:
        """The frontend sends a list of field names (`type.service.ts`), not a Mongo-style mapping"""
        assert BaseAPIResponse.apply_projection(self.DOCUMENT, ['public_id', 'name']) \
            == {'public_id': 1, 'name': 'server'}
