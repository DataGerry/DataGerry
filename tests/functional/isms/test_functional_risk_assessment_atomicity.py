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
Functional tests: every RiskAssessment write path is all-or-nothing

MongoDB transactions need a replica set, which DataGerry does not run on, so the routes compensate: every write
is recorded in a WriteLedger and a failure part-way undoes the recorded writes. These tests break a write in the
middle of each path - create, update, duplicate - and assert the database is exactly as it was before the request,
or, when the undo itself cannot finish, that the 500 names what is left. The update's ownership refusal is asserted
to happen before ANY write, and the delete to remove the RiskAssessment before its assignments.
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.isms_manager.control_measure_assignment_manager import ControlMeasureAssignmentManager
from cmdb.manager.isms_manager.risk_assessment_manager import RiskAssessmentManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.isms_model import IsmsControlMeasure, IsmsControlMeasureAssignment, IsmsRiskAssessment
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import RISK_ASSESSMENT_UNDO_INCOMPLETE_MSG
from tests.functional.isms.test_functional_risk_assessment_route import (
    _ra_body,
    assignment_entry,
    purge_referenced_persons,
    seed_referenced_persons,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/isms/risk_assessments'

RA_ID: int = 99401
FOREIGN_RA_ID: int = 99402
CM_ID: int = 99410
# An assessment holds one measure once, so a write touching two assignments needs a second measure
CM_SECOND_ID: int = 99411
CMA_UPDATED_ID: int = 99422
CMA_DELETED_ID: int = 99423
CMA_FOREIGN_ID: int = 99424
TARGET_RISK_IDS: list[int] = [99431, 99432, 99433]

# Every assessment a test writes carries this, so the ones the route created (their ids are server-drawn) can be
# found - and purged - without knowing their ids
MARKER_KEY: str = 'additional_info'
MARKER: str = 'atomicity-test-marker'

ALL_CMA_IDS: list[int] = [CMA_UPDATED_ID, CMA_DELETED_ID, CMA_FOREIGN_ID]
ORIGINAL_PRIORITY: int = 1
CHANGED_PRIORITY: int = 3


@pytest.fixture(autouse=True)
def _isms_licensed(monkeypatch: pytest.MonkeyPatch):
    """Licenses the ISMS feature so the gated routes are reachable."""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.ISMS)


@pytest.fixture(name='collections', autouse=True)
def fixture_collections(database_manager: MongoDatabaseManager, database_name: str):
    """The three collections, a seeded ControlMeasure, and a purge of everything the tests write."""
    assessments = database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)
    assignments = database_manager.get_collection(IsmsControlMeasureAssignment.COLLECTION, database_name)
    measures = database_manager.get_collection(IsmsControlMeasure.COLLECTION, database_name)

    def _purge() -> None:
        marked: list[int] = [ra['public_id'] for ra in assessments.find({MARKER_KEY: MARKER})]
        assessments.delete_many({'$or': [{MARKER_KEY: MARKER}, {'public_id': {'$in': [RA_ID, FOREIGN_RA_ID]}}]})
        assignments.delete_many({'$or': [{'public_id': {'$in': ALL_CMA_IDS}},
                                         {'risk_assessment_id': {'$in': marked + [RA_ID, FOREIGN_RA_ID]}}]})
        measures.delete_many({'public_id': {'$in': [CM_ID, CM_SECOND_ID]}})
        purge_referenced_persons(database_manager, database_name)

    _purge()
    measures.insert_many([{'public_id': measure_id, 'title': 'CM', 'control_measure_type': 'CONTROL'}
                          for measure_id in (CM_ID, CM_SECOND_ID)])
    seed_referenced_persons(database_manager, database_name)
    yield assessments, assignments
    _purge()


def _body(public_id: int = RA_ID, **overrides: Any) -> dict[str, Any]:
    """A complete RiskAssessment body carrying the marker."""
    return _ra_body(public_id, **{MARKER_KEY: MARKER, **overrides})


def _cma(public_id: int, risk_assessment_id: int, control_measure_id: int = CM_ID) -> dict[str, Any]:
    """A stored ControlMeasureAssignment document."""
    return {'public_id': public_id, 'risk_assessment_id': risk_assessment_id, 'control_measure_id': control_measure_id,
            'priority': ORIGINAL_PRIORITY}


def _created_count(assignments: Any) -> int:
    """The assignments of RA_ID stored by the route - under ids the server picked, so none of the seeded ones"""
    return assignments.count_documents({'risk_assessment_id': RA_ID, 'public_id': {'$nin': ALL_CMA_IDS}})


