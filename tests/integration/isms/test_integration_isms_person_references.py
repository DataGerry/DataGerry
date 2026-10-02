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

The real PersonsManager / PersonGroupsManager answer the lookups, so what is pinned is the pairing the check
exists for: a CmdbPerson and a CmdbPersonGroup that share a public_id are told apart by the reference type, and a
reference the check accepts is exactly one the delete cascade of its own collection clears - while the delete of
the OTHER collection's same-numbered document leaves it alone. Also the projected ControlMeasure existence read.
"""
from http import HTTPStatus
from typing import Any

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.database import MongoDatabaseManager
from cmdb.manager.isms_manager.control_measure_assignment_manager import ControlMeasureAssignmentManager
from cmdb.manager.persons_manager import PersonsManager
from cmdb.manager.person_groups_manager import PersonGroupsManager
from cmdb.manager.person_reference_helper import RISK_ASSESSMENT_PERSON_REFERENCE_KEYS, ref_type_key
from cmdb.models.isms_model import IsmsControlMeasure, IsmsRiskAssessment
from cmdb.models.isms_model.isms_risk_assessment_constants import RiskAssessmentKey
from cmdb.models.person_model import CmdbPerson
from cmdb.models.person_group_model import CmdbPersonGroup
from cmdb.models.person_group_model.person_reference_type_enum import PersonReferenceType
from cmdb.interface.rest_api.routes.isms_routes.isms_person_reference_helper import (
    abort_on_unknown_person_references,
    collect_person_references,
)
# -------------------------------------------------------------------------------------------------------------------- #

# A person and a group holding the same public_id - the two counters collide in every real database
SHARED_ID: int = 97501
PERSON_ONLY_ID: int = 97502
RISK_ASSESSMENT_ID: int = 97510
CONTROL_MEASURE_ID: int = 97520
UNKNOWN_CONTROL_MEASURE_ID: int = 97521

RESPONSIBLE_KEY: str = RiskAssessmentKey.RESPONSIBLE_PERSONS_ID.value
PERSON_GROUP: str = PersonReferenceType.PERSON_GROUP.value
PERSON: str = PersonReferenceType.PERSON.value


@pytest.fixture(name='managers')
def fixture_managers(database_manager: MongoDatabaseManager) -> tuple[PersonsManager, PersonGroupsManager]:
    """The two managers the check resolves against"""
    return PersonsManager(database_manager), PersonGroupsManager(database_manager)


@pytest.fixture(name='collections', autouse=True)
def fixture_collections(database_manager: MongoDatabaseManager, database_name: str):
    """A person and a group sharing SHARED_ID, a lone person, and a ControlMeasure; purged before and after"""
    persons = database_manager.get_collection(CmdbPerson.COLLECTION, database_name)
    groups = database_manager.get_collection(CmdbPersonGroup.COLLECTION, database_name)
    assessments = database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)
    measures = database_manager.get_collection(IsmsControlMeasure.COLLECTION, database_name)

    def _purge() -> None:
        persons.delete_many({'public_id': {'$in': [SHARED_ID, PERSON_ONLY_ID]}})
        groups.delete_many({'public_id': SHARED_ID})
        assessments.delete_many({'public_id': RISK_ASSESSMENT_ID})
        measures.delete_many({'public_id': CONTROL_MEASURE_ID})

    _purge()
    persons.insert_one({'public_id': SHARED_ID, 'display_name': 'Shared person', 'groups': []})
    persons.insert_one({'public_id': PERSON_ONLY_ID, 'display_name': 'Lone person', 'groups': []})
    groups.insert_one({'public_id': SHARED_ID, 'name': 'Shared group', 'group_members': []})
    measures.insert_one({'public_id': CONTROL_MEASURE_ID, 'title': 'CM', 'control_measure_type': 'CONTROL'})
    yield assessments
    _purge()


def _responsible(public_id: int, reference_type: str) -> dict[str, Any]:
    """An assessment whose responsible party is the given reference"""
    return {'public_id': RISK_ASSESSMENT_ID, RESPONSIBLE_KEY: public_id, ref_type_key(RESPONSIBLE_KEY): reference_type}


def _check(document: dict[str, Any], managers: tuple[PersonsManager, PersonGroupsManager]) -> None:
    """Runs the check on every reference of an assessment document"""
    with Flask(__name__).app_context():
        abort_on_unknown_person_references(
            collect_person_references(document, RISK_ASSESSMENT_PERSON_REFERENCE_KEYS), *managers,
        )


class TestResolvedAgainstTheNamedCollection:
    """The real lookups tell a person and a group with the same public_id apart"""

    @pytest.mark.parametrize('reference_type', [PERSON, PERSON_GROUP])
    def test_the_shared_id_resolves_under_either_type(self, managers, reference_type: str) -> None:
        """Both documents exist, so both pairings are valid"""
        _check(_responsible(SHARED_ID, reference_type), managers)

    def test_a_lone_person_resolves_as_a_person_only(self, managers) -> None:
        """No group holds PERSON_ONLY_ID, so the group pairing is refused"""
        _check(_responsible(PERSON_ONLY_ID, PERSON), managers)

        with pytest.raises(HTTPException) as caught:
            _check(_responsible(PERSON_ONLY_ID, PERSON_GROUP), managers)

        assert caught.value.code == HTTPStatus.BAD_REQUEST
        assert str(PERSON_ONLY_ID) in caught.value.description


class TestTheAcceptedPairIsTheOneTheCascadeCleans:
    """What the check lets through is exactly what the delete cascade of the named collection clears"""

    def test_the_group_delete_clears_a_group_reference(self, managers, collections) -> None:
        """Accepted as a PERSON_GROUP, cleared by the group's delete"""
        document = _responsible(SHARED_ID, PERSON_GROUP)
        _check(document, managers)
        collections.insert_one(document)

        managers[1].delete_with_follow_up(SHARED_ID)

        assert collections.find_one({'public_id': RISK_ASSESSMENT_ID})[RESPONSIBLE_KEY] is None

    def test_the_person_delete_leaves_a_group_reference_alone(self, managers, collections) -> None:
        """The person sharing the id is not the referenced party, so its delete must not touch the reference"""
        document = _responsible(SHARED_ID, PERSON_GROUP)
        _check(document, managers)
        collections.insert_one(document)

        managers[0].delete_with_follow_up(SHARED_ID)

        assert collections.find_one({'public_id': RISK_ASSESSMENT_ID})[RESPONSIBLE_KEY] == SHARED_ID


class TestControlMeasureExistence:
    """The projected existence read, against the real collection"""

    def test_reports_only_the_unknown_measures(self, database_manager: MongoDatabaseManager) -> None:
        """A stored measure is found through the projection, a missing one is reported"""
        manager = ControlMeasureAssignmentManager(database_manager)

        missing = manager.get_missing_control_measure_ids([
            {'control_measure_id': CONTROL_MEASURE_ID}, {'control_measure_id': UNKNOWN_CONTROL_MEASURE_ID},
        ])

        assert missing == {UNKNOWN_CONTROL_MEASURE_ID}
