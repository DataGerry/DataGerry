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
Functional tests for the person references of the ISMS write routes

Every write of an IsmsRiskAssessment (create, update, duplicate) and of an IsmsControlMeasureAssignment (create,
update) resolves its person references before anything is written:

  - an id has to exist in the collection its ``_ref_type`` names - a group's id sent as a PERSON is refused, the
    pair the delete cascade would otherwise never clean
  - an update judges only the references it introduces, so a document carrying a reference that went stale can
    still be saved, and a changed reference cannot be stale
  - an assignment also has to name an existing ControlMeasure and RiskAssessment, on create and on update
  - a refused write stores nothing

The routes are ISMS-license gated, so the check is stubbed.
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import PersonsManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.manager.person_reference_helper import ref_type_key
from cmdb.models.isms_model import IsmsControlMeasure, IsmsControlMeasureAssignment, IsmsRiskAssessment
from cmdb.models.isms_model.isms_control_measure_assignment_constants import ControlMeasureAssignmentKey
from cmdb.models.isms_model.isms_risk_assessment_constants import RiskAssessmentKey
from cmdb.models.person_group_model.person_reference_type_enum import PersonReferenceType
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.errors.manager.persons_manager import PersonsManagerGetError
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import REFERENCE_LOOKUP_FAILED_MSG
from cmdb.interface.rest_api.routes.user_management_routes.person_constants import PERSON_GROUP_LABEL, PERSON_LABEL

from tests.functional.isms.test_functional_risk_assessment_route import (
    PERSON_GROUP_ID,
    PERSON_ID,
    _ra_body,
    purge_referenced_persons,
    seed_referenced_persons,
)
# -------------------------------------------------------------------------------------------------------------------- #

RA_URL: str = '/isms/risk_assessments'
CMA_URL: str = '/isms/control_measure_assignments'

STORED_RA_ID: int = 97301
CMA_ID: int = 97310
STORED_CMA_ID: int = 97311
CONTROL_MEASURE_ID: int = 97320
UNKNOWN_CONTROL_MEASURE_ID: int = 97321
UNKNOWN_RA_ID: int = 97330
RISK_ID: int = 97340
UNKNOWN_PERSON_ID: int = 97399

# Every document a test writes through a route carries it, so a refused write can be shown to have stored nothing
MARKER_KEY: str = RiskAssessmentKey.ADDITIONAL_INFO.value
MARKER: str = 'person-reference-test-marker'

PERSON: str = PersonReferenceType.PERSON.value
PERSON_GROUP: str = PersonReferenceType.PERSON_GROUP.value

OWNER_KEY: str = RiskAssessmentKey.RISK_OWNER_ID.value
RESPONSIBLE_KEY: str = RiskAssessmentKey.RESPONSIBLE_PERSONS_ID.value
AUDITOR_KEY: str = RiskAssessmentKey.AUDITOR_ID.value
ASSESSOR_KEY: str = RiskAssessmentKey.RISK_ASSESSOR_ID.value
INTERVIEWED_KEY: str = RiskAssessmentKey.INTERVIEWED_PERSONS.value
IMPLEMENTER_KEY: str = ControlMeasureAssignmentKey.RESPONSIBLE_FOR_IMPLEMENTATION_ID.value
PRIORITY_KEY: str = ControlMeasureAssignmentKey.PRIORITY.value
ASSIGNMENTS_KEY: str = 'control_measure_assignments'

ORIGINAL_PRIORITY: int = 1
CHANGED_PRIORITY: int = 3


@pytest.fixture(autouse=True)
def _isms_licensed(monkeypatch: pytest.MonkeyPatch):
    """Licenses the ISMS feature so the gated routes are reachable"""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.ISMS)


@pytest.fixture(name='collections', autouse=True)
def fixture_collections(database_manager: MongoDatabaseManager, database_name: str):
    """The two ISMS collections, the referenced person / group / measure seeded, everything purged after"""
    assessments = database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)
    assignments = database_manager.get_collection(IsmsControlMeasureAssignment.COLLECTION, database_name)
    measures = database_manager.get_collection(IsmsControlMeasure.COLLECTION, database_name)

    def _purge() -> None:
        assessments.delete_many({'$or': [{MARKER_KEY: MARKER}, {'public_id': STORED_RA_ID}]})
        assignments.delete_many({'public_id': {'$in': [CMA_ID, STORED_CMA_ID]}})
        assignments.delete_many({ControlMeasureAssignmentKey.RISK_ASSESSMENT_ID.value: STORED_RA_ID})
        measures.delete_many({'public_id': CONTROL_MEASURE_ID})
        purge_referenced_persons(database_manager, database_name)

    _purge()
    measures.insert_one({'public_id': CONTROL_MEASURE_ID, 'title': 'CM', 'control_measure_type': 'CONTROL'})
    seed_referenced_persons(database_manager, database_name)
    yield assessments, assignments
    _purge()


