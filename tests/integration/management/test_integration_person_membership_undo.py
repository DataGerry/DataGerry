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
Integration tests: the reciprocal membership write and its undo, on real Mongo

``sync_membership`` and ``record_delete_cascade`` hand the WriteLedger inverses that run real ``$addToSet`` /
``$pull`` / ``replace_one`` / ``insert_one`` writes. Pinned here against the bound collections: the sync lands on
what the other side stores, its undo restores exactly the listing read before it, a second undo changes nothing
more, and the recorded delete cascade restores the ISMS documents, the membership and the document itself.
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.framework.write_ledger import WriteLedger
from cmdb.manager import ControlMeasureAssignmentManager, PersonGroupsManager, PersonsManager, RiskAssessmentManager
from cmdb.models.isms_model import IsmsControlMeasureAssignment, IsmsRiskAssessment
from cmdb.models.person_group_model import CmdbPersonGroup, PersonGroupKey
from cmdb.models.person_group_model.person_reference_type_enum import PersonReferenceType
from cmdb.models.person_model import CmdbPerson
from cmdb.interface.rest_api.routes.user_management_routes.person_membership_helper import (
    record_delete_cascade,
    sync_membership,
)
# -------------------------------------------------------------------------------------------------------------------- #

PERSON_ID: int = 96601
GROUP_A: int = 96701
GROUP_B: int = 96702
GROUP_C: int = 96703
ASSESSMENT_ID: int = 96801
ASSIGNMENT_ID: int = 96901

ALL_GROUP_IDS: list[int] = [GROUP_A, GROUP_B, GROUP_C]
MEMBERS_KEY: str = PersonGroupKey.GROUP_MEMBERS.value


@pytest.fixture(name='managers')
def fixture_managers(database_manager: MongoDatabaseManager, database_name: str):
    """The person in groups A and B, and ISMS documents naming the person; purged around each test."""
    persons = PersonsManager(database_manager)
    groups = PersonGroupsManager(database_manager)
    assessments = RiskAssessmentManager(database_manager)
    assignments = ControlMeasureAssignmentManager(database_manager)
    collections = {manager.collection: database_manager.get_collection(manager.collection, database_name)
                   for manager in (persons, groups, assessments, assignments)}

    def _purge() -> None:
        collections[CmdbPerson.COLLECTION].delete_many({'public_id': PERSON_ID})
        collections[CmdbPersonGroup.COLLECTION].delete_many({'public_id': {'$in': ALL_GROUP_IDS}})
        collections[IsmsRiskAssessment.COLLECTION].delete_many({'public_id': ASSESSMENT_ID})
        collections[IsmsControlMeasureAssignment.COLLECTION].delete_many({'public_id': ASSIGNMENT_ID})

    _purge()
    collections[CmdbPerson.COLLECTION].insert_one({'public_id': PERSON_ID, 'display_name': 'P', 'first_name': 'F',
                                                  'last_name': 'L', 'groups': [GROUP_A, GROUP_B]})
    collections[CmdbPersonGroup.COLLECTION].insert_many([
        {'public_id': GROUP_A, 'name': 'A', 'email': '', MEMBERS_KEY: [PERSON_ID]},
        {'public_id': GROUP_B, 'name': 'B', 'email': '', MEMBERS_KEY: [PERSON_ID]},
        {'public_id': GROUP_C, 'name': 'C', 'email': '', MEMBERS_KEY: []},
    ])
    collections[IsmsRiskAssessment.COLLECTION].insert_one({
        'public_id': ASSESSMENT_ID, 'risk_assessor_id': PERSON_ID, 'interviewed_persons': [PERSON_ID],
        'risk_owner_id': PERSON_ID, 'risk_owner_id_ref_type': 'PERSON',
    })
    collections[IsmsControlMeasureAssignment.COLLECTION].insert_one({
        'public_id': ASSIGNMENT_ID, 'responsible_for_implementation_id': PERSON_ID,
        'responsible_for_implementation_id_ref_type': 'PERSON',
    })
    yield persons, groups, assessments, assignments, collections
    _purge()


