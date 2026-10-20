# DATAGERRY - OpenSource Enterprise CMDB
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
The `?filter=` disclosures, driven over HTTP

Each request below answers 200 without the guard, as an ordinary
authenticated caller with nothing but a list right. They are kept here as requests rather than as unit
calls because what made the finding real was the status code and the response body, not the shape of
an argument: the first one returned a stored password digest.

`/users/` is the route used throughout, for the reason it is the sharpest: `CmdbUser.to_public_json`
exists precisely to keep the digest out of every user response, and the `$lookup` walked around it on
the route it guards. The guard is not in the route, though - it is in `CollectionParameters`, so it
covers all 45 list routes and the ISMS report routes that splice `params.filter` into a pipeline of
their own without ever reaching the query builder.
"""
from http import HTTPStatus
from json import dumps
from typing import Any

import pytest
# -------------------------------------------------------------------------------------------------------------------- #

USERS_ROUTE: str = '/users/'

JS_FUNCTION: dict[str, Any] = {'$function': {'body': 'function(){ return 1; }', 'args': [], 'lang': 'js'}}

#: Each of these answered 200 before the guard; the first returned `"password": "<digest>"`
VERIFIED_EXPLOITS: list[tuple[str, list[dict[str, Any]]]] = [
    ('lookup into the user collection', [
        {'$match': {}},
        {'$lookup': {'from': 'management.users', 'pipeline': [{'$limit': 1}], 'as': 'email'}},
    ]),
    ('graphLookup into the user collection', [
        {'$match': {}},
        {'$graphLookup': {'from': 'management.users', 'startWith': '$public_id',
                          'connectFromField': 'public_id', 'connectToField': 'public_id', 'as': 'email'}},
    ]),
    ('unionWith the user collection', [
        {'$match': {}},
        {'$unionWith': {'coll': 'management.users'}},
    ]),
    ('server-side JavaScript in $addFields', [
        {'$match': {}},
        {'$addFields': {'email': JS_FUNCTION}},
    ]),
    ('server-side JavaScript inside $match', [
        {'$match': {'$expr': {'$eq': [JS_FUNCTION, 1]}}},
    ]),
]


def _get_with_filter(rest_api, pipeline: Any):
    """Issues the list call carrying the pipeline as the `?filter=` query parameter."""
    return rest_api.get(f'{USERS_ROUTE}?filter={dumps(pipeline)}')


class TestTheVerifiedExploitsAreRefused:
    """Each one is a request that would answer 200 with data the caller may not have."""

    @pytest.mark.parametrize('label,pipeline', VERIFIED_EXPLOITS, ids=[e[0] for e in VERIFIED_EXPLOITS])
    def test_it_answers_400(self, rest_api, label: str, pipeline: list[dict[str, Any]]) -> None:
        """Refused at the parameter boundary, so the aggregation is never built."""
        assert _get_with_filter(rest_api, pipeline).status_code == HTTPStatus.BAD_REQUEST

    def test_no_password_digest_can_come_back(self, rest_api) -> None:
        """
        The finding itself, stated as the property that matters

        A status assertion alone would still pass if some future path answered 200 with the document
        and a different code path produced the 400.
        """
        response = _get_with_filter(rest_api, VERIFIED_EXPLOITS[0][1])

        assert 'password' not in response.get_data(as_text=True)

    def test_the_rejection_says_which_stage_was_refused(self, rest_api) -> None:
        """
        The message reaches the caller (finding B2)

        A rejection from the parameter package must not be flattened into
        *"Failed to parse the request parameters!"*, which told a client nothing and told a developer
        less. A refused stage now names itself.
        """
        body = _get_with_filter(rest_api, [{'$match': {}}, {'$out': 'sink'}]).get_data(as_text=True)

        assert '$out' in body


class TestOrdinaryFiltersStillWork:
    """A guard that refuses everything is indistinguishable from a broken route."""

    def test_a_plain_document_filter_is_served(self, rest_api) -> None:
        """The shape almost every list call actually sends."""
        response = rest_api.get(f'{USERS_ROUTE}?filter={dumps({"public_id": 1})}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['results'][0]['public_id'] == 1

    def test_a_stage_shaped_filter_the_frontend_builds_is_served(self, rest_api) -> None:
        """
        `$match` + `$addFields` + `$toString`, the delivery-log and report search shape

        The frontend genuinely sends stages, which is why the fix is an allow-list rather than a
        refusal of list-shaped filters.
        """
        pipeline = [
            {'$addFields': {'public_id_str': {'$toString': '$public_id'}}},
            {'$match': {'public_id_str': {'$regex': '1', '$options': 'i'}}},
        ]

        assert _get_with_filter(rest_api, pipeline).status_code == HTTPStatus.OK

    def test_no_filter_at_all_is_served(self, rest_api) -> None:
        """The baseline the other assertions are measured against."""
        assert rest_api.get(USERS_ROUTE).status_code == HTTPStatus.OK
