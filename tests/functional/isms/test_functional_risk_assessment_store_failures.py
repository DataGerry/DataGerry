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
Functional tests for a failed database call while a RiskAssessment's ControlMeasureAssignments are written or checked

`workflows/isms.md`: a bug is a 500, a failed database call a 400. Measured before: every one of these answered the
generic 500 - an assignment insert, update or delete of an update's diff (the ledger already undid the writes), the
read of the assessment's own assignments, and the read checking the named ControlMeasures exist, which four routes
share. Each failure is raised where the database layer raises it (the base manager call), so the manager's own
wrapping runs as in production; the stored data is compared exactly, so "undone" and "never written" are pinned too.

The seed is the atomicity tests', reused by their fixtures
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.errors.manager import (
    BaseManagerDeleteError,
    BaseManagerGetError,
    BaseManagerInsertError,
    BaseManagerUpdateError,
)
from cmdb.manager.isms_manager.control_measure_assignment_manager import ControlMeasureAssignmentManager
from cmdb.manager.isms_manager.risk_assessment_manager import RiskAssessmentManager
from cmdb.models.isms_model import IsmsControlMeasureAssignment
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import (
    CONTROL_MEASURE_ASSIGNMENT_LABEL,
    CONTROL_MEASURE_LOOKUP_FAILED_MSG,
    OWNED_ASSIGNMENTS_READ_MSG,
    IsmsManagerErrorMessage,
)
from tests.functional.isms.test_functional_risk_assessment_atomicity import (  # pylint: disable=unused-import
    CHANGED_PRIORITY,
    CM_ID,
    CM_SECOND_ID,
    CMA_DELETED_ID,
    CMA_UPDATED_ID,
    RA_ID,
    ROUTE_URL,
    TestUpdate,
    _body,
    _created_count,
    _isms_licensed,
    _without_id,
    assignment_entry,
    fixture_collections,
)
# -------------------------------------------------------------------------------------------------------------------- #

ASSIGNMENT_ROUTE_URL: str = '/isms/control_measure_assignments'

# The base call each assignment write wraps, and the error the database layer raises from it
WRITE_FAILURES: dict[str, tuple[str, Exception, IsmsManagerErrorMessage]] = {
    'insert': ('insert', BaseManagerInsertError('insert failed'), IsmsManagerErrorMessage.ASSIGNMENT_INSERT_UNDONE),
    'update': ('update', BaseManagerUpdateError('update failed'), IsmsManagerErrorMessage.ASSIGNMENT_UPDATE_UNDONE),
    'delete': ('delete', BaseManagerDeleteError('delete failed'), IsmsManagerErrorMessage.ASSIGNMENT_DELETE_UNDONE),
}


def _raiser(error: Exception):
    """A replacement that always raises the given error."""
    def _raise(*_args: Any, **_kwargs: Any) -> None:
        raise error

    return _raise


def _diff() -> dict[str, list[Any]]:
    """An update's assignment diff touching every write kind: one created, one updated, one deleted."""
    return {
        'created': [assignment_entry(CM_SECOND_ID)],
        'updated': [assignment_entry(CM_ID, public_id=CMA_UPDATED_ID, priority=CHANGED_PRIORITY)],
        'deleted': [CMA_DELETED_ID],
    }


def _message(template: IsmsManagerErrorMessage) -> str:
    """The assignment template as the update route answers it - the RiskAssessment's id filled in."""
    return template.value.format(entity=CONTROL_MEASURE_ASSIGNMENT_LABEL.singular, public_id=RA_ID)


