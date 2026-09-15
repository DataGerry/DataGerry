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
Unit tests for the concrete API response classes

One class per operation, and what each one answers - its status code, its payload keys and its
headers - is a **frontend contract**: `app/src/app/services/models/api-response.ts` declares the keys
and four Angular services read `X-Total-Count`. Nothing pinned any of it until 2026-09-09, so a
renamed key or a changed status code passed the whole backend suite.

The three Get* classes additionally carry the `?projection=` wiring (the frontend sends it from
`type.service.ts`) and the bodyless HEAD answer, both of which were untested while the `body` flag was
inert - `APIProjector` itself was at 100%, only the three lines that reach it were not.
"""
from json import loads
from typing import Any
from unittest.mock import MagicMock

import pytest
from flask import Flask

from cmdb.interface.rest_api.responses import (
    DefaultResponse,
    DeleteSingleResponse,
    GetListResponse,
    GetMultiResponse,
    GetSingleResponse,
    InsertSingleResponse,
    LoginResponse,
    UpdateMultiResponse,
    UpdateSingleResponse,
)
from cmdb.interface.rest_api.responses.helpers.operation_type_enum import OperationType
from cmdb.interface.rest_api.responses.response_constants import ResponseHeader, ResponseKey
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

DOCUMENT: dict[str, Any] = {'public_id': 1, 'name': 'server', 'label': 'Server'}
SECOND_DOCUMENT: dict[str, Any] = {'public_id': 2, 'name': 'switch', 'label': 'Switch'}
TOTAL: int = 137


@pytest.fixture(autouse=True)
def _app_ctx():
    """A request context around every test; taken for its side effect only"""
    with Flask(__name__).test_request_context('/rest/whatever'):
        yield


def _params(**overrides: Any) -> CollectionParameters:
    """CollectionParameters as the pager decorator hands them to a route"""
    values: dict[str, Any] = {'query_string': '', 'limit': 10, 'sort': 'public_id', 'order': 1, 'page': 1}
    values.update(overrides)

    return CollectionParameters(**values)


def _payload(response) -> dict[str, Any]:
    """The decoded body of a response"""
    return loads(response.make_response().get_data())


# -------------------------------------------------------------------------------------------------------------------- #
#                                              GetSingleResponse                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetSingleResponse:
    """GET one resource: 200 and a `result` key."""

    def test_it_answers_the_resource_under_result(self) -> None:
        """The key the Angular APIGetSingleResponse type reads"""
        assert _payload(GetSingleResponse(DOCUMENT))[ResponseKey.RESULT.value] == DOCUMENT

    def test_it_answers_200(self) -> None:
        """A read never invents another status"""
        assert GetSingleResponse(DOCUMENT).make_response().status_code == 200

    def test_it_carries_the_envelope_keys(self) -> None:
        """Every response does, and the operation is a GET"""
        payload = _payload(GetSingleResponse(DOCUMENT))

        assert payload[ResponseKey.RESPONSE_TYPE.value] == OperationType.GET.value
        assert ResponseKey.TIME.value in payload

    def test_a_projection_trims_the_result(self) -> None:
        """The wiring the frontend's `?projection=` reaches - untested until 2026-09-09"""
        response = GetSingleResponse(DOCUMENT, projection={'name': 1})

        assert _payload(response)[ResponseKey.RESULT.value] == {'name': 'server'}

    def test_a_head_request_gets_no_body(self) -> None:
        """`body=False` answers with the status and the headers only"""
        response = GetSingleResponse(DOCUMENT, body=False).make_response()

        assert response.status_code == 200
        assert response.get_data() == b''


# -------------------------------------------------------------------------------------------------------------------- #
#                                               GetListResponse                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetListResponse:
    """GET a plain list: 200, a `results` key and the count as a header."""

    def test_it_answers_the_resources_under_results(self) -> None:
        """In the order they were read - a list route does not sort by itself"""
        assert _payload(GetListResponse([DOCUMENT, SECOND_DOCUMENT]))[ResponseKey.RESULTS.value] \
            == [DOCUMENT, SECOND_DOCUMENT]

    def test_the_count_is_reported_as_a_header(self) -> None:
        """Read by four Angular services to size a collection without parsing the body"""
        response = GetListResponse([DOCUMENT, SECOND_DOCUMENT]).make_response()

        assert response.headers[ResponseHeader.TOTAL_COUNT.value] == '2'

    def test_the_header_survives_a_bodyless_answer(self) -> None:
        """Which is the whole point of a HEAD request on a list route"""
        response = GetListResponse([DOCUMENT], body=False).make_response()

        assert response.get_data() == b''
        assert response.headers[ResponseHeader.TOTAL_COUNT.value] == '1'

    def test_a_projection_from_the_parameters_trims_the_rows(self) -> None:
        """This class reads the projection off its APIParameters rather than taking it directly"""
        params = MagicMock()
        params.projection = ['name']

        payload = _payload(GetListResponse([DOCUMENT, SECOND_DOCUMENT], params=params))

        assert payload[ResponseKey.RESULTS.value] == [{'name': 'server'}, {'name': 'switch'}]

    def test_no_parameters_is_a_normal_call(self) -> None:
        """Most list routes pass none at all, and then nothing is projected"""
        assert _payload(GetListResponse([DOCUMENT]))[ResponseKey.RESULTS.value] == [DOCUMENT]


