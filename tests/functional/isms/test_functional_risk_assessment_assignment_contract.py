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
Functional tests for the ControlMeasureAssignments a RiskAssessment write embeds, through the real REST app

``POST`` and ``PUT /isms/risk_assessments/`` hold every embedded entry to the schema of
``POST /isms/control_measure_assignments/``. Pinned:

  - a container or entry the schema refuses is a 400 and stores nothing - neither the assessment nor any
    assignment
  - a created entry's ``public_id`` and ``risk_assessment_id`` are not taken from the body, unknown keys are not
    stored
  - an updated entry without its integer ``public_id`` and a deleted entry that is no integer are refused
  - an assessment holds one ControlMeasure once - on create, and after an update's diff is applied; the
    standalone assignment routes keep the same rule
  - the payloads the frontend sends still pass
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.isms_model import IsmsControlMeasure, IsmsControlMeasureAssignment, IsmsRiskAssessment
from cmdb.models.isms_model.priority_enum import Priority
from cmdb.security.license.license_constants import LicenseFeature

from tests.functional.isms.test_functional_risk_assessment_route import (
    _ra_body,
    assignment_entry,
    purge_referenced_persons,
    seed_referenced_persons,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/isms/risk_assessments'
CMA_URL: str = '/isms/control_measure_assignments'

RA_ID: int = 98901
FOREIGN_RA_ID: int = 98902
MEASURE_ID: int = 98911
SECOND_MEASURE_ID: int = 98912
STORED_CMA_ID: int = 98921
SECOND_STORED_CMA_ID: int = 98922
CLIENT_CMA_ID: int = 98929
ALL_MEASURE_IDS: list[int] = [MEASURE_ID, SECOND_MEASURE_ID]
ALL_RA_IDS: list[int] = [RA_ID, FOREIGN_RA_ID]

MARKER_KEY: str = 'additional_info'
MARKER: str = 'assignment-contract-marker'
UNKNOWN_KEY: str = 'not_a_field'
UNKNOWN_PRIORITY: int = max(priority.value for priority in Priority) + 1
ORIGINAL_PRIORITY: int = Priority.LOW.value
CHANGED_PRIORITY: int = Priority.HIGH.value


@pytest.fixture(autouse=True)
def _isms_licensed(monkeypatch: pytest.MonkeyPatch):
    """Licenses the ISMS feature so the gated routes are reachable"""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.ISMS)


@pytest.fixture(name='collections', autouse=True)
def fixture_collections(database_manager: MongoDatabaseManager, database_name: str):
    """Two ControlMeasures, the referenced persons, and a purge of everything the tests write"""
    assessments = database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)
    assignments = database_manager.get_collection(IsmsControlMeasureAssignment.COLLECTION, database_name)
    measures = database_manager.get_collection(IsmsControlMeasure.COLLECTION, database_name)

    def _purge() -> None:
        assessments.delete_many({'$or': [{MARKER_KEY: MARKER}, {'public_id': {'$in': ALL_RA_IDS}}]})
        assignments.delete_many({'control_measure_id': {'$in': ALL_MEASURE_IDS}})
        measures.delete_many({'public_id': {'$in': ALL_MEASURE_IDS}})
        purge_referenced_persons(database_manager, database_name)

    _purge()
    measures.insert_many([{'public_id': measure_id, 'title': 'CM', 'control_measure_type': 'CONTROL'}
                          for measure_id in ALL_MEASURE_IDS])
    seed_referenced_persons(database_manager, database_name)
    yield {'assessments': assessments, 'assignments': assignments}
    _purge()


def _body(**overrides: Any) -> dict[str, Any]:
    """A complete RiskAssessment body carrying the marker"""
    return _ra_body(RA_ID, **{MARKER_KEY: MARKER, **overrides})


def _entry(measure_id: int = MEASURE_ID, **overrides: Any) -> dict[str, Any]:
    """One embedded assignment of a test measure"""
    return assignment_entry(measure_id, **overrides)


def _stored_assignment(public_id: int, measure_id: int = MEASURE_ID, risk_assessment_id: int = RA_ID,
                       ) -> dict[str, Any]:
    """A stored assignment document"""
    return {**_entry(measure_id, priority=ORIGINAL_PRIORITY), 'public_id': public_id,
            'risk_assessment_id': risk_assessment_id}