def _raiser(error: Exception):
    """A replacement that always raises the given error."""
    def _raise(*_args: Any, **_kwargs: Any) -> None:
        raise error

    return _raise


def _without_id(document: dict[str, Any] | None) -> dict[str, Any] | None:
    """A stored document without its Mongo _id, for exact comparisons."""
    return None if document is None else {key: value for key, value in document.items() if key != '_id'}


def _store_first_then_fail(real_insert_many):
    """An insert_many_items that stores the batch's FIRST document and then fails - a partial batch."""
    def _partial(self, documents):
        real_insert_many(self, documents[:1])
        raise RuntimeError('the batch failed part-way')

    return _partial


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       CREATE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCreate:
    """POST /isms/risk_assessments/ - the assessment and its assignments, or nothing"""

    def test_a_failed_assignment_batch_leaves_nothing_behind(self, rest_api, monkeypatch, collections) -> None:
        """The assessment was stored and one assignment of the batch too; both are gone again."""
        assessments, assignments = collections
        monkeypatch.setattr(ControlMeasureAssignmentManager, 'insert_many_items',
                            _store_first_then_fail(ControlMeasureAssignmentManager.insert_many_items))

        response = rest_api.post(f'{ROUTE_URL}/', json=_body(control_measure_assignments=[
            assignment_entry(CM_ID), assignment_entry(CM_SECOND_ID),
        ]))

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert assessments.count_documents({MARKER_KEY: MARKER}) == 0
        assert assignments.count_documents({'control_measure_id': {'$in': [CM_ID, CM_SECOND_ID]}}) == 0

    def test_an_undo_that_cannot_finish_names_what_is_left(self, rest_api, monkeypatch, collections) -> None:
        """The one outcome that is neither: a 500 naming the assessment that could not be removed."""
        assessments, _ = collections
        monkeypatch.setattr(ControlMeasureAssignmentManager, 'insert_many_items',
                            _raiser(RuntimeError('the batch failed')))
        monkeypatch.setattr(RiskAssessmentManager, 'delete_many', _raiser(RuntimeError('cleanup failed')))

        response = rest_api.post(f'{ROUTE_URL}/', json=_body(control_measure_assignments=[assignment_entry(CM_ID)]))

        left = assessments.find_one({MARKER_KEY: MARKER})
        message: str = response.get_json()['message']

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert message.startswith(RISK_ASSESSMENT_UNDO_INCOMPLETE_MSG.split('{', maxsplit=1)[0])
        assert left is not None
        assert f"'public_id': {left['public_id']}" in message
        assert IsmsRiskAssessment.COLLECTION in message


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       UPDATE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestUpdate:
    """PUT /isms/risk_assessments/<id> - refused before any write, or applied fully, or undone"""

    @staticmethod
    def _seed(collections) -> dict[int, dict[str, Any]]:
        """The assessment with one assignment to update and one to delete; answers their stored snapshots."""
        assessments, assignments = collections
        assessments.insert_one(_body())
        assignments.insert_many([_cma(CMA_UPDATED_ID, RA_ID), _cma(CMA_DELETED_ID, RA_ID, CM_SECOND_ID)])

        return {cma['public_id']: _without_id(cma) for cma in assignments.find({'risk_assessment_id': RA_ID})}

    def test_an_ownership_refusal_happens_before_any_write(self, rest_api, collections) -> None:
        """
        It used to arrive after the created assignments were already stored - "refused" for a half-applied
        request. Now nothing is written.
        """
        _, assignments = collections
        self._seed(collections)
        assignments.insert_one(_cma(CMA_FOREIGN_ID, FOREIGN_RA_ID))

        response = rest_api.put(f'{ROUTE_URL}/{RA_ID}', json=_body(control_measure_assignments={
            'created': [assignment_entry(CM_SECOND_ID)],
            'updated': [assignment_entry(CM_ID, public_id=CMA_UPDATED_ID, priority=CHANGED_PRIORITY)],
            'deleted': [CMA_FOREIGN_ID],
        }))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _created_count(assignments) == 0
        assert assignments.find_one({'public_id': CMA_UPDATED_ID})['priority'] == ORIGINAL_PRIORITY

    def test_a_failed_assessment_write_undoes_every_assignment_change(self, rest_api, monkeypatch,
                                                                      collections) -> None:
        """The last write fails: the created assignment is gone, the updated one and the deleted one as before."""
        assessments, assignments = collections
        before: dict[int, dict[str, Any]] = self._seed(collections)
        stored_assessment = _without_id(assessments.find_one({'public_id': RA_ID}))
        monkeypatch.setattr(RiskAssessmentManager, 'update_item', _raiser(RuntimeError('the write failed')))

        response = rest_api.put(f'{ROUTE_URL}/{RA_ID}', json=_body(additional_info=MARKER, control_measure_assignments={
            'created': [assignment_entry(CM_SECOND_ID)],
            'updated': [assignment_entry(CM_ID, public_id=CMA_UPDATED_ID, priority=CHANGED_PRIORITY)],
            'deleted': [CMA_DELETED_ID],
        }))

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert _created_count(assignments) == 0
        assert _without_id(assignments.find_one({'public_id': CMA_UPDATED_ID})) == before[CMA_UPDATED_ID]
        assert _without_id(assignments.find_one({'public_id': CMA_DELETED_ID})) == before[CMA_DELETED_ID]
        assert _without_id(assessments.find_one({'public_id': RA_ID})) == stored_assessment

    def test_a_complete_update_applies_everything(self, rest_api, collections) -> None:
        """The ordinary case still works end to end: create, update and delete in one request."""
        _, assignments = collections
        self._seed(collections)

        response = rest_api.put(f'{ROUTE_URL}/{RA_ID}', json=_body(control_measure_assignments={
            'created': [assignment_entry(CM_SECOND_ID)],
            'updated': [assignment_entry(CM_ID, public_id=CMA_UPDATED_ID, priority=CHANGED_PRIORITY)],
            'deleted': [CMA_DELETED_ID],
        }))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert _created_count(assignments) == 1
        assert assignments.find_one({'public_id': CMA_UPDATED_ID})['priority'] == CHANGED_PRIORITY
        assert assignments.find_one({'public_id': CMA_DELETED_ID}) is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                                      DUPLICATE                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDuplicate:
    """POST /isms/risk_assessments/duplicate/risk/<ids> - every target, or none"""

    def test_a_failure_on_a_later_target_removes_every_duplicate(self, rest_api, monkeypatch, collections) -> None:
        """
        The first target is fully written and the second partly, when the second's assignments fail. It used to
        leave the first duplicate and a second one without assignments behind an error; now none survives.
        """
        assessments, assignments = collections
        assessments.insert_one(_body())
        assignments.insert_one(_cma(CMA_UPDATED_ID, RA_ID))
        real_insert_many = ControlMeasureAssignmentManager.insert_many_items
        calls: dict[str, int] = {'count': 0}

        def _fail_on_the_second_target(self, documents):
            calls['count'] += 1

            if calls['count'] == 2:
                return _store_first_then_fail(real_insert_many)(self, documents)

            return real_insert_many(self, documents)

        monkeypatch.setattr(ControlMeasureAssignmentManager, 'insert_many_items', _fail_on_the_second_target)
        target_ids: str = ','.join(str(target) for target in TARGET_RISK_IDS)

        response = rest_api.post(f'{ROUTE_URL}/duplicate/risk/{target_ids}?copy_cma=true', json=_body())

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert [ra['public_id'] for ra in assessments.find({MARKER_KEY: MARKER})] == [RA_ID]
        assert assignments.count_documents({'control_measure_id': CM_ID}) == 1


