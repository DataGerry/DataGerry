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

Persons and person groups are CmdbObjects of the PERSON / PERSON_GROUP SpecialTypes; the real ObjectsManager /
TypesManager answer the lookups. Pinned is the pairing the check exists for: an id is only accepted under the
reference type naming its object's SpecialType - a group's id sent as a PERSON, or an ordinary object's id, is
refused - and a reference the check accepts is exactly one the object delete clears, while the delete of
another object leaves it alone. Also the projected ControlMeasure existence read.
"""
from http import HTTPStatus
from typing import Any

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectsManager, TypesManager
from cmdb.manager.isms_manager.control_measure_assignment_manager import ControlMeasureAssignmentManager
from cmdb.manager.person_reference_helper import RISK_ASSESSMENT_PERSON_REFERENCE_KEYS, ref_type_key
from cmdb.models.isms_model import IsmsControlMeasure, IsmsRiskAssessment
from cmdb.models.isms_model.isms_risk_assessment_constants import RiskAssessmentKey
from cmdb.models.person_group_model.person_reference_type_enum import PersonReferenceType
from cmdb.interface.rest_api.routes.isms_routes.isms_person_reference_helper import (
    abort_on_unknown_person_references,
    collect_person_references,
)
from tests.utils.ipam_doc_builders import make_object_doc
from tests.utils.person_seed import ensure_person_types, group_doc, insert_objects, person_doc, remove_objects
# -------------------------------------------------------------------------------------------------------------------- #

GROUP_ID: int = 97501
PERSON_ID: int = 97502
OTHER_PERSON_ID: int = 97503
ORDINARY_OBJECT_ID: int = 97504
OBJECT_IDS: list[int] = [GROUP_ID, PERSON_ID, OTHER_PERSON_ID, ORDINARY_OBJECT_ID]
RISK_ASSESSMENT_ID: int = 97510
CONTROL_MEASURE_ID: int = 97520
UNKNOWN_CONTROL_MEASURE_ID: int = 97521

RESPONSIBLE_KEY: str = RiskAssessmentKey.RESPONSIBLE_PERSONS_ID.value
PERSON_GROUP: str = PersonReferenceType.PERSON_GROUP.value
PERSON: str = PersonReferenceType.PERSON.value


@pytest.fixture(name='managers')
def fixture_managers(database_manager: MongoDatabaseManager, database_name: str) -> tuple[ObjectsManager, TypesManager]:
    """The two managers the check resolves against"""
    return ObjectsManager(database_manager, database_name), TypesManager(database_manager, database_name)


@pytest.fixture(name='collections', autouse=True)
def fixture_collections(database_manager: MongoDatabaseManager, database_name: str):
    """A group, two persons, an ordinary object and a ControlMeasure; purged before and after"""
    assessments = database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)
    measures = database_manager.get_collection(IsmsControlMeasure.COLLECTION, database_name)
    person_type_id, group_type_id = ensure_person_types(database_manager, database_name)

    def _purge() -> None:
        remove_objects(database_manager, database_name, OBJECT_IDS)
        assessments.delete_many({'public_id': RISK_ASSESSMENT_ID})
        measures.delete_many({'public_id': CONTROL_MEASURE_ID})

    _purge()
    insert_objects(
        database_manager, database_name,
        person_doc(PERSON_ID, person_type_id, 'Lone person'),
        person_doc(OTHER_PERSON_ID, person_type_id, 'Other person'),
        group_doc(GROUP_ID, group_type_id, 'A group', [PERSON_ID]),
        make_object_doc(ORDINARY_OBJECT_ID, 1, []),
    )
    measures.insert_one({'public_id': CONTROL_MEASURE_ID, 'title': 'CM', 'control_measure_type': 'CONTROL'})
    yield assessments
    _purge()


def _responsible(public_id: int, reference_type: str) -> dict[str, Any]:
    """An assessment whose responsible party is the given reference"""
    return {'public_id': RISK_ASSESSMENT_ID, RESPONSIBLE_KEY: public_id, ref_type_key(RESPONSIBLE_KEY): reference_type}


def _check(document: dict[str, Any], managers: tuple[ObjectsManager, TypesManager]) -> None:
    """Runs the check on every reference of an assessment document"""
    with Flask(__name__).app_context():
        abort_on_unknown_person_references(
            collect_person_references(document, RISK_ASSESSMENT_PERSON_REFERENCE_KEYS), *managers,
        )


class TestResolvedAgainstTheNamedSpecialType:
    """The real lookups resolve an id to the SpecialType of its object"""

    @pytest.mark.parametrize('public_id, reference_type', [(PERSON_ID, PERSON), (GROUP_ID, PERSON_GROUP)])
    def test_an_id_resolves_under_its_own_type(self, managers, public_id: int, reference_type: str) -> None:
        """A person as a PERSON, a group as a PERSON_GROUP"""
        _check(_responsible(public_id, reference_type), managers)

    @pytest.mark.parametrize('public_id, reference_type', [(PERSON_ID, PERSON_GROUP), (GROUP_ID, PERSON)])
    def test_an_id_under_the_other_type_is_refused(self, managers, public_id: int, reference_type: str) -> None:
        """The object exists, but is of the other person SpecialType"""
        with pytest.raises(HTTPException) as caught:
            _check(_responsible(public_id, reference_type), managers)

        assert caught.value.code == HTTPStatus.BAD_REQUEST
        assert str(public_id) in caught.value.description

    def test_an_ordinary_object_is_refused(self, managers) -> None:
        """An existing object of another type is no person"""
        with pytest.raises(HTTPException) as caught:
            _check(_responsible(ORDINARY_OBJECT_ID, PERSON), managers)

        assert caught.value.code == HTTPStatus.BAD_REQUEST

    def test_every_key_of_an_assessment_is_resolved(self, managers) -> None:
        """Assessor and interviewed persons are persons; one unknown entry fails the whole document"""
        document = {
            'public_id': RISK_ASSESSMENT_ID,
            RiskAssessmentKey.RISK_ASSESSOR_ID.value: PERSON_ID,
            RiskAssessmentKey.INTERVIEWED_PERSONS.value: [PERSON_ID, OTHER_PERSON_ID],
        }
        _check(document, managers)

        document[RiskAssessmentKey.INTERVIEWED_PERSONS.value].append(GROUP_ID)

        with pytest.raises(HTTPException):
            _check(document, managers)


class TestTheAcceptedPairIsTheOneTheDeleteCleans:
    """What the check lets through is exactly what the object delete clears"""

    def test_the_group_delete_clears_a_group_reference(self, managers, collections) -> None:
        """Accepted as a PERSON_GROUP, cleared when the group object is deleted"""
        document = _responsible(GROUP_ID, PERSON_GROUP)
        _check(document, managers)
        collections.insert_one(document)

        managers[0].delete_all_object_references([GROUP_ID])

        assert collections.find_one({'public_id': RISK_ASSESSMENT_ID})[RESPONSIBLE_KEY] is None

    def test_another_delete_leaves_the_reference_alone(self, managers, collections) -> None:
        """Deleting a different person must not touch the reference"""
        document = _responsible(GROUP_ID, PERSON_GROUP)
        _check(document, managers)
        collections.insert_one(document)

        managers[0].delete_all_object_references([OTHER_PERSON_ID])

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
