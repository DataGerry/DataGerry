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
Integration tests for the membership-sync and ISMS follow-up cleanup of the twin managers
PersonsManager and PersonGroupsManager, run end-to-end against the bound collections.

Covers the bulk membership helpers (``$addToSet`` add, ``$pull`` remove, both the explicit-id and
match-all branches - the explicit-id branch being a regression guard for the former
'CmdbPerson not subscriptable' crash), and the ISMS cascades that null / pull a deleted
Person or PersonGroup out of IsmsRiskAssessment and IsmsControlMeasureAssignment with the
correct reference-type gating.
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.persons_manager import PersonsManager
from cmdb.manager.person_groups_manager import PersonGroupsManager
from cmdb.models.person_model import CmdbPerson
from cmdb.models.person_group_model import CmdbPersonGroup
from cmdb.models.person_group_model.person_reference_type_enum import PersonReferenceType
from cmdb.models.isms_model import IsmsRiskAssessment, IsmsControlMeasureAssignment
# -------------------------------------------------------------------------------------------------------------------- #

PERSON_ID_A: int = 96001
PERSON_ID_B: int = 96002
PERSON_ID_OTHER: int = 96003
GROUP_ID_A: int = 96101
GROUP_ID_B: int = 96102

RISK_ASSESSMENT_ID: int = 96201
CONTROL_ASSIGNMENT_ID: int = 96301

ALL_PERSON_IDS: list[int] = [PERSON_ID_A, PERSON_ID_B, PERSON_ID_OTHER]
ALL_GROUP_IDS: list[int] = [GROUP_ID_A, GROUP_ID_B]
ALL_RISK_ASSESSMENT_IDS: list[int] = [RISK_ASSESSMENT_ID]
ALL_CONTROL_ASSIGNMENT_IDS: list[int] = [CONTROL_ASSIGNMENT_ID]


def _person_doc(public_id: int, groups: list[int] | None = None) -> dict[str, Any]:
    """Builds a minimal CmdbPerson document for direct collection insertion."""
    return {
        'public_id': public_id,
        'display_name': f'Person {public_id}',
        'first_name': 'First',
        'last_name': 'Last',
        'groups': groups if groups is not None else [],
    }


def _group_doc(public_id: int, group_members: list[int] | None = None) -> dict[str, Any]:
    """Builds a minimal CmdbPersonGroup document for direct collection insertion."""
    return {
        'public_id': public_id,
        'name': f'Group {public_id}',
        'email': '',
        'group_members': group_members if group_members is not None else [],
    }


@pytest.fixture(name='persons_manager')
def fixture_persons_manager(database_manager: MongoDatabaseManager) -> PersonsManager:
    """Provides a PersonsManager wired to the test database."""
    return PersonsManager(database_manager)