# -------------------------------------------------------------------------------------------------------------------- #
#                                              GetMultiResponse                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetMultiResponse:
    """GET a paged collection: 200, the page, the totals and the pager block."""

    def test_it_answers_the_page_with_its_counts(self) -> None:
        """`count` is what this page holds, `total` what the request matches overall"""
        payload = _payload(GetMultiResponse([DOCUMENT], TOTAL, _params(), '/rest/objects/'))

        assert payload[ResponseKey.RESULTS.value] == [DOCUMENT]
        assert payload[ResponseKey.COUNT.value] == 1
        assert payload[ResponseKey.TOTAL.value] == TOTAL

    def test_the_pager_block_is_included(self) -> None:
        """Three keys the frontend's APIGetMultiResponse declares as optional"""
        payload = _payload(GetMultiResponse([DOCUMENT], TOTAL, _params(), '/rest/objects/'))

        assert {ResponseKey.PARAMETERS.value, ResponseKey.PAGER.value, ResponseKey.PAGINATION.value} \
            <= set(payload)

    def test_a_route_can_suppress_the_pager_block(self) -> None:
        """`make_response(pagination=False)` - used by the rights and categories list routes"""
        response = GetMultiResponse([DOCUMENT], TOTAL, _params(), '/rest/rights/')
        payload = loads(response.make_response(pagination=False).get_data())

        assert ResponseKey.PAGER.value not in payload
        assert payload[ResponseKey.TOTAL.value] == TOTAL

    def test_the_total_is_reported_as_a_header(self) -> None:
        """The complete count, not the size of this page"""
        response = GetMultiResponse([DOCUMENT], TOTAL, _params(), '/rest/objects/').make_response()

        assert response.headers[ResponseHeader.TOTAL_COUNT.value] == str(TOTAL)

    def test_the_header_survives_a_bodyless_answer(self) -> None:
        """A HEAD on a collection answers how many there are and nothing else"""
        response = GetMultiResponse(
            [DOCUMENT], TOTAL, _params(), '/rest/objects/', body=False,
        ).make_response()

        assert response.get_data() == b''
        assert response.headers[ResponseHeader.TOTAL_COUNT.value] == str(TOTAL)

    def test_a_projection_trims_the_rows(self) -> None:
        """The frontend sends `?projection=` as a list of field names"""
        payload = _payload(GetMultiResponse(
            [DOCUMENT, SECOND_DOCUMENT], TOTAL, _params(projection=['name']), '/rest/types/',
        ))

        assert payload[ResponseKey.RESULTS.value] == [{'name': 'server'}, {'name': 'switch'}]

    def test_the_page_count_comes_from_the_limit(self) -> None:
        """Ordinary paging arithmetic, pinned because the pager block reports it"""
        payload = _payload(GetMultiResponse([DOCUMENT], 25, _params(limit=10), '/rest/objects/'))

        assert payload[ResponseKey.PAGER.value]['total_pages'] == 3

    def test_an_unlimited_request_is_one_page(self) -> None:
        """`?limit=0` means "everything", which cannot be divided into pages"""
        payload = _payload(GetMultiResponse([DOCUMENT], 25, _params(limit=0), '/rest/objects/'))

        assert payload[ResponseKey.PAGER.value]['total_pages'] == 1


# -------------------------------------------------------------------------------------------------------------------- #
#                                          the write responses                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestInsertSingleResponse:
    """POST: 201, the new id and the stored document."""

    def test_it_answers_201_with_the_new_id_and_the_document(self) -> None:
        """The frontend reads `result_id` to navigate to what it just created"""
        response = InsertSingleResponse(DOCUMENT, 1)
        payload = loads(response.make_response().get_data())

        assert response.make_response().status_code == 201
        assert payload[ResponseKey.RESULT_ID.value] == 1
        assert payload[ResponseKey.RAW.value] == DOCUMENT
        assert payload[ResponseKey.RESPONSE_TYPE.value] == OperationType.INSERT.value


