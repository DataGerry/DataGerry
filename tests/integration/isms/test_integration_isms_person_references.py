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
Integration tests for the ISMS person-reference check, against the real collections

Persons and groups are objects of the test person Types. What is pinned: an id resolves only as the marker its
reference type names (a group object sent as a PERSON is refused, so is an ordinary object), a writer who may not READ
the Type is refused with 403, and a reference the check accepts is exactly one the clean-up after the object's delete
clears - while the delete of another object leaves it alone. Also the projected ControlMeasure existence read.
"""
from http import HTTPStatus
from typing import Any

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectsManager
from cmdb.manager.isms_manager.control_measure_assignment_manager import ControlMeasureAssignmentManager
from cmdb.manager.person_reference_helper import RISK_ASSESSMENT_PERSON_REFERENCE_KEYS, ref_type_key
from cmdb.models.isms_model import IsmsControlMeasure, IsmsRiskAssessment
from cmdb.models.isms_model.isms_risk_assessment_constants import RiskAssessmentKey
from cmdb.models.object_model.cmdb_object import CmdbObject
from cmdb.models.person_group_model.person_reference_type_enum import PersonReferenceType
from cmdb.framework.person_types.person_isms_cleanup import clear_isms_person_references
from cmdb.interface.rest_api.routes.isms_routes.isms_person_reference_helper import (
    abort_on_unknown_person_references,
    collect_person_references,
)
from tests.utils.ipam_doc_builders import make_object_doc
from tests.utils.person_objects import TEST_PERSON_TYPE_ID, purge_person_objects, seed_person_objects
# -------------------------------------------------------------------------------------------------------------------- #

PERSON_ID: int = 97501
GROUP_ID: int = 97502
PLAIN_OBJECT_ID: int = 97503
PLAIN_TYPE_ID: int = 97509
RISK_ASSESSMENT_ID: int = 97510
CONTROL_MEASURE_ID: int = 97520
UNKNOWN_CONTROL_MEASURE_ID: int = 97521

RESPONSIBLE_KEY: str = RiskAssessmentKey.RESPONSIBLE_PERSONS_ID.value
PERSON_GROUP: str = PersonReferenceType.PERSON_GROUP.value
PERSON: str = PersonReferenceType.PERSON.value


@pytest.fixture(name='manager')
def fixture_manager(database_manager: MongoDatabaseManager) -> ObjectsManager:
    """The objects manager the check resolves against"""
    return ObjectsManager(database_manager)


@pytest.fixture(name='collections', autouse=True)
def fixture_collections(database_manager: MongoDatabaseManager, database_name: str):
    """A person, a group, an ordinary object and a ControlMeasure; purged before and after"""
    assessments = database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)
    measures = database_manager.get_collection(IsmsControlMeasure.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    def _purge() -> None:
        purge_person_objects(database_manager, database_name, [PERSON_ID, GROUP_ID, PLAIN_OBJECT_ID])
        assessments.delete_many({'public_id': RISK_ASSESSMENT_ID})
        measures.delete_many({'public_id': CONTROL_MEASURE_ID})

    _purge()
    seed_person_objects(database_manager, database_name, persons={PERSON_ID: 'Person'}, groups={GROUP_ID: 'Group'})
    objects.insert_one(make_object_doc(PLAIN_OBJECT_ID, PLAIN_TYPE_ID, []))
    measures.insert_one({'public_id': CONTROL_MEASURE_ID, 'title': 'CM', 'control_measure_type': 'CONTROL'})
    yield assessments
    _purge()


def _responsible(public_id: int, reference_type: str) -> dict[str, Any]:
    """An assessment whose responsible party is the given reference"""
    return {'public_id': RISK_ASSESSMENT_ID, RESPONSIBLE_KEY: public_id, ref_type_key(RESPONSIBLE_KEY): reference_type}


def _check(document: dict[str, Any], manager: ObjectsManager, *hidden: int) -> None:
    """Runs the check on every reference of an assessment document, the writer denied the given Types"""
    with Flask(__name__).app_context():
        abort_on_unknown_person_references(
            collect_person_references(document, RISK_ASSESSMENT_PERSON_REFERENCE_KEYS), manager,
            lambda: frozenset(hidden),
        )


class TestResolvedByMarker:
    """The real reads tell persons, groups and ordinary objects apart by the marker they carry"""

    @pytest.mark.parametrize('public_id, reference_type', [(PERSON_ID, PERSON), (GROUP_ID, PERSON_GROUP)])
    def test_an_object_of_the_named_marker_resolves(self, manager, public_id: int, reference_type: str) -> None:
        """A person as PERSON, a group as PERSON_GROUP"""
        _check(_responsible(public_id, reference_type), manager)

    @pytest.mark.parametrize('public_id, reference_type', [
        (GROUP_ID, PERSON), (PERSON_ID, PERSON_GROUP), (PLAIN_OBJECT_ID, PERSON),
    ], ids=['group-as-person', 'person-as-group', 'ordinary-object'])
    def test_any_other_object_is_refused(self, manager, public_id: int, reference_type: str) -> None:
        """400 naming the id"""
        with pytest.raises(HTTPException) as caught:
            _check(_responsible(public_id, reference_type), manager)

        assert caught.value.code == HTTPStatus.BAD_REQUEST
        assert str(public_id) in caught.value.description

    def test_a_person_of_a_hidden_type_is_forbidden(self, manager) -> None:
        """The writer may not READ the person Type: 403"""
        with pytest.raises(HTTPException) as caught:
            _check(_responsible(PERSON_ID, PERSON), manager, TEST_PERSON_TYPE_ID)

        assert caught.value.code == HTTPStatus.FORBIDDEN


class TestTheAcceptedPairIsTheOneTheCleanupClears:
    """What the check lets through is exactly what the clean-up after the object's delete clears"""

    def test_the_group_delete_clears_a_group_reference(self, manager, collections) -> None:
        """Accepted as a PERSON_GROUP, cleared for the deleted group"""
        document = _responsible(GROUP_ID, PERSON_GROUP)
        _check(document, manager)
        collections.insert_one(document)

        clear_isms_person_references(manager, {PersonReferenceType.PERSON_GROUP: [GROUP_ID]})

        assert collections.find_one({'public_id': RISK_ASSESSMENT_ID})[RESPONSIBLE_KEY] is None

    def test_another_delete_leaves_the_reference_alone(self, manager, collections) -> None:
        """The deleted person is not the referenced party"""
        document = _responsible(GROUP_ID, PERSON_GROUP)
        collections.insert_one(document)

        clear_isms_person_references(manager, {PersonReferenceType.PERSON: [PERSON_ID]})

        assert collections.find_one({'public_id': RISK_ASSESSMENT_ID})[RESPONSIBLE_KEY] == GROUP_ID


class TestControlMeasureExistence:
    """The projected existence read, against the real collection"""

    def test_reports_only_the_unknown_measures(self, database_manager: MongoDatabaseManager) -> None:
        """A stored measure is found through the projection, a missing one is reported"""
        manager = ControlMeasureAssignmentManager(database_manager)

        missing = manager.get_missing_control_measure_ids([
            {'control_measure_id': CONTROL_MEASURE_ID}, {'control_measure_id': UNKNOWN_CONTROL_MEASURE_ID},
        ])

        assert missing == {UNKNOWN_CONTROL_MEASURE_ID}