@pytest.fixture(name='person_groups_manager')
def fixture_person_groups_manager(database_manager: MongoDatabaseManager) -> PersonGroupsManager:
    """Provides a PersonGroupsManager wired to the test database."""
    return PersonGroupsManager(database_manager)


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any docs seeded by a test from all touched collections, before and after each test."""
    def _purge() -> None:
        database_manager.get_collection(CmdbPerson.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_PERSON_IDS}})
        database_manager.get_collection(CmdbPersonGroup.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_GROUP_IDS}})
        database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_RISK_ASSESSMENT_IDS}})
        database_manager.get_collection(IsmsControlMeasureAssignment.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_CONTROL_ASSIGNMENT_IDS}})

    _purge()
    yield
    _purge()


def _person_groups(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> list[int]:
    """Returns the stored 'groups' array of a CmdbPerson."""
    doc = database_manager.get_collection(CmdbPerson.COLLECTION, database_name).find_one({'public_id': public_id})
    return doc['groups']


def _group_members(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> list[int]:
    """Returns the stored 'group_members' array of a CmdbPersonGroup."""
    doc = database_manager.get_collection(CmdbPersonGroup.COLLECTION, database_name)\
        .find_one({'public_id': public_id})
    return doc['group_members']


def _risk_assessment(database_manager: MongoDatabaseManager, database_name: str) -> dict[str, Any]:
    """Returns the seeded IsmsRiskAssessment document."""
    return database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)\
        .find_one({'public_id': RISK_ASSESSMENT_ID})


# -------------------------------------------------------------------------------------------------------------------- #
#                                           PERSONS - GROUP MEMBERSHIP SYNC                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class TestAddGroupToPersons:
    """``add_group_to_persons`` adds the group to each person's 'groups' via a single bulk update."""

    def test_adds_group_to_each_person(
        self, persons_manager: PersonsManager, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The group id is appended to every listed person's 'groups' array."""
        database_manager.get_collection(CmdbPerson.COLLECTION, database_name)\
            .insert_many([_person_doc(PERSON_ID_A), _person_doc(PERSON_ID_B)])

        persons_manager.add_group_to_persons(GROUP_ID_A, [PERSON_ID_A, PERSON_ID_B])

        assert _person_groups(database_manager, database_name, PERSON_ID_A) == [GROUP_ID_A]
        assert _person_groups(database_manager, database_name, PERSON_ID_B) == [GROUP_ID_A]

    def test_is_idempotent(
        self, persons_manager: PersonsManager, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A second add of the same group does not create a duplicate entry ($addToSet)."""
        database_manager.get_collection(CmdbPerson.COLLECTION, database_name)\
            .insert_one(_person_doc(PERSON_ID_A, groups=[GROUP_ID_A]))

        persons_manager.add_group_to_persons(GROUP_ID_A, [PERSON_ID_A])

        assert _person_groups(database_manager, database_name, PERSON_ID_A) == [GROUP_ID_A]

    def test_empty_person_ids_is_noop(self, persons_manager: PersonsManager) -> None:
        """An empty person-id list performs no update and does not raise."""
        persons_manager.add_group_to_persons(GROUP_ID_A, [])


class TestDeleteGroupFromPersons:
    """``delete_group_from_persons`` pulls the group out of the relevant persons' 'groups'."""

    def test_explicit_ids_only_touches_those_persons(
        self, persons_manager: PersonsManager, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """With explicit ids only the listed persons lose the group (regression: used to crash)."""
        database_manager.get_collection(CmdbPerson.COLLECTION, database_name).insert_many([
            _person_doc(PERSON_ID_A, groups=[GROUP_ID_A]),
            _person_doc(PERSON_ID_B, groups=[GROUP_ID_A]),
        ])

        persons_manager.delete_group_from_persons(GROUP_ID_A, [PERSON_ID_A])

        assert _person_groups(database_manager, database_name, PERSON_ID_A) == []
        assert _person_groups(database_manager, database_name, PERSON_ID_B) == [GROUP_ID_A]

    def test_without_ids_touches_all_members(
        self, persons_manager: PersonsManager, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Without explicit ids the group is pulled from every person that references it."""
        database_manager.get_collection(CmdbPerson.COLLECTION, database_name).insert_many([
            _person_doc(PERSON_ID_A, groups=[GROUP_ID_A]),
            _person_doc(PERSON_ID_B, groups=[GROUP_ID_A]),
        ])

        persons_manager.delete_group_from_persons(GROUP_ID_A)

        assert _person_groups(database_manager, database_name, PERSON_ID_A) == []
        assert _person_groups(database_manager, database_name, PERSON_ID_B) == []


# -------------------------------------------------------------------------------------------------------------------- #
#                                        PERSON GROUPS - MEMBER MEMBERSHIP SYNC                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestAddPersonToGroups:
    """``add_person_to_groups`` adds the person to each group's 'group_members' via a bulk update."""

    def test_adds_person_to_each_group(
        self,
        person_groups_manager: PersonGroupsManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """The person id is appended to every listed group's 'group_members' array."""
        database_manager.get_collection(CmdbPersonGroup.COLLECTION, database_name)\
            .insert_many([_group_doc(GROUP_ID_A), _group_doc(GROUP_ID_B)])

        person_groups_manager.add_person_to_groups(PERSON_ID_A, [GROUP_ID_A, GROUP_ID_B])

        assert _group_members(database_manager, database_name, GROUP_ID_A) == [PERSON_ID_A]
        assert _group_members(database_manager, database_name, GROUP_ID_B) == [PERSON_ID_A]

    def test_is_idempotent(
        self,
        person_groups_manager: PersonGroupsManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """A second add of the same person does not create a duplicate member entry."""
        database_manager.get_collection(CmdbPersonGroup.COLLECTION, database_name)\
            .insert_one(_group_doc(GROUP_ID_A, group_members=[PERSON_ID_A]))

        person_groups_manager.add_person_to_groups(PERSON_ID_A, [GROUP_ID_A])

        assert _group_members(database_manager, database_name, GROUP_ID_A) == [PERSON_ID_A]


class TestDeletePersonFromGroups:
    """``delete_person_from_groups`` pulls the person out of the relevant groups' members."""

    def test_explicit_ids_only_touches_those_groups(
        self,
        person_groups_manager: PersonGroupsManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """With explicit ids only the listed groups lose the member (regression: used to crash)."""
        database_manager.get_collection(CmdbPersonGroup.COLLECTION, database_name).insert_many([
            _group_doc(GROUP_ID_A, group_members=[PERSON_ID_A]),
            _group_doc(GROUP_ID_B, group_members=[PERSON_ID_A]),
        ])

        person_groups_manager.delete_person_from_groups(PERSON_ID_A, [GROUP_ID_A])

        assert _group_members(database_manager, database_name, GROUP_ID_A) == []
        assert _group_members(database_manager, database_name, GROUP_ID_B) == [PERSON_ID_A]


# -------------------------------------------------------------------------------------------------------------------- #
#                                               ISMS FOLLOW-UP CLEANUP                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TestRemovePersonFromRiskAssessments:
    """Deleting a Person nulls its person-typed slots and pulls it from 'interviewed_persons'."""

    def test_nulls_person_slots_and_respects_ref_type(
        self, persons_manager: PersonsManager, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Person-typed references are cleared; a slot typed as PERSON_GROUP is left untouched."""
        database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name).insert_one({
            'public_id': RISK_ASSESSMENT_ID,
            'risk_assessor_id': PERSON_ID_A,
            'risk_owner_id': PERSON_ID_A,
            'risk_owner_id_ref_type': PersonReferenceType.PERSON,
            'responsible_persons_id': PERSON_ID_A,
            'responsible_persons_id_ref_type': PersonReferenceType.PERSON,
            'auditor_id': PERSON_ID_A,
            'auditor_id_ref_type': PersonReferenceType.PERSON_GROUP,
            'interviewed_persons': [PERSON_ID_A, PERSON_ID_OTHER],
        })

        persons_manager.remove_person_from_risk_assessments(PERSON_ID_A)

        doc = _risk_assessment(database_manager, database_name)
        assert doc['risk_assessor_id'] is None
        assert doc['risk_owner_id'] is None
        assert doc['responsible_persons_id'] is None
        # auditor_id is typed PERSON_GROUP, so the person cascade must leave it untouched
        assert doc['auditor_id'] == PERSON_ID_A
        assert doc['interviewed_persons'] == [PERSON_ID_OTHER]


class TestRemovePersonGroupFromRiskAssessments:
    """Deleting a PersonGroup nulls only the slots typed as PERSON_GROUP that reference it."""

    def test_nulls_group_slots_and_respects_ref_type(
        self,
        person_groups_manager: PersonGroupsManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """PERSON_GROUP-typed references are cleared; a slot typed as PERSON is left untouched."""
        database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name).insert_one({
            'public_id': RISK_ASSESSMENT_ID,
            'responsible_persons_id': GROUP_ID_A,
            'responsible_persons_id_ref_type': PersonReferenceType.PERSON_GROUP,
            'risk_owner_id': GROUP_ID_A,
            'risk_owner_id_ref_type': PersonReferenceType.PERSON_GROUP,
            'auditor_id': GROUP_ID_A,
            'auditor_id_ref_type': PersonReferenceType.PERSON,
        })

        person_groups_manager.remove_person_group_from_risk_assessments(GROUP_ID_A)

        doc = _risk_assessment(database_manager, database_name)
        assert doc['responsible_persons_id'] is None
        assert doc['risk_owner_id'] is None
        # auditor_id is typed PERSON, so the person-group cascade must leave it untouched
        assert doc['auditor_id'] == GROUP_ID_A


class TestRemoveFromControlMeasureAssignments:
    """The ControlMeasureAssignment cascades null the responsible slot only on a ref-type match."""

    def test_person_cascade_nulls_only_person_typed(
        self, persons_manager: PersonsManager, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A PERSON-typed responsible slot referencing the deleted person is nulled."""
        database_manager.get_collection(IsmsControlMeasureAssignment.COLLECTION, database_name).insert_one({
            'public_id': CONTROL_ASSIGNMENT_ID,
            'responsible_for_implementation_id': PERSON_ID_A,
            'responsible_for_implementation_id_ref_type': PersonReferenceType.PERSON,
        })

        persons_manager.remove_person_from_control_measure_assignments(PERSON_ID_A)

        doc = database_manager.get_collection(IsmsControlMeasureAssignment.COLLECTION, database_name)\
            .find_one({'public_id': CONTROL_ASSIGNMENT_ID})
        assert doc['responsible_for_implementation_id'] is None

    def test_group_cascade_ignores_person_typed(
        self,
        person_groups_manager: PersonGroupsManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """A PERSON-typed slot is left untouched by the person-group cascade even on an id match."""
        database_manager.get_collection(IsmsControlMeasureAssignment.COLLECTION, database_name).insert_one({
            'public_id': CONTROL_ASSIGNMENT_ID,
            'responsible_for_implementation_id': GROUP_ID_A,
            'responsible_for_implementation_id_ref_type': PersonReferenceType.PERSON,
        })

        person_groups_manager.remove_person_group_from_control_measure_assignments(GROUP_ID_A)

        doc = database_manager.get_collection(IsmsControlMeasureAssignment.COLLECTION, database_name)\
            .find_one({'public_id': CONTROL_ASSIGNMENT_ID})
        assert doc['responsible_for_implementation_id'] == GROUP_ID_A


class TestDeleteWithFollowUp:
    """``delete_with_follow_up`` removes the entity and runs the ISMS cascades end-to-end."""

    def test_person_delete_removes_doc_and_clears_reference(
        self, persons_manager: PersonsManager, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Deleting a person removes it and nulls its reference in a RiskAssessment."""
        database_manager.get_collection(CmdbPerson.COLLECTION, database_name)\
            .insert_one(_person_doc(PERSON_ID_A))
        database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name).insert_one({
            'public_id': RISK_ASSESSMENT_ID,
            'risk_assessor_id': PERSON_ID_A,
        })

        result = persons_manager.delete_with_follow_up(PERSON_ID_A)

        assert result is True
        assert database_manager.get_collection(CmdbPerson.COLLECTION, database_name)\
            .find_one({'public_id': PERSON_ID_A}) is None
        assert _risk_assessment(database_manager, database_name)['risk_assessor_id'] is None
