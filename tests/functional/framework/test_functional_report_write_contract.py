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
What a CmdbReport write accepts, and where it accepts it from

The report write routes validate no request schema - the payload is not the document (the query is
built server-side, and a query-string payload carries every value as text), so what stands in for one
is the route helper's own coercions and shape checks. This pins them.

Two halves:

* **shape** - a value that is not what the write reads it as is a **400**. A non-dict `conditions` is
  read as a rule tree (`.get`) and a non-list `selected_fields` as a set of names, so both reach the
  route as an AttributeError / TypeError and answer **500** unless they are refused first; a dict
  under `selected_fields` and a blank `name` do not raise at all and are stored instead, leaving a
  document the CmdbReport schema rejects.
* **transport** - the payload is read from a JSON **body** when one is sent and from the query string
  otherwise, so a caller may use either. The Angular report form sends **both**, which is served from
  the body; a rule tree does not belong in a URL, where it counts against the request-line limit and
  is written to every access log in plain text.

The seeding is shared with `test_functional_report_route.py` rather than repeated - the same Type and
Category, so the two files describe one surface.
"""
import json
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.type_model import CmdbType
from cmdb.models.reports_model.cmdb_report_category import CmdbReportCategory

from tests.functional.framework.test_functional_report_route import (
    ALL_TYPE_IDS,
    EMPTY_CONDITIONS,
    PLAIN_FIELD,
    PLAIN_TYPE_ID,
    REPORT_CATEGORY_ID,
    ROUTE_URL,
    _report_params,
    _reports,
    _type_doc,
)
# -------------------------------------------------------------------------------------------------------------------- #

REPORT_NAME: str = 'Write Contract Report'


@pytest.fixture(name='seeded', autouse=True)
def fixture_seeded(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the Type and the Category a report write resolves, and clears the written reports."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    categories = database_manager.get_collection(CmdbReportCategory.COLLECTION, database_name)
    reports = _reports(database_manager, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': {'$in': ALL_TYPE_IDS}})
        categories.delete_one({'public_id': REPORT_CATEGORY_ID})
        reports.delete_many({'report_category_id': REPORT_CATEGORY_ID})

    _purge()
    types.insert_one(_type_doc(PLAIN_TYPE_ID, [{'type': 'text', 'name': PLAIN_FIELD, 'label': 'A'}]))
    categories.insert_one({'public_id': REPORT_CATEGORY_ID, 'name': 'Contract', 'predefined': False})

    yield reports

    _purge()


def _query_params(**overrides: Any) -> dict[str, Any]:
    """A query-string payload: every value is text, both JSON values are encoded."""
    params = _report_params(name=REPORT_NAME)
    params.update(overrides)

    return params


def _body(**overrides: Any) -> dict[str, Any]:
    """The object `create-report.component.ts` builds, with the values already typed."""
    payload: dict[str, Any] = {
        'report_category_id': REPORT_CATEGORY_ID,
        'name': REPORT_NAME,
        'type_id': PLAIN_TYPE_ID,
        'selected_fields': [PLAIN_FIELD],
        'conditions': EMPTY_CONDITIONS,
        'report_query': {},
        'predefined': False,
        'mds_mode': 'ROWS',
    }
    payload.update(overrides)

    return payload


def _as_query_string(body: dict[str, Any]) -> dict[str, str]:
    """The same object as `report.service.ts` encodes it into query parameters."""
    return {
        key: json.dumps(value) if isinstance(value, (dict, list)) else str(value)
        for key, value in body.items()
    }


def _stored(reports, public_id: int) -> dict[str, Any]:
    """The written document."""
    return reports.find_one({'public_id': public_id}) or {}


# -------------------------------------------------------------------------------------------------------------------- #
#                                               A MALFORMED VALUE IS A 400                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class TestAMalformedValueIsRefused:
    """Each of these answered 500, or was stored as a document the schema rejects."""

    @pytest.mark.parametrize('conditions', ['"hello"', '[1, 2]', '5', 'true'], ids=repr)
    def test_conditions_that_are_not_a_rule_tree(self, rest_api, conditions: str) -> None:
        """Read as `{'condition': ..., 'rules': [...]}` further down, so anything else raised"""
        response = rest_api.post(f'{ROUTE_URL}/', query_string=_query_params(conditions=conditions))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'conditions' in response.get_json()['message']

    @pytest.mark.parametrize('selected_fields', ['{"a": 1}', '7', '"text-a"', 'null'], ids=repr)
    def test_selected_fields_that_are_not_a_list(self, rest_api, selected_fields: str) -> None:
        """A dict is the shape that survived `set(...)` and was stored as the report's columns"""
        response = rest_api.post(f'{ROUTE_URL}/', query_string=_query_params(selected_fields=selected_fields))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'selected_fields' in response.get_json()['message']

    @pytest.mark.parametrize('selected_fields', ['[1, {"x": 2}]', '["text-a", null]', '["  "]'], ids=repr)
    def test_a_selected_field_that_is_not_a_name(self, rest_api, selected_fields: str) -> None:
        """An unhashable entry was a TypeError inside `set(...)`, and a blank one names no field"""
        response = rest_api.post(f'{ROUTE_URL}/', query_string=_query_params(selected_fields=selected_fields))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    @pytest.mark.parametrize('name', ['', '   '], ids=repr)
    def test_a_blank_name(self, rest_api, name: str) -> None:
        """A report with no name leaves a row nothing can identify"""
        response = rest_api.post(f'{ROUTE_URL}/', query_string=_query_params(name=name))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_an_unreadable_id(self, rest_api) -> None:
        """The refusal names the parameter rather than reporting 'one or more'"""
        response = rest_api.post(f'{ROUTE_URL}/', query_string=_query_params(type_id='abc'))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'type_id' in response.get_json()['message']

    def test_nothing_is_written_when_a_value_is_refused(self, rest_api, seeded) -> None:
        """A refused write leaves no document behind"""
        rest_api.post(f'{ROUTE_URL}/', query_string=_query_params(conditions='[1, 2]'))

        assert seeded.count_documents({'name': REPORT_NAME}) == 0

    def test_the_update_route_refuses_the_same_shapes(self, rest_api, seeded) -> None:
        """Both write routes share the payload builder, so neither can drift from the other"""
        created = rest_api.post(f'{ROUTE_URL}/', query_string=_query_params())
        public_id = created.get_json()

        response = rest_api.put(
            f'{ROUTE_URL}/{public_id}', query_string=_query_params(selected_fields='{"a": 1}'),
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _stored(seeded, public_id)['selected_fields'] == [PLAIN_FIELD]


# -------------------------------------------------------------------------------------------------------------------- #
#                                             WHAT IS DELIBERATELY ACCEPTED                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class TestWhatIsStillAccepted:
    """The guards may not cost a legitimate write."""

    def test_a_query_string_payload_is_written(self, rest_api, seeded) -> None:
        """The shape every caller used before a body was read at all"""
        response = rest_api.post(f'{ROUTE_URL}/', query_string=_query_params())

        assert response.status_code == HTTPStatus.OK
        assert _stored(seeded, response.get_json())['name'] == REPORT_NAME

    def test_null_conditions_mean_no_conditions(self, rest_api, seeded) -> None:
        """Which is what an absent tree already resolves to"""
        response = rest_api.post(f'{ROUTE_URL}/', query_string=_query_params(conditions='null'))

        assert response.status_code == HTTPStatus.OK
        assert _stored(seeded, response.get_json())['conditions'] is None

    def test_a_report_without_conditions_still_runs(self, rest_api) -> None:
        """Accepting the null is only safe if the report it produces is runnable"""
        public_id = rest_api.post(f'{ROUTE_URL}/', query_string=_query_params(conditions='null')).get_json()

        assert rest_api.get(f'{ROUTE_URL}/run/{public_id}').status_code == HTTPStatus.OK

    def test_an_empty_selection_is_written(self, rest_api, seeded) -> None:
        """A report under construction selects nothing yet"""
        response = rest_api.post(f'{ROUTE_URL}/', query_string=_query_params(selected_fields='[]'))

        assert response.status_code == HTTPStatus.OK
        assert _stored(seeded, response.get_json())['selected_fields'] == []

    def test_an_unknown_mds_mode_still_falls_back(self, rest_api, seeded) -> None:
        """Deliberate, and unchanged: only the two known modes mean anything"""
        response = rest_api.post(f'{ROUTE_URL}/', query_string=_query_params(mds_mode='NOT-A-MODE'))

        assert response.status_code == HTTPStatus.OK
        assert _stored(seeded, response.get_json())['mds_mode'] == 'ROWS'

    def test_the_server_owned_keys_are_still_dropped(self, rest_api, seeded) -> None:
        """A client can set neither the identity, nor 'predefined', nor the compiled query"""
        response = rest_api.post(f'{ROUTE_URL}/', query_string=_query_params(
            public_id='999', predefined='true', report_query='{"data": "x"}', injected='value',
        ))
        document = _stored(seeded, response.get_json())

        assert response.get_json() != 999
        assert document['predefined'] is False
        assert 'injected' not in document


# -------------------------------------------------------------------------------------------------------------------- #
#                                            WHERE THE PAYLOAD MAY BE SENT                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class TestThePayloadMayBeSentAsABody:
    """A rule tree does not belong in a URL - and the frontend already sends a body."""

    def test_a_body_only_request_is_written(self, rest_api, seeded) -> None:
        """No query string at all: the values arrive already typed"""
        response = rest_api.post(f'{ROUTE_URL}/', json=_body())
        document = _stored(seeded, response.get_json())

        assert response.status_code == HTTPStatus.OK
        assert document['conditions'] == EMPTY_CONDITIONS
        assert document['selected_fields'] == [PLAIN_FIELD]

    def test_the_body_is_judged_by_the_same_rules(self, rest_api) -> None:
        """A typed value is no more trusted than a parsed one"""
        response = rest_api.post(f'{ROUTE_URL}/', json=_body(conditions=[1, 2]))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_a_body_that_is_not_an_object_is_refused(self, rest_api) -> None:
        """It was meant as the payload, so reading the query string instead would answer the wrong 400"""
        response = rest_api.post(f'{ROUTE_URL}/', json=[1, 2])

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_the_body_wins_over_the_query_string(self, rest_api, seeded) -> None:
        """Key by key, because the body carries the value and the query string only its text"""
        response = rest_api.post(
            f'{ROUTE_URL}/',
            query_string=_query_params(name='from-the-query-string'),
            json=_body(name='from-the-body'),
        )

        assert _stored(seeded, response.get_json())['name'] == 'from-the-body'

    def test_the_query_string_fills_what_the_body_omits(self, rest_api, seeded) -> None:
        """Merged rather than chosen, so neither half can go missing"""
        response = rest_api.post(
            f'{ROUTE_URL}/',
            query_string=_query_params(),
            json={'name': 'from-the-body'},
        )

        assert response.status_code == HTTPStatus.OK
        assert _stored(seeded, response.get_json())['name'] == 'from-the-body'

    def test_an_update_may_be_sent_as_a_body(self, rest_api, seeded) -> None:
        """Both write routes read the payload the same way"""
        public_id = rest_api.post(f'{ROUTE_URL}/', json=_body()).get_json()

        response = rest_api.put(f'{ROUTE_URL}/{public_id}', json=_body(name='updated-by-body'))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert _stored(seeded, public_id)['name'] == 'updated-by-body'


# -------------------------------------------------------------------------------------------------------------------- #
#                                        THE FRONTEND'S OWN CALL, END TO END                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTheAngularCallShapeStillWorks:
    """`report.service.ts` sends the payload as a body AND as query parameters, for every write."""

    def test_create_update_and_run_the_way_the_app_calls_them(self, rest_api, seeded) -> None:
        """The whole feature, driven exactly as the report form drives it"""
        body = _body()

        created = rest_api.post(f'{ROUTE_URL}/', query_string=_as_query_string(body), json=body)

        assert created.status_code == HTTPStatus.OK
        public_id = created.get_json()

        edited = {**body, 'public_id': public_id, 'name': 'edited-report'}
        updated = rest_api.put(
            f'{ROUTE_URL}/{public_id}', query_string=_as_query_string(edited), json=edited,
        )

        assert updated.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)

        read_back = rest_api.get(f'{ROUTE_URL}/{public_id}')

        assert read_back.status_code == HTTPStatus.OK
        assert read_back.get_json()['name'] == 'edited-report'

        run = rest_api.get(f'{ROUTE_URL}/run/{public_id}')

        assert run.status_code == HTTPStatus.OK

        deleted = rest_api.delete(f'{ROUTE_URL}/{public_id}')

        assert deleted.status_code == HTTPStatus.OK
        assert seeded.count_documents({'public_id': public_id}) == 0

    def test_the_identity_still_comes_from_the_url(self, rest_api, seeded) -> None:
        """The app sends its own public_id in both places; the URL is what decides"""
        public_id = rest_api.post(f'{ROUTE_URL}/', json=_body()).get_json()
        edited = {**_body(), 'public_id': 4242, 'name': 'pinned'}

        rest_api.put(f'{ROUTE_URL}/{public_id}', query_string=_as_query_string(edited), json=edited)

        assert _stored(seeded, public_id)['name'] == 'pinned'
        assert seeded.count_documents({'public_id': 4242}) == 0