def _seed_assessment(collections: dict[str, Any], *stored: dict[str, Any]) -> None:
    """The assessment RA_ID with the given stored assignments"""
    collections['assessments'].insert_one(_body())

    if stored:
        collections['assignments'].insert_many([dict(assignment) for assignment in stored])


def _assert_refused(response: Any, *fragments: str) -> None:
    """A 400 whose message names every fragment"""
    assert response.status_code == HTTPStatus.BAD_REQUEST, response.get_json()
    message: str = response.get_json()['message']
    assert all(fragment in message for fragment in fragments), message


def _without_id(document: dict[str, Any]) -> dict[str, Any]:
    """A stored document without its Mongo _id"""
    return {key: value for key, value in document.items() if key != '_id'}


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       CREATE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
CREATE_PROBES: list[Any] = [
    pytest.param({'created': [assignment_entry(MEASURE_ID)]}, 'must be a list', id='diff-object'),
    # Neither a list nor an object: the assessment schema's own anyof refuses it first
    pytest.param('not-a-list', 'control_measure_assignments', id='string'),
    pytest.param([5], 'created #1', id='entry-no-object'),
    pytest.param([assignment_entry(None)], 'control_measure_id', id='measure-null'),
    pytest.param([assignment_entry([MEASURE_ID])], 'control_measure_id', id='measure-list'),
    pytest.param([assignment_entry(MEASURE_ID, priority=UNKNOWN_PRIORITY)], 'priority', id='priority-unknown'),
    pytest.param([assignment_entry(MEASURE_ID, responsible_for_implementation_id_ref_type='NOBODY')],
                 'responsible_for_implementation_id_ref_type', id='ref-type-unknown'),
    pytest.param([{'control_measure_id': MEASURE_ID}], 'implementation_status', id='required-missing'),
]


class TestCreate:
    """POST /isms/risk_assessments/"""

    @pytest.mark.parametrize('assignments, fragment', CREATE_PROBES)
    def test_a_payload_the_schema_refuses_stores_nothing(self, rest_api, collections, assignments: Any,
                                                         fragment: str) -> None:
        """A 400 naming what is wrong, and neither the assessment nor an assignment stored"""
        _assert_refused(rest_api.post(f'{ROUTE_URL}/', json=_body(control_measure_assignments=assignments)), fragment)
        assert collections['assessments'].count_documents({MARKER_KEY: MARKER}) == 0
        assert collections['assignments'].count_documents({'control_measure_id': {'$in': ALL_MEASURE_IDS}}) == 0

    def test_the_frontend_payload_is_stored_with_server_owned_ids(self, rest_api, collections) -> None:
        """A sent public_id and risk_assessment_id are not taken, an unknown key is not stored"""
        entry: dict[str, Any] = _entry()
        sent: dict[str, Any] = {**entry, 'public_id': CLIENT_CMA_ID, 'risk_assessment_id': FOREIGN_RA_ID,
                                UNKNOWN_KEY: 'x'}

        response = rest_api.post(f'{ROUTE_URL}/', json=_body(control_measure_assignments=[sent]))

        assert response.status_code == HTTPStatus.CREATED, response.get_json()
        created_id: int = response.get_json()['result_id']
        stored: dict[str, Any] = collections['assignments'].find_one({'control_measure_id': MEASURE_ID})
        assert stored['public_id'] != CLIENT_CMA_ID
        assert stored['risk_assessment_id'] == created_id
        assert UNKNOWN_KEY not in stored
        assert {key: stored[key] for key in entry} == entry

    def test_one_measure_twice_is_refused(self, rest_api, collections) -> None:
        """Named, and nothing stored"""
        response = rest_api.post(f'{ROUTE_URL}/', json=_body(control_measure_assignments=[
            _entry(), _entry(SECOND_MEASURE_ID), _entry(),
        ]))

        _assert_refused(response, f'[{MEASURE_ID}]')
        assert collections['assessments'].count_documents({MARKER_KEY: MARKER}) == 0

    def test_two_measures_are_stored(self, rest_api, collections) -> None:
        """The ordinary case"""
        response = rest_api.post(f'{ROUTE_URL}/', json=_body(control_measure_assignments=[
            _entry(), _entry(SECOND_MEASURE_ID),
        ]))

        assert response.status_code == HTTPStatus.CREATED
        assert collections['assignments'].count_documents({
            'risk_assessment_id': response.get_json()['result_id'],
        }) == 2


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       UPDATE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
UPDATE_PROBES: list[Any] = [
    pytest.param([assignment_entry(MEASURE_ID)], 'must be an object', id='a-list'),
    pytest.param({'removed': [STORED_CMA_ID]}, 'must be an object', id='unknown-key'),
    pytest.param({'created': assignment_entry(MEASURE_ID)}, 'must be an object', id='created-no-list'),
    pytest.param({'created': [assignment_entry(MEASURE_ID, priority=UNKNOWN_PRIORITY)]}, 'created #1',
                 id='created-invalid'),
    pytest.param({'updated': [assignment_entry(MEASURE_ID)]}, 'updated #1', id='updated-without-id'),
    pytest.param({'updated': [assignment_entry(MEASURE_ID, public_id=str(STORED_CMA_ID))]}, 'updated #1',
                 id='updated-id-str'),
    pytest.param({'updated': [assignment_entry(MEASURE_ID, public_id=STORED_CMA_ID, priority=UNKNOWN_PRIORITY)]},
                 'priority', id='updated-invalid'),
    pytest.param({'deleted': [str(STORED_CMA_ID)]}, 'deleted #1', id='deleted-id-str'),
]