def _body(**overrides: Any) -> dict[str, Any]:
    """A complete RiskAssessment body carrying the marker"""
    return _ra_body(STORED_RA_ID, **{MARKER_KEY: MARKER, 'risk_id': RISK_ID, **overrides})


def _assignment(public_id: int = CMA_ID, **overrides: Any) -> dict[str, Any]:
    """A complete ControlMeasureAssignment body linked to the stored assessment"""
    body: dict[str, Any] = {
        'public_id': public_id,
        'control_measure_id': CONTROL_MEASURE_ID,
        'risk_assessment_id': STORED_RA_ID,
        'planned_implementation_date': None,
        'implementation_status': 1,
        'finished_implementation_date': None,
        PRIORITY_KEY: ORIGINAL_PRIORITY,
        ref_type_key(IMPLEMENTER_KEY): PERSON,
        IMPLEMENTER_KEY: PERSON_ID,
    }
    body.update(overrides)

    return body


def _marked(assessments: Any) -> int:
    """How many assessments a route stored for this module"""
    return assessments.count_documents({MARKER_KEY: MARKER, 'public_id': {'$ne': STORED_RA_ID}})


def _store_assessment(assessments: Any, **overrides: Any) -> None:
    """Stores the assessment the update tests change, bypassing the routes"""
    assessments.insert_one(_body(**overrides))


def _assert_refused(response: Any, *fragments: str) -> None:
    """A 400 whose message names every fragment"""
    assert response.status_code == HTTPStatus.BAD_REQUEST, response.get_json()

    message: str = response.get_json()['message']

    for fragment in fragments:
        assert fragment in message, message


