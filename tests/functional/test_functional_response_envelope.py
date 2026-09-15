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
Functional tests for the REST API response envelope

Every route answers through `cmdb/interface/rest_api/responses/`, and what arrives at the client -
the keys, the two headers, the status code and whether there is a body at all - is a frontend
contract. The unit tests pin the classes; these pin what actually leaves the server, over real HTTP.

The `HEAD` assertions are the reason this module exists. 28 routes asked for a bodyless answer with
the flag INVERTED, and the flag itself was inert (`body or True`), so a HEAD request built and
serialized its whole payload and then relied on werkzeug to drop it. Both halves were fixed on
2026-09-09; a regression on either would be invisible without these tests, because werkzeug still
drops the body afterwards.

The users routes are used because `conftest` seeds exactly one CmdbUser, so the counts are known
"""
from http import HTTPStatus
from json import dumps
from unittest.mock import patch
# -------------------------------------------------------------------------------------------------------------------- #

USERS_URL: str = '/users'
ADMIN_ID: int = 1

RESPONSE_TYPE_KEY: str = 'response_type'
TIME_KEY: str = 'time'
RESULT_KEY: str = 'result'
RESULTS_KEY: str = 'results'
COUNT_KEY: str = 'count'
TOTAL_KEY: str = 'total'
PAGER_KEY: str = 'pager'

API_VERSION_HEADER: str = 'X-API-Version'
TOTAL_COUNT_HEADER: str = 'X-Total-Count'


class TestCollectionEnvelope:
    """GET a paged collection: the envelope, the pager block and the headers."""

    def test_the_envelope_carries_the_page_and_the_counts(self, rest_api) -> None:
        """What the Angular APIGetMultiResponse type declares"""
        payload = rest_api.get(f'{USERS_URL}/').get_json()

        assert payload[RESULTS_KEY][0]['public_id'] == ADMIN_ID
        assert payload[COUNT_KEY] == 1
        assert payload[TOTAL_KEY] == 1
        assert payload[RESPONSE_TYPE_KEY] == 'GET'
        assert TIME_KEY in payload
        assert PAGER_KEY in payload

    def test_both_api_headers_are_set(self, rest_api) -> None:
        """The version on every response, the total count on every collection"""
        response = rest_api.get(f'{USERS_URL}/')

        assert response.headers[API_VERSION_HEADER] == '1.0'
        assert response.headers[TOTAL_COUNT_HEADER] == '1'

    def test_the_body_is_json(self, rest_api) -> None:
        """Set explicitly by the response class rather than left to Flask"""
        assert rest_api.get(f'{USERS_URL}/').mimetype == 'application/json'

    def test_a_projection_trims_the_rows(self, rest_api) -> None:
        """
        `?projection=` is applied to what leaves the server

        The frontend sends it (`type.service.ts`), the projector helpers were fully covered, and the
        three lines wiring the two together were not tested at all until 2026-09-09.
        """
        response = rest_api.get(f'{USERS_URL}/?projection={dumps({"public_id": 1})}')

        assert response.get_json()[RESULTS_KEY] == [{'public_id': ADMIN_ID}]


class TestSingleEnvelope:
    """GET one resource: the `result` key and the version header."""

    def test_the_resource_is_answered_under_result(self, rest_api) -> None:
        """What the Angular APIGetSingleResponse type declares"""
        payload = rest_api.get(f'{USERS_URL}/{ADMIN_ID}').get_json()

        assert payload[RESULT_KEY]['public_id'] == ADMIN_ID
        assert payload[RESPONSE_TYPE_KEY] == 'GET'

    def test_the_stored_password_is_not_part_of_it(self, rest_api) -> None:
        """The user routes answer `to_public_json`; asserted here because this is the wire"""
        assert 'password' not in rest_api.get(f'{USERS_URL}/{ADMIN_ID}').get_json()[RESULT_KEY]


class TestHeadRequests:
    """HEAD: the same status and headers as GET, and no body at all."""

    def test_a_collection_head_answers_without_a_body(self, rest_api) -> None:
        """The client asked how many there are, not what they are"""
        response = rest_api.head(f'{USERS_URL}/')

        assert response.status_code == HTTPStatus.OK
        assert response.get_data() == b''

    def test_a_collection_head_still_reports_the_total(self, rest_api) -> None:
        """Which is what makes a bodyless collection answer useful at all"""
        assert rest_api.head(f'{USERS_URL}/').headers[TOTAL_COUNT_HEADER] == '1'

    def test_a_collection_head_still_reports_the_api_version(self, rest_api) -> None:
        """Every response carries it, body or not"""
        assert rest_api.head(f'{USERS_URL}/').headers[API_VERSION_HEADER] == '1.0'

    def test_a_single_head_answers_without_a_body(self, rest_api) -> None:
        """Same rule for a single resource: the caller only wanted the status"""
        response = rest_api.head(f'{USERS_URL}/{ADMIN_ID}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_data() == b''

    def test_nothing_is_serialized_for_a_head_request(self, rest_api) -> None:
        """
        The payload is not built at all - the point of the fix, and not otherwise observable

        Werkzeug drops the body of a HEAD response either way, so the only way to see the difference
        is to watch the serializer: a GET calls it, a HEAD does not.
        """
        target: str = 'cmdb.interface.rest_api.responses.base_api_response.dumps'

        with patch(target, wraps=dumps) as serializer:
            rest_api.get(f'{USERS_URL}/')

        assert serializer.called

        with patch(target, wraps=dumps) as serializer:
            rest_api.head(f'{USERS_URL}/')

        assert not serializer.called

    def test_a_head_on_a_missing_resource_is_still_a_404(self, rest_api) -> None:
        """The refusal is not a payload, so suppressing the body may not suppress the error"""
        assert rest_api.head(f'{USERS_URL}/9999').status_code == HTTPStatus.NOT_FOUND
