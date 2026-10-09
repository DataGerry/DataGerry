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

Covers both writes of the other side of the membership: ``sync_membership`` on a create / update
(``$addToSet`` into the selected counterparts, the explicit-id ``$pull`` from the unselected ones - that
branch being a regression guard for the former 'CmdbPerson not subscriptable' crash) and the delete
cascade's match-all ``$pull``; and the ISMS cascades that null / pull a deleted
Person or PersonGroup out of IsmsRiskAssessment and IsmsControlMeasureAssignment with the
correct reference-type gating.
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.framework.write_ledger import WriteLedger
from cmdb.interface.rest_api.routes.user_management_routes.person_membership_helper import sync_membership
from cmdb.manager.persons_manager import PersonsManager
from cmdb.manager.person_groups_manager import PersonGroupsManager
from cmdb.models.person_model import CmdbPerson, PersonKey
from cmdb.models.person_group_model import CmdbPersonGroup, PersonGroupKey
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
#                                   MEMBERSHIP SYNC ON CREATE / UPDATE (route helper)                                  #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('direction', ['group_into_persons', 'person_into_groups'])
class TestSyncMembership:
    """``sync_membership`` - the one create/update write of the other side - on the bound collections."""

    @staticmethod
    def _setup(direction: str, persons_manager: PersonsManager, person_groups_manager: PersonGroupsManager,
               database_manager: MongoDatabaseManager, database_name: str,
               listed: list[int]) -> tuple[Any, str, int, list[int], Any]:
        """Seeds two counterparts (the given ones listing the member); answers what the sync needs."""
        if direction == 'group_into_persons':
            database_manager.get_collection(CmdbPerson.COLLECTION, database_name).insert_many([
                _person_doc(PERSON_ID_A, groups=[GROUP_ID_A] if PERSON_ID_A in listed else []),
                _person_doc(PERSON_ID_B, groups=[GROUP_ID_A] if PERSON_ID_B in listed else []),
            ])
            return (persons_manager, PersonKey.GROUPS.value, GROUP_ID_A, [PERSON_ID_A, PERSON_ID_B],
                    lambda public_id: _person_groups(database_manager, database_name, public_id))

        database_manager.get_collection(CmdbPersonGroup.COLLECTION, database_name).insert_many([
            _group_doc(GROUP_ID_A, group_members=[PERSON_ID_A] if GROUP_ID_A in listed else []),
            _group_doc(GROUP_ID_B, group_members=[PERSON_ID_A] if GROUP_ID_B in listed else []),
        ])
        return (person_groups_manager, PersonGroupKey.GROUP_MEMBERS.value, PERSON_ID_A, [GROUP_ID_A, GROUP_ID_B],
                lambda public_id: _group_members(database_manager, database_name, public_id))

    def test_adds_the_member_to_each_selected_counterpart(self, direction, persons_manager, person_groups_manager,
                                                          database_manager, database_name) -> None:
        """Both counterparts list the member afterwards."""
        manager, key, member, counterparts, stored = self._setup(
            direction, persons_manager, person_groups_manager, database_manager, database_name, listed=[])

        sync_membership(WriteLedger(), manager, key, member, counterparts)

        assert [stored(public_id) for public_id in counterparts] == [[member], [member]]

    def test_an_already_listed_member_is_not_duplicated(self, direction, persons_manager, person_groups_manager,
                                                        database_manager, database_name) -> None:
        """'$addToSet', and no write at all for a counterpart already in sync."""
        manager, key, member, counterparts, stored = self._setup(
            direction, persons_manager, person_groups_manager, database_manager, database_name,
            listed=[PERSON_ID_A, GROUP_ID_A])

        sync_membership(WriteLedger(), manager, key, member, counterparts)

        assert [stored(public_id) for public_id in counterparts] == [[member], [member]]

    def test_the_pull_touches_only_the_unselected_counterparts(self, direction, persons_manager,
                                                               person_groups_manager, database_manager,
                                                               database_name) -> None:
        """Both list the member, one stays selected: only the other loses it."""
        manager, key, member, counterparts, stored = self._setup(
            direction, persons_manager, person_groups_manager, database_manager, database_name,
            listed=[PERSON_ID_A, PERSON_ID_B, GROUP_ID_A, GROUP_ID_B])

        sync_membership(WriteLedger(), manager, key, member, counterparts[:1])

        assert [stored(public_id) for public_id in counterparts] == [[member], []]

    def test_an_empty_selection_of_an_unlisted_member_writes_nothing(self, direction, persons_manager,
                                                                     person_groups_manager, database_manager,
                                                                     database_name) -> None:
        """Nothing to add, nothing to pull, and no ledger entry."""
        manager, key, member, counterparts, stored = self._setup(
            direction, persons_manager, person_groups_manager, database_manager, database_name, listed=[])
        ledger = WriteLedger()

        sync_membership(ledger, manager, key, member, [])

        assert not ledger.entries
        assert [stored(public_id) for public_id in counterparts] == [[], []]