class TestRiskAssessmentCreate:
    """POST /isms/risk_assessments/ resolves every person reference"""

    def test_resolving_references_are_accepted(self, rest_api, collections) -> None:
        """A person in a person slot, a group in a group slot, persons in the person-only keys"""
        response = rest_api.post(f'{RA_URL}/', json=_body(**{
            RESPONSIBLE_KEY: PERSON_GROUP_ID, ref_type_key(RESPONSIBLE_KEY): PERSON_GROUP,
            ASSESSOR_KEY: PERSON_ID, INTERVIEWED_KEY: [PERSON_ID],
        }))

        assert response.status_code == HTTPStatus.CREATED
        assert _marked(collections[0]) == 1

    @pytest.mark.parametrize('key', [OWNER_KEY, RESPONSIBLE_KEY, AUDITOR_KEY])
    def test_an_unknown_person_in_a_polymorphic_key_is_refused(self, rest_api, collections, key: str) -> None:
        """Each of the three polymorphic keys is checked"""
        response = rest_api.post(f'{RA_URL}/', json=_body(**{key: UNKNOWN_PERSON_ID, ref_type_key(key): PERSON}))

        _assert_refused(response, PERSON_LABEL, str(UNKNOWN_PERSON_ID))
        assert _marked(collections[0]) == 0

    def test_an_unknown_group_is_refused(self, rest_api, collections) -> None:
        """The group half of a polymorphic key"""
        response = rest_api.post(f'{RA_URL}/', json=_body(**{
            RESPONSIBLE_KEY: UNKNOWN_PERSON_ID, ref_type_key(RESPONSIBLE_KEY): PERSON_GROUP,
        }))

        _assert_refused(response, PERSON_GROUP_LABEL, str(UNKNOWN_PERSON_ID))
        assert _marked(collections[0]) == 0

    def test_a_group_id_sent_as_a_person_is_refused(self, rest_api, collections) -> None:
        """The group exists, but the ref_type says PERSON and no person holds that id"""
        response = rest_api.post(f'{RA_URL}/', json=_body(**{
            OWNER_KEY: PERSON_GROUP_ID, ref_type_key(OWNER_KEY): PERSON,
        }))

        _assert_refused(response, PERSON_LABEL, str(PERSON_GROUP_ID))
        assert _marked(collections[0]) == 0

    def test_a_person_id_sent_as_a_group_is_refused(self, rest_api, collections) -> None:
        """The other direction of the mismatch"""
        response = rest_api.post(f'{RA_URL}/', json=_body(**{
            RESPONSIBLE_KEY: PERSON_ID, ref_type_key(RESPONSIBLE_KEY): PERSON_GROUP,
        }))

        _assert_refused(response, PERSON_GROUP_LABEL, str(PERSON_ID))

    @pytest.mark.parametrize('key, value', [(ASSESSOR_KEY, UNKNOWN_PERSON_ID), (INTERVIEWED_KEY, [UNKNOWN_PERSON_ID])])
    def test_an_unknown_person_in_a_person_only_key_is_refused(self, rest_api, collections, key: str,
                                                               value: Any) -> None:
        """The assessor and the interviewed persons are always persons"""
        _assert_refused(rest_api.post(f'{RA_URL}/', json=_body(**{key: value})), str(UNKNOWN_PERSON_ID))
        assert _marked(collections[0]) == 0

    def test_a_group_id_among_the_interviewed_persons_is_refused(self, rest_api) -> None:
        """A person-only key cannot hold a group, whatever the id"""
        _assert_refused(rest_api.post(f'{RA_URL}/', json=_body(**{INTERVIEWED_KEY: [PERSON_ID, PERSON_GROUP_ID]})),
                        str(PERSON_GROUP_ID))

    def test_an_interviewed_entry_that_is_no_id_is_refused(self, rest_api, collections) -> None:
        """The schema refuses it before the reference check"""
        response = rest_api.post(f'{RA_URL}/', json=_body(**{INTERVIEWED_KEY: [PERSON_ID, 'x']}))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _marked(collections[0]) == 0

    def test_an_assignment_with_an_unknown_responsible_person_is_refused(self, rest_api, collections) -> None:
        """The embedded assignments are checked too, and nothing at all is stored"""
        response = rest_api.post(f'{RA_URL}/', json=_body(**{
            ASSIGNMENTS_KEY: [_assignment(**{IMPLEMENTER_KEY: UNKNOWN_PERSON_ID})],
        }))

        _assert_refused(response, PERSON_LABEL, str(UNKNOWN_PERSON_ID))
        assert _marked(collections[0]) == 0
        assert collections[1].count_documents({'public_id': CMA_ID}) == 0

    def test_an_assignment_with_an_unknown_ref_type_is_refused(self, rest_api, collections) -> None:
        """An embedded assignment is not schema-checked, so the reference check refuses the ref_type itself"""
        response = rest_api.post(f'{RA_URL}/', json=_body(**{
            ASSIGNMENTS_KEY: [_assignment(**{ref_type_key(IMPLEMENTER_KEY): 'NOBODY'})],
        }))

        _assert_refused(response, IMPLEMENTER_KEY, 'NOBODY')
        assert _marked(collections[0]) == 0

    def test_a_failed_lookup_is_a_400(self, rest_api, monkeypatch, collections) -> None:
        """A manager read failure of the ISMS routes answers 400, naming what could not be looked up"""
        def _fail(*_args: Any, **_kwargs: Any) -> None:
            raise PersonsManagerGetError('lookup failed')

        monkeypatch.setattr(PersonsManager, 'find_existing_public_ids', _fail)

        response = rest_api.post(f'{RA_URL}/', json=_body())

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == REFERENCE_LOOKUP_FAILED_MSG.format(label=PERSON_LABEL)
        assert _marked(collections[0]) == 0