class TestUpdateSingleResponse:
    """PUT / PATCH: 202 and the updated resource."""

    def test_it_answers_202_with_the_result(self) -> None:
        """202 rather than 200, consistently across every update route"""
        response = UpdateSingleResponse(DOCUMENT)
        payload = loads(response.make_response().get_data())

        assert response.make_response().status_code == 202
        assert payload[ResponseKey.RESULT.value] == DOCUMENT
        assert payload[ResponseKey.RESPONSE_TYPE.value] == OperationType.UPDATE.value


class TestUpdateMultiResponse:
    """A bulk update: 202, what went through and what did not."""

    def test_it_answers_202_with_results_and_failed(self) -> None:
        """A partial bulk update is a success carrying its rejections"""
        response = UpdateMultiResponse([DOCUMENT], ['nope'])
        payload = loads(response.make_response().get_data())

        assert response.make_response().status_code == 202
        assert payload[ResponseKey.RESULTS.value] == [DOCUMENT]
        assert payload[ResponseKey.FAILED.value] == ['nope']

    def test_no_failures_is_an_empty_list(self) -> None:
        """The key is always present, so a client can read it unconditionally"""
        assert loads(UpdateMultiResponse([DOCUMENT]).make_response().get_data())[
            ResponseKey.FAILED.value] == []


class TestDeleteSingleResponse:
    """DELETE: 202 when the deleted resource is reported, 204 when there is nothing to report."""

    def test_a_reported_resource_answers_202(self) -> None:
        """The delete routes answer with what they removed"""
        response = DeleteSingleResponse(DOCUMENT)
        payload = loads(response.make_response().get_data())

        assert response.make_response().status_code == 202
        assert payload[ResponseKey.RAW.value] == DOCUMENT
        assert payload[ResponseKey.RESPONSE_TYPE.value] == OperationType.DELETE.value

    def test_nothing_to_report_answers_204(self) -> None:
        """Which is why the key is nullable in the frontend model"""
        assert DeleteSingleResponse().make_response().status_code == 204


class TestDefaultResponse:
    """Anything that is just a value - no envelope, the value itself."""

    def test_it_answers_the_value_verbatim(self) -> None:
        """Used by the routes whose answer is a bool, a list or a computed dict"""
        assert loads(DefaultResponse(True).make_response().get_data()) is True

    def test_the_status_can_be_chosen(self) -> None:
        """The one response class that lets a route pick its status code"""
        assert DefaultResponse({'ok': True}).make_response(status=201).status_code == 201

    def test_it_sends_the_body_by_default(self) -> None:
        """Most callers are not HEAD-capable routes, so nothing had to change for them"""
        assert loads(DefaultResponse(DOCUMENT).make_response().get_data()) == DOCUMENT

    def test_a_bodyless_response_serializes_nothing(self) -> None:
        """
        The HEAD case, which this class ignored until 2026-09-10

        The envelope sweep taught the three Get* classes to answer HEAD without building the
        payload; DefaultResponse kept serializing it for werkzeug to throw away.
        """
        response = DefaultResponse(DOCUMENT, body=False).make_response()

        assert response.get_data(as_text=True) == ''
        assert response.status_code == 200

    def test_a_bodyless_response_keeps_its_status(self) -> None:
        """A route that picks a status still gets it without a payload"""
        assert DefaultResponse(DOCUMENT, body=False).make_response(status=201).status_code == 201


class TestLoginResponse:
    """The token exchange: user plus token, deliberately without the envelope keys."""

    @staticmethod
    def _login_payload() -> dict[str, Any]:
        """A LoginResponse over a real CmdbUser (its export insists on the model, by design)"""
        user = CmdbUser(public_id=1, user_name='admin', active=True, group_id=1)

        return LoginResponse(user, b'the-token', 1757000000, 1757003600).export()

    def test_it_carries_the_token_and_its_lifetime(self) -> None:
        """Decoded, because the token is generated as bytes"""
        payload = self._login_payload()

        assert payload['token'] == 'the-token'
        assert payload['token_issued_at'] == 1757000000
        assert payload['token_expire'] == 1757003600

    def test_it_deliberately_has_no_envelope_keys(self) -> None:
        """It is the token exchange rather than a resource read; the login flow reads the four keys"""
        payload = self._login_payload()

        assert ResponseKey.RESPONSE_TYPE.value not in payload
        assert ResponseKey.TIME.value not in payload

    def test_it_never_answers_the_stored_password(self) -> None:
        """`to_public_json`, never `to_json` - the digest may not leave the server"""
        assert 'password' not in self._login_payload()['user']