# -------------------------------------------------------------------------------------------------------------------- #
#                                    MEMBERSHIP CLEANUP ON DELETE (the manager cascade)                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCounterpartCleanup:
    """The cascade pulls a deleted member out of every counterpart that lists it - the match-all '$pull'."""

    def test_a_deleted_group_leaves_every_person(self, persons_manager: PersonsManager,
                                                  person_groups_manager: PersonGroupsManager,
                                                  database_manager: MongoDatabaseManager, database_name: str) -> None:
        """Both persons listing group A lose it; group B stays listed."""
        database_manager.get_collection(CmdbPerson.COLLECTION, database_name).insert_many([
            _person_doc(PERSON_ID_A, groups=[GROUP_ID_A, GROUP_ID_B]),
            _person_doc(PERSON_ID_B, groups=[GROUP_ID_A]),
        ])

        person_groups_manager.remove_person_group_from_persons(GROUP_ID_A)

        assert _person_groups(database_manager, database_name, PERSON_ID_A) == [GROUP_ID_B]
        assert _person_groups(database_manager, database_name, PERSON_ID_B) == []

    def test_a_deleted_person_leaves_every_group(self, persons_manager: PersonsManager,
                                                 database_manager: MongoDatabaseManager, database_name: str) -> None:
        """Both groups listing person A lose them; person B stays listed."""
        database_manager.get_collection(CmdbPersonGroup.COLLECTION, database_name).insert_many([
            _group_doc(GROUP_ID_A, group_members=[PERSON_ID_A, PERSON_ID_B]),
            _group_doc(GROUP_ID_B, group_members=[PERSON_ID_A]),
        ])

        persons_manager.remove_person_from_person_groups(PERSON_ID_A)

        assert _group_members(database_manager, database_name, GROUP_ID_A) == [PERSON_ID_B]
        assert _group_members(database_manager, database_name, GROUP_ID_B) == []


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