class TestRiskAssessmentUpdate:
    """PUT /isms/risk_assessments/<id> judges the references it introduces"""

    def test_a_stale_stored_reference_does_not_block_a_save(self, rest_api, collections) -> None:
        """The auditor was deleted outside the cascade; the assessment can still be edited"""
        _store_assessment(collections[0], **{AUDITOR_KEY: UNKNOWN_PERSON_ID})

        response = rest_api.put(f'{RA_URL}/{STORED_RA_ID}', json=_body(**{
            AUDITOR_KEY: UNKNOWN_PERSON_ID, 'audit_result': 'edited',
        }))

        assert response.status_code == HTTPStatus.ACCEPTED
        assert collections[0].find_one({'public_id': STORED_RA_ID})['audit_result'] == 'edited'

    def test_a_changed_reference_is_checked(self, rest_api, collections) -> None:
        """A new auditor has to exist, and the refused update changes nothing"""
        _store_assessment(collections[0])

        response = rest_api.put(f'{RA_URL}/{STORED_RA_ID}', json=_body(**{AUDITOR_KEY: UNKNOWN_PERSON_ID}))

        _assert_refused(response, PERSON_LABEL, str(UNKNOWN_PERSON_ID))
        assert collections[0].find_one({'public_id': STORED_RA_ID})[AUDITOR_KEY] is None

    def test_a_changed_ref_type_is_checked(self, rest_api, collections) -> None:
        """Re-labelling a stored person as a group is a new reference"""
        _store_assessment(collections[0])

        response = rest_api.put(f'{RA_URL}/{STORED_RA_ID}', json=_body(**{ref_type_key(OWNER_KEY): PERSON_GROUP}))

        _assert_refused(response, PERSON_GROUP_LABEL, str(PERSON_ID))

    def test_a_created_assignment_is_checked(self, rest_api, collections) -> None:
        """An assignment created by the update names an existing person"""
        _store_assessment(collections[0])

        response = rest_api.put(f'{RA_URL}/{STORED_RA_ID}', json=_body(**{ASSIGNMENTS_KEY: {
            'created': [_assignment(**{IMPLEMENTER_KEY: UNKNOWN_PERSON_ID})], 'updated': [], 'deleted': [],
        }}))

        _assert_refused(response, str(UNKNOWN_PERSON_ID))
        assert collections[1].count_documents({'public_id': CMA_ID}) == 0

    def test_an_updated_assignment_keeps_its_stale_reference(self, rest_api, collections) -> None:
        """An updated assignment is judged against its stored self"""
        _store_assessment(collections[0])
        collections[1].insert_one(_assignment(STORED_CMA_ID, **{IMPLEMENTER_KEY: UNKNOWN_PERSON_ID}))

        response = rest_api.put(f'{RA_URL}/{STORED_RA_ID}', json=_body(**{ASSIGNMENTS_KEY: {
            'created': [],
            'updated': [_assignment(STORED_CMA_ID, **{IMPLEMENTER_KEY: UNKNOWN_PERSON_ID,
                                                      PRIORITY_KEY: CHANGED_PRIORITY})],
            'deleted': [],
        }}))

        assert response.status_code == HTTPStatus.ACCEPTED
        assert collections[1].find_one({'public_id': STORED_CMA_ID})[PRIORITY_KEY] == CHANGED_PRIORITY

    def test_an_updated_assignment_with_a_new_unknown_reference_is_refused(self, rest_api, collections) -> None:
        """Changing an assignment's responsible person to nobody is refused, and nothing is written"""
        _store_assessment(collections[0])
        collections[1].insert_one(_assignment(STORED_CMA_ID))

        response = rest_api.put(f'{RA_URL}/{STORED_RA_ID}', json=_body(**{ASSIGNMENTS_KEY: {
            'created': [],
            'updated': [_assignment(STORED_CMA_ID, **{IMPLEMENTER_KEY: UNKNOWN_PERSON_ID,
                                                      PRIORITY_KEY: CHANGED_PRIORITY})],
            'deleted': [],
        }}))

        _assert_refused(response, str(UNKNOWN_PERSON_ID))
        assert collections[1].find_one({'public_id': STORED_CMA_ID})[PRIORITY_KEY] == ORIGINAL_PRIORITY


class TestRiskAssessmentDuplicate:
    """POST /isms/risk_assessments/duplicate/... judges the source payload in full"""

    def test_an_unknown_reference_writes_no_duplicate(self, rest_api, collections) -> None:
        """Every duplicate would carry the reference, so none is written"""
        response = rest_api.post(f'{RA_URL}/duplicate/risk/{RISK_ID}?copy_cma=false',
                                 json=_body(**{AUDITOR_KEY: UNKNOWN_PERSON_ID}))

        _assert_refused(response, PERSON_LABEL, str(UNKNOWN_PERSON_ID))
        assert _marked(collections[0]) == 0

    def test_resolving_references_duplicate(self, rest_api, collections) -> None:
        """The check does not get in the way of a valid source"""
        response = rest_api.post(f'{RA_URL}/duplicate/risk/{RISK_ID}?copy_cma=false', json=_body())

        assert response.status_code == HTTPStatus.OK
        assert _marked(collections[0]) == 1