class TestUpdate:
    """PUT /isms/risk_assessments/<id>"""

    @pytest.mark.parametrize('diff, fragment', UPDATE_PROBES)
    def test_a_diff_the_schema_refuses_changes_nothing(self, rest_api, collections, diff: Any,
                                                       fragment: str) -> None:
        """A 400 naming what is wrong; the stored assessment and its assignment as before"""
        _seed_assessment(collections, _stored_assignment(STORED_CMA_ID))
        before: dict[str, Any] = _without_id(collections['assignments'].find_one({'public_id': STORED_CMA_ID}))

        response = rest_api.put(f'{ROUTE_URL}/{RA_ID}', json=_body(control_measure_assignments=diff))

        _assert_refused(response, fragment)
        assert _without_id(collections['assignments'].find_one({'public_id': STORED_CMA_ID})) == before
        assert collections['assignments'].count_documents({'risk_assessment_id': RA_ID}) == 1

    def test_the_frontend_diff_is_applied(self, rest_api, collections) -> None:
        """Create, update and delete in one request; the updated entry is stored as validated"""
        _seed_assessment(collections, _stored_assignment(STORED_CMA_ID),
                         _stored_assignment(SECOND_STORED_CMA_ID, SECOND_MEASURE_ID))

        response = rest_api.put(f'{ROUTE_URL}/{RA_ID}', json=_body(control_measure_assignments={
            'created': [_entry(SECOND_MEASURE_ID, public_id=None)],
            'updated': [_entry(public_id=STORED_CMA_ID, priority=CHANGED_PRIORITY,
                               risk_assessment_id=FOREIGN_RA_ID, **{UNKNOWN_KEY: 'x'})],
            'deleted': [SECOND_STORED_CMA_ID],
        }))

        assert response.status_code == HTTPStatus.ACCEPTED, response.get_json()
        updated: dict[str, Any] = collections['assignments'].find_one({'public_id': STORED_CMA_ID})
        assert updated['priority'] == CHANGED_PRIORITY
        assert updated['risk_assessment_id'] == RA_ID
        assert UNKNOWN_KEY not in updated
        assert collections['assignments'].find_one({'public_id': SECOND_STORED_CMA_ID}) is None
        created: dict[str, Any] = collections['assignments'].find_one({'control_measure_id': SECOND_MEASURE_ID})
        assert created['risk_assessment_id'] == RA_ID

    def test_a_created_entry_repeating_a_kept_measure_is_refused(self, rest_api, collections) -> None:
        """Judged on what the assessment holds after the diff: the stored one stays, so the new one repeats it"""
        _seed_assessment(collections, _stored_assignment(STORED_CMA_ID))

        response = rest_api.put(f'{ROUTE_URL}/{RA_ID}', json=_body(control_measure_assignments={
            'created': [_entry()],
        }))

        _assert_refused(response, f'[{MEASURE_ID}]')
        assert collections['assignments'].count_documents({'risk_assessment_id': RA_ID}) == 1

    def test_an_update_moving_onto_a_kept_measure_is_refused(self, rest_api, collections) -> None:
        """An updated entry taking the measure another stored assignment keeps"""
        _seed_assessment(collections, _stored_assignment(STORED_CMA_ID),
                         _stored_assignment(SECOND_STORED_CMA_ID, SECOND_MEASURE_ID))

        response = rest_api.put(f'{ROUTE_URL}/{RA_ID}', json=_body(control_measure_assignments={
            'updated': [_entry(public_id=SECOND_STORED_CMA_ID)],
        }))

        _assert_refused(response, f'[{MEASURE_ID}]')
        assert collections['assignments'].find_one({'public_id': SECOND_STORED_CMA_ID})['control_measure_id'] \
            == SECOND_MEASURE_ID

    def test_replacing_a_deleted_measure_is_legal(self, rest_api, collections) -> None:
        """The deleted one is gone after the diff, so its measure is free again"""
        _seed_assessment(collections, _stored_assignment(STORED_CMA_ID))

        response = rest_api.put(f'{ROUTE_URL}/{RA_ID}', json=_body(control_measure_assignments={
            'created': [_entry()], 'deleted': [STORED_CMA_ID],
        }))

        assert response.status_code == HTTPStatus.ACCEPTED, response.get_json()
        assert collections['assignments'].count_documents({'risk_assessment_id': RA_ID}) == 1
        assert collections['assignments'].find_one({'public_id': STORED_CMA_ID}) is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 STANDALONE ROUTES                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestStandaloneRoutes:
    """POST / PUT /isms/control_measure_assignments/ keep the same one-measure-once rule"""

    def test_a_second_assignment_of_a_held_measure_is_refused(self, rest_api, collections) -> None:
        """The assessment already holds the measure"""
        _seed_assessment(collections, _stored_assignment(STORED_CMA_ID))

        response = rest_api.post(f'{CMA_URL}/', json={**_entry(), 'risk_assessment_id': RA_ID})

        _assert_refused(response, f'ID:{MEASURE_ID}', f'ID:{RA_ID}')
        assert collections['assignments'].count_documents({'risk_assessment_id': RA_ID}) == 1

    def test_the_same_measure_on_another_assessment_is_legal(self, rest_api, collections) -> None:
        """The rule is per assessment"""
        _seed_assessment(collections, _stored_assignment(STORED_CMA_ID))
        collections['assessments'].insert_one(_ra_body(FOREIGN_RA_ID))

        response = rest_api.post(f'{CMA_URL}/', json={**_entry(), 'risk_assessment_id': FOREIGN_RA_ID})

        assert response.status_code == HTTPStatus.CREATED, response.get_json()

    def test_an_update_of_the_holder_itself_is_legal(self, rest_api, collections) -> None:
        """The updated assignment does not count against itself"""
        _seed_assessment(collections, _stored_assignment(STORED_CMA_ID))

        response = rest_api.put(f'{CMA_URL}/{STORED_CMA_ID}', json={
            **_entry(priority=CHANGED_PRIORITY), 'risk_assessment_id': RA_ID,
        })

        assert response.status_code == HTTPStatus.ACCEPTED, response.get_json()
        assert collections['assignments'].find_one({'public_id': STORED_CMA_ID})['priority'] == CHANGED_PRIORITY

    def test_an_update_onto_a_measure_another_holds_is_refused(self, rest_api, collections) -> None:
        """Moving one assignment onto the other's measure"""
        _seed_assessment(collections, _stored_assignment(STORED_CMA_ID),
                         _stored_assignment(SECOND_STORED_CMA_ID, SECOND_MEASURE_ID))

        response = rest_api.put(f'{CMA_URL}/{SECOND_STORED_CMA_ID}', json={**_entry(), 'risk_assessment_id': RA_ID})

        _assert_refused(response, f'ID:{MEASURE_ID}')
        assert collections['assignments'].find_one({'public_id': SECOND_STORED_CMA_ID})['control_measure_id'] \
            == SECOND_MEASURE_ID

    def test_an_unknown_priority_is_refused(self, rest_api, collections) -> None:
        """The pinned priority holds on the standalone route too"""
        _seed_assessment(collections)

        response = rest_api.post(f'{CMA_URL}/', json={
            **_entry(priority=UNKNOWN_PRIORITY), 'risk_assessment_id': RA_ID,
        })

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert collections['assignments'].count_documents({'risk_assessment_id': RA_ID}) == 0