def _members(collections: dict[str, Any]) -> dict[int, list[int]]:
    """The stored membership of each test group."""
    return {doc['public_id']: doc[MEMBERS_KEY]
            for doc in collections[CmdbPersonGroup.COLLECTION].find({'public_id': {'$in': ALL_GROUP_IDS}})}


def _state(collections: dict[str, Any]) -> list[list[dict[str, Any]]]:
    """Every test document of the four collections, without Mongo's _id."""
    ids = [PERSON_ID, *ALL_GROUP_IDS, ASSESSMENT_ID, ASSIGNMENT_ID]
    return [sorted(({k: v for k, v in doc.items() if k != '_id'} for doc in collection.find(
        {'public_id': {'$in': ids}})), key=lambda doc: doc['public_id']) for collection in collections.values()]


class TestSyncMembership:
    """The reciprocal write on the real collection."""

    def test_moves_the_member_to_the_selection(self, managers) -> None:
        """Selected {B, C} against a listing of {A, B}: A pulled, C added, B untouched."""
        groups, collections = managers[1], managers[4]

        sync_membership(WriteLedger(), groups, MEMBERS_KEY, PERSON_ID, [GROUP_B, GROUP_C])

        assert _members(collections) == {GROUP_A: [], GROUP_B: [PERSON_ID], GROUP_C: [PERSON_ID]}

    def test_the_undo_restores_the_listing_and_a_second_undo_changes_nothing(self, managers) -> None:
        """Both inverses land and verify clean; running the ledger again is harmless."""
        groups, collections = managers[1], managers[4]
        before = _members(collections)
        ledger = WriteLedger()
        sync_membership(ledger, groups, MEMBERS_KEY, PERSON_ID, [GROUP_C])

        assert not ledger.undo()
        assert _members(collections) == before
        assert not ledger.undo()
        assert _members(collections) == before

    def test_a_member_already_back_is_not_added_twice(self, managers) -> None:
        """'$addToSet' on the way back: an undo of a pull that never landed adds nothing."""
        groups, collections = managers[1], managers[4]
        ledger = WriteLedger()
        sync_membership(ledger, groups, MEMBERS_KEY, PERSON_ID, [])
        collections[CmdbPersonGroup.COLLECTION].update_one({'public_id': GROUP_A},
                                                           {'$set': {MEMBERS_KEY: [PERSON_ID]}})

        assert not ledger.undo()
        assert _members(collections)[GROUP_A] == [PERSON_ID]


class TestRecordDeleteCascade:
    """The recorded inverse of the whole delete cascade, run after the cascade itself on the real collections."""

    def test_a_finished_delete_is_undone_completely(self, managers) -> None:
        """References cleared, membership pulled, document deleted: the undo restores all of it, twice safely."""
        persons, groups, assessments, assignments, collections = managers
        before = _state(collections)
        ledger = WriteLedger()
        snapshot = persons.get_item(PERSON_ID, as_dict=True)

        record_delete_cascade(ledger, persons, groups, MEMBERS_KEY, snapshot, PersonReferenceType.PERSON,
                              (assessments, assignments))
        persons.delete_with_follow_up(PERSON_ID)

        assert _state(collections) != before
        assert not ledger.undo()
        assert _state(collections) == before
        assert not ledger.undo()
        assert _state(collections) == before

    def test_an_undo_before_the_cascade_ran_changes_nothing(self, managers) -> None:
        """Recorded but never run: every inverse finds its document as the snapshot, and inserts no copy."""
        persons, groups, assessments, assignments, collections = managers
        before = _state(collections)
        ledger = WriteLedger()

        record_delete_cascade(ledger, persons, groups, MEMBERS_KEY, persons.get_item(PERSON_ID, as_dict=True),
                              PersonReferenceType.PERSON, (assessments, assignments))

        assert not ledger.undo()
        assert _state(collections) == before