class TestAssignmentCreate:
    """POST /isms/control_measure_assignments/ resolves every reference"""

    @pytest.fixture(autouse=True)
    def _stored_assessment(self, collections) -> None:
        """The assessment the assignments link to"""
        _store_assessment(collections[0])

    def test_resolving_references_are_accepted(self, rest_api, collections) -> None:
        """A group as the responsible party"""
        response = rest_api.post(f'{CMA_URL}/', json=_assignment(**{
            IMPLEMENTER_KEY: PERSON_GROUP_ID, ref_type_key(IMPLEMENTER_KEY): PERSON_GROUP,
        }))

        assert response.status_code == HTTPStatus.CREATED

    def test_an_unknown_responsible_person_is_refused(self, rest_api, collections) -> None:
        """Nothing is stored"""
        response = rest_api.post(f'{CMA_URL}/', json=_assignment(**{IMPLEMENTER_KEY: UNKNOWN_PERSON_ID}))

        _assert_refused(response, PERSON_LABEL, str(UNKNOWN_PERSON_ID))
        assert collections[1].count_documents({'public_id': CMA_ID}) == 0

    def test_a_group_id_sent_as_a_person_is_refused(self, rest_api) -> None:
        """The mismatch, on the assignment's key"""
        _assert_refused(rest_api.post(f'{CMA_URL}/', json=_assignment(**{IMPLEMENTER_KEY: PERSON_GROUP_ID})),
                        PERSON_LABEL, str(PERSON_GROUP_ID))

    def test_an_unknown_ref_type_is_refused(self, rest_api) -> None:
        """The schema restricts the ref_type to the PersonReferenceType values"""
        response = rest_api.post(f'{CMA_URL}/', json=_assignment(**{ref_type_key(IMPLEMENTER_KEY): 'FOO'}))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_an_unknown_risk_assessment_is_refused(self, rest_api, collections) -> None:
        """An assignment must belong to an assessment that exists"""
        response = rest_api.post(f'{CMA_URL}/', json=_assignment(risk_assessment_id=UNKNOWN_RA_ID))

        _assert_refused(response, str(UNKNOWN_RA_ID))
        assert collections[1].count_documents({'public_id': CMA_ID}) == 0


class TestAssignmentUpdate:
    """PUT /isms/control_measure_assignments/<id> resolves its references"""

    @pytest.fixture(autouse=True)
    def _stored(self, collections) -> None:
        """The assessment and a stored assignment whose responsible person was deleted outside the cascade"""
        _store_assessment(collections[0])
        collections[1].insert_one(_assignment(STORED_CMA_ID, **{IMPLEMENTER_KEY: UNKNOWN_PERSON_ID}))

    def test_a_stale_stored_reference_does_not_block_a_save(self, rest_api, collections) -> None:
        """Only what the update introduces is judged"""
        response = rest_api.put(f'{CMA_URL}/{STORED_CMA_ID}', json=_assignment(
            STORED_CMA_ID, **{IMPLEMENTER_KEY: UNKNOWN_PERSON_ID, PRIORITY_KEY: CHANGED_PRIORITY},
        ))

        assert response.status_code == HTTPStatus.ACCEPTED
        assert collections[1].find_one({'public_id': STORED_CMA_ID})[PRIORITY_KEY] == CHANGED_PRIORITY

    def test_a_new_unknown_reference_is_refused(self, rest_api, collections) -> None:
        """Re-pointing it at a group that does not exist"""
        response = rest_api.put(f'{CMA_URL}/{STORED_CMA_ID}', json=_assignment(STORED_CMA_ID, **{
            IMPLEMENTER_KEY: UNKNOWN_PERSON_ID, ref_type_key(IMPLEMENTER_KEY): PERSON_GROUP,
        }))

        _assert_refused(response, PERSON_GROUP_LABEL, str(UNKNOWN_PERSON_ID))

    def test_an_unknown_control_measure_is_refused(self, rest_api, collections) -> None:
        """The update checks the measure exactly like the create, and writes nothing"""
        response = rest_api.put(f'{CMA_URL}/{STORED_CMA_ID}', json=_assignment(
            STORED_CMA_ID, control_measure_id=UNKNOWN_CONTROL_MEASURE_ID, **{IMPLEMENTER_KEY: UNKNOWN_PERSON_ID},
        ))

        _assert_refused(response, str(UNKNOWN_CONTROL_MEASURE_ID))
        assert collections[1].find_one({'public_id': STORED_CMA_ID})['control_measure_id'] == CONTROL_MEASURE_ID

    def test_an_unknown_risk_assessment_is_refused(self, rest_api, collections) -> None:
        """An update cannot move the assignment onto an assessment that does not exist"""
        response = rest_api.put(f'{CMA_URL}/{STORED_CMA_ID}', json=_assignment(
            STORED_CMA_ID, risk_assessment_id=UNKNOWN_RA_ID, **{IMPLEMENTER_KEY: UNKNOWN_PERSON_ID},
        ))

        _assert_refused(response, str(UNKNOWN_RA_ID))
        assert collections[1].find_one({'public_id': STORED_CMA_ID})['risk_assessment_id'] == STORED_RA_ID