class TestDeleteCascadeCleansTheCounterpartCollection:
    """The half of the cascade that moved out of the delete routes and into the managers."""

    def test_deleting_a_person_removes_them_from_every_group(
        self, persons_manager: PersonsManager, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """
        Any caller deleting a person now gets the membership cleaned up, not just the delete route

        A second call from the route would leave an importer or a bulk delete holding the
        person listed in every group - a membership pointing at a public_id that no longer resolves.
        """
        database_manager.get_collection(CmdbPerson.COLLECTION, database_name)\
            .insert_one(_person_doc(PERSON_ID_A, groups=[GROUP_ID_A, GROUP_ID_B]))
        database_manager.get_collection(CmdbPersonGroup.COLLECTION, database_name).insert_many([
            _group_doc(GROUP_ID_A, group_members=[PERSON_ID_A]),
            _group_doc(GROUP_ID_B, group_members=[PERSON_ID_A, PERSON_ID_OTHER]),
        ])

        persons_manager.delete_with_follow_up(PERSON_ID_A)

        assert _group_members(database_manager, database_name, GROUP_ID_A) == []
        assert _group_members(database_manager, database_name, GROUP_ID_B) == [PERSON_ID_OTHER]

    def test_deleting_a_group_removes_it_from_every_person(
        self,
        person_groups_manager: PersonGroupsManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """The mirror image, written straight to the person collection by the group's own manager."""
        database_manager.get_collection(CmdbPersonGroup.COLLECTION, database_name)\
            .insert_one(_group_doc(GROUP_ID_A, group_members=[PERSON_ID_A, PERSON_ID_B]))
        database_manager.get_collection(CmdbPerson.COLLECTION, database_name).insert_many([
            _person_doc(PERSON_ID_A, groups=[GROUP_ID_A]),
            _person_doc(PERSON_ID_B, groups=[GROUP_ID_A, GROUP_ID_B]),
        ])

        person_groups_manager.delete_with_follow_up(GROUP_ID_A)

        assert _person_groups(database_manager, database_name, PERSON_ID_A) == []
        assert _person_groups(database_manager, database_name, PERSON_ID_B) == [GROUP_ID_B]

    def test_a_person_and_a_group_sharing_a_public_id_are_not_confused(
        self, persons_manager: PersonsManager, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """
        The two counters are independent, so overlapping ids are the normal case, not a corner one

        Deleting person 96001 must not touch an assessment whose owner is the GROUP with the same
        public_id - which is what the '_ref_type' half of every polymorphic filter is for.
        """
        database_manager.get_collection(CmdbPerson.COLLECTION, database_name)\
            .insert_one(_person_doc(PERSON_ID_A))
        database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name).insert_one({
            'public_id': RISK_ASSESSMENT_ID,
            'risk_owner_id': PERSON_ID_A,
            'risk_owner_id_ref_type': PersonReferenceType.PERSON_GROUP.value,
        })

        persons_manager.delete_with_follow_up(PERSON_ID_A)

        assert _risk_assessment(database_manager, database_name)['risk_owner_id'] == PERSON_ID_A

    def test_the_person_is_gone_from_every_place_at_once(
        self, persons_manager: PersonsManager, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """
        The whole cascade in one call: assessor, polymorphic owner, interviewed list, assignment, group

        Asserted together because the value of moving it into the manager is that a caller gets all
        of it, not a subset that depends on which route they came through.
        """
        database_manager.get_collection(CmdbPerson.COLLECTION, database_name)\
            .insert_one(_person_doc(PERSON_ID_A, groups=[GROUP_ID_A]))
        database_manager.get_collection(CmdbPersonGroup.COLLECTION, database_name)\
            .insert_one(_group_doc(GROUP_ID_A, group_members=[PERSON_ID_A]))
        database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name).insert_one({
            'public_id': RISK_ASSESSMENT_ID,
            'risk_assessor_id': PERSON_ID_A,
            'risk_owner_id': PERSON_ID_A,
            'risk_owner_id_ref_type': PersonReferenceType.PERSON.value,
            'interviewed_persons': [PERSON_ID_A, PERSON_ID_OTHER],
        })
        database_manager.get_collection(IsmsControlMeasureAssignment.COLLECTION, database_name).insert_one({
            'public_id': CONTROL_ASSIGNMENT_ID,
            'responsible_for_implementation_id': PERSON_ID_A,
            'responsible_for_implementation_id_ref_type': PersonReferenceType.PERSON.value,
        })

        persons_manager.delete_with_follow_up(PERSON_ID_A)

        assessment = _risk_assessment(database_manager, database_name)
        assignment = database_manager.get_collection(IsmsControlMeasureAssignment.COLLECTION, database_name)\
            .find_one({'public_id': CONTROL_ASSIGNMENT_ID})

        assert assessment['risk_assessor_id'] is None
        assert assessment['risk_owner_id'] is None
        assert assessment['interviewed_persons'] == [PERSON_ID_OTHER]
        assert assignment['responsible_for_implementation_id'] is None
        assert _group_members(database_manager, database_name, GROUP_ID_A) == []