def _fail_assignment_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    """The RiskAssessment manager's read of the assignment collection fails; every other read of it works."""
    real_read = RiskAssessmentManager.get_many_from_other_collection

    def _read(self, collection: str, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        if collection == IsmsControlMeasureAssignment.COLLECTION:
            raise BaseManagerGetError('assignment read failed')

        return real_read(self, collection, *args, **kwargs)

    monkeypatch.setattr(RiskAssessmentManager, 'get_many_from_other_collection', _read)


def _fail_measure_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ControlMeasure existence read fails."""
    monkeypatch.setattr(
        ControlMeasureAssignmentManager, 'get_many_from_other_collection', _raiser(BaseManagerGetError('lookup')),
    )


class TestTheAssignmentDiffOfAnUpdate:
    """PUT /isms/risk_assessments/<id>: each failed write a 400 naming the RiskAssessment, everything undone"""

    @pytest.mark.parametrize('kind', list(WRITE_FAILURES))
    def test_a_failed_write_is_a_400_and_undone(self, rest_api, monkeypatch, collections, kind: str) -> None:
        """Before: 500. The created assignment is gone, the updated and the deleted one as stored, the RA unchanged"""
        assessments, assignments = collections
        before: dict[int, dict[str, Any]] = TestUpdate._seed(collections)  # pylint: disable=protected-access
        stored_assessment = _without_id(assessments.find_one({'public_id': RA_ID}))
        method, error, template = WRITE_FAILURES[kind]
        monkeypatch.setattr(ControlMeasureAssignmentManager, method, _raiser(error))

        response = rest_api.put(f'{ROUTE_URL}/{RA_ID}', json=_body(additional_info='changed',
                                                                  control_measure_assignments=_diff()))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == _message(template)
        assert _created_count(assignments) == 0
        assert _without_id(assignments.find_one({'public_id': CMA_UPDATED_ID})) == before[CMA_UPDATED_ID]
        assert _without_id(assignments.find_one({'public_id': CMA_DELETED_ID})) == before[CMA_DELETED_ID]
        assert _without_id(assessments.find_one({'public_id': RA_ID})) == stored_assessment

    def test_a_failed_read_of_its_own_assignments_is_a_400_before_any_write(
            self, rest_api, monkeypatch, collections) -> None:
        """Before: 500. Nothing was written - the read is the ownership rule's input"""
        assessments, assignments = collections
        before: dict[int, dict[str, Any]] = TestUpdate._seed(collections)  # pylint: disable=protected-access
        stored_assessment = _without_id(assessments.find_one({'public_id': RA_ID}))
        _fail_assignment_reads(monkeypatch)

        response = rest_api.put(f'{ROUTE_URL}/{RA_ID}', json=_body(control_measure_assignments=_diff()))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == OWNED_ASSIGNMENTS_READ_MSG.format(public_id=RA_ID)
        assert _created_count(assignments) == 0
        assert _without_id(assignments.find_one({'public_id': CMA_UPDATED_ID})) == before[CMA_UPDATED_ID]
        assert _without_id(assessments.find_one({'public_id': RA_ID})) == stored_assessment

    def test_without_a_diff_the_assignments_are_not_read(self, rest_api, monkeypatch, collections) -> None:
        """An update that changes no assignment does not depend on that read at all"""
        TestUpdate._seed(collections)  # pylint: disable=protected-access
        _fail_assignment_reads(monkeypatch)

        response = rest_api.put(f'{ROUTE_URL}/{RA_ID}', json=_body(additional_info='changed'))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)


class TestTheControlMeasureLookup:
    """The existence read four routes share: a 400 of its own, before anything is written"""

    def test_a_risk_assessment_create(self, rest_api, monkeypatch, collections) -> None:
        """Before: 500"""
        assessments, _assignments = collections
        _fail_measure_lookup(monkeypatch)

        response = rest_api.post(f'{ROUTE_URL}/', json=_body(control_measure_assignments=[assignment_entry(CM_ID)]))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == CONTROL_MEASURE_LOOKUP_FAILED_MSG
        assert assessments.find_one({'public_id': RA_ID}) is None

    def test_a_risk_assessment_update(self, rest_api, monkeypatch, collections) -> None:
        """Before: 500"""
        _assessments, assignments = collections
        TestUpdate._seed(collections)  # pylint: disable=protected-access
        _fail_measure_lookup(monkeypatch)

        response = rest_api.put(f'{ROUTE_URL}/{RA_ID}', json=_body(control_measure_assignments=_diff()))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == CONTROL_MEASURE_LOOKUP_FAILED_MSG
        assert _created_count(assignments) == 0

    def test_an_assignment_create(self, rest_api, monkeypatch, collections) -> None:
        """Before: 500"""
        assessments, assignments = collections
        assessments.insert_one(_body())
        _fail_measure_lookup(monkeypatch)

        response = rest_api.post(f'{ASSIGNMENT_ROUTE_URL}/',
                                 json={**assignment_entry(CM_ID), 'risk_assessment_id': RA_ID})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == CONTROL_MEASURE_LOOKUP_FAILED_MSG
        assert _created_count(assignments) == 0

    def test_an_assignment_update(self, rest_api, monkeypatch, collections) -> None:
        """Not measured before - the same helper - pinned now"""
        _assessments, assignments = collections
        before: dict[int, dict[str, Any]] = TestUpdate._seed(collections)  # pylint: disable=protected-access
        _fail_measure_lookup(monkeypatch)

        response = rest_api.put(
            f'{ASSIGNMENT_ROUTE_URL}/{CMA_UPDATED_ID}',
            json={**assignment_entry(CM_ID, priority=CHANGED_PRIORITY), 'risk_assessment_id': RA_ID},
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == CONTROL_MEASURE_LOOKUP_FAILED_MSG
        assert _without_id(assignments.find_one({'public_id': CMA_UPDATED_ID})) == before[CMA_UPDATED_ID]