# -------------------------------------------------------------------------------------------------------------------- #
#                                                        DELETE                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDelete:
    """DELETE /isms/risk_assessments/<id> - the assessment first, then its assignments"""

    def test_a_failed_assessment_delete_keeps_its_assignments(self, rest_api, monkeypatch, collections) -> None:
        """The old order deleted the assignments first and left a surviving assessment without them."""
        assessments, assignments = collections
        assessments.insert_one(_body())
        assignments.insert_one(_cma(CMA_DELETED_ID, RA_ID))
        monkeypatch.setattr(RiskAssessmentManager, 'delete_item', _raiser(RuntimeError('the delete failed')))

        response = rest_api.delete(f'{ROUTE_URL}/{RA_ID}')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert assessments.find_one({'public_id': RA_ID}) is not None
        assert assignments.find_one({'public_id': CMA_DELETED_ID}) is not None

    def test_a_failure_between_the_two_leaves_orphans_not_a_stripped_assessment(
            self, rest_api, monkeypatch, collections) -> None:
        """The failure the new order accepts: assignments pointing at nothing, which readers treat as unassigned."""
        assessments, assignments = collections
        assessments.insert_one(_body())
        assignments.insert_one(_cma(CMA_DELETED_ID, RA_ID))
        monkeypatch.setattr(RiskAssessmentManager, 'delete_many_from_other_collection',
                            _raiser(RuntimeError('the cascade failed')))

        rest_api.delete(f'{ROUTE_URL}/{RA_ID}')

        assert assessments.find_one({'public_id': RA_ID}) is None
        assert assignments.find_one({'public_id': CMA_DELETED_ID}) is not None
