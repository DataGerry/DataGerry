# DATAGERRY - OpenSource Enterprise CMDB
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
Unit tests for cmdb.manager.person_reference_helper

Pure tests: no Mongo. The module holds what PersonsManager and PersonGroupsManager do identically -
maintaining the reciprocal membership array, and clearing the polymorphic ISMS references of a deleted
person or group. Both managers are thin wrappers over it, so the rules live here and are asserted once:

  - an empty or missing selection writes NOTHING, rather than issuing a query matching every document
  - the '$pull' reaches every document listing the member when no selection is given, which is what a
    deletion needs, and is restricted when one is
  - **every polymorphic filter names the '_ref_type' sibling.** Without it, deleting person 7 would
    also clear a field pointing at the *group* with public_id 7 - the ids come from two independent
    counters and collide constantly
  - **the snapshot criteria select what the clears write.** The delete route snapshots the documents the
    cascade will change with ``risk_assessment_reference_criteria`` / ``control_measure_assignment_reference_
    criteria``; a document the clears reach but the criteria miss would not be restored by an undo
"""
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.manager.person_reference_helper import (
    CONTROL_MEASURE_ASSIGNMENT_PERSON_REFERENCE_KEYS,
    PERSON_ONLY_RISK_ASSESSMENT_KEYS,
    POLYMORPHIC_RISK_ASSESSMENT_PERSON_KEYS,
    RISK_ASSESSMENT_PERSON_REFERENCE_KEYS,
    ref_type_key,
    add_member_to_documents,
    clear_control_measure_assignment_reference,
    clear_polymorphic_risk_assessment_references,
    control_measure_assignment_reference_criteria,
    polymorphic_reference_filter,
    remove_member_from_documents,
    risk_assessment_reference_criteria,
)
from cmdb.models.isms_model.isms_control_measure_assignment_constants import ControlMeasureAssignmentKey
from cmdb.models.isms_model.isms_risk_assessment_constants import RiskAssessmentKey
from cmdb.models.person_group_model import PersonReferenceType
# -------------------------------------------------------------------------------------------------------------------- #

DB_NAME: str = 'testdb'
COLLECTION: str = 'management.person'
ARRAY_KEY: str = 'groups'
MEMBER_ID: int = 3
RA_COLLECTION: str = 'isms.riskAssessment'
CMA_COLLECTION: str = 'isms.controlMeasureAssignment'


class TestAddMemberToDocuments:
    """The '$addToSet' half of the reciprocal membership."""

    def test_adds_the_member_to_the_named_documents_only(self) -> None:
        """One bulk update selected by public_id, with add_to_set doing the duplicate check."""
        dbm = MagicMock()

        add_member_to_documents(dbm, DB_NAME, COLLECTION, ARRAY_KEY, MEMBER_ID, [10, 11])

        dbm.update_many.assert_called_once_with(
            COLLECTION,
            DB_NAME,
            {'public_id': {'$in': [10, 11]}},
            {ARRAY_KEY: MEMBER_ID},
            add_to_set=True,
        )

    def test_accepts_a_set_of_ids(self) -> None:
        """
        The routes compute the delta as a set difference and hand the set straight over

        pymongo cannot encode a set, so the conversion to a list has to happen here rather than at
        each of the four call sites.
        """
        dbm = MagicMock()

        add_member_to_documents(dbm, DB_NAME, COLLECTION, ARRAY_KEY, MEMBER_ID, {10})

        assert dbm.update_many.call_args.args[2] == {'public_id': {'$in': [10]}}

    def test_writes_nothing_for_an_empty_selection(self) -> None:
        """An update that adds no memberships must not touch the collection at all."""
        dbm = MagicMock()

        add_member_to_documents(dbm, DB_NAME, COLLECTION, ARRAY_KEY, MEMBER_ID, [])

        dbm.update_many.assert_not_called()

    def test_writes_nothing_for_a_missing_selection(self) -> None:
        """None is the same as nothing to add, not 'every document'."""
        dbm = MagicMock()

        add_member_to_documents(dbm, DB_NAME, COLLECTION, ARRAY_KEY, MEMBER_ID, None)

        dbm.update_many.assert_not_called()


class TestRemoveMemberFromDocuments:
    """The '$pull' half, whose two modes are what the delete and the update cascades need."""

    def test_restricts_the_pull_when_documents_are_named(self) -> None:
        """An update only drops the memberships the payload actually removed."""
        dbm = MagicMock()

        remove_member_from_documents(dbm, DB_NAME, COLLECTION, ARRAY_KEY, MEMBER_ID, [10])

        dbm.update_many_raw.assert_called_once_with(
            COLLECTION,
            DB_NAME,
            {ARRAY_KEY: MEMBER_ID, 'public_id': {'$in': [10]}},
            {'$pull': {ARRAY_KEY: MEMBER_ID}},
        )

    def test_reaches_every_listing_document_when_none_are_named(self) -> None:
        """
        What a deletion needs: the member is gone, so no document may keep listing them

        The absence of a selection is the instruction here, which is why it is None rather than an
        empty list - the two mean opposite things in this function.
        """
        dbm = MagicMock()

        remove_member_from_documents(dbm, DB_NAME, COLLECTION, ARRAY_KEY, MEMBER_ID)

        dbm.update_many_raw.assert_called_once_with(
            COLLECTION,
            DB_NAME,
            {ARRAY_KEY: MEMBER_ID},
            {'$pull': {ARRAY_KEY: MEMBER_ID}},
        )

    def test_an_empty_selection_pulls_from_nothing(self) -> None:
        """
        An empty list is a selection of no documents, and must not be read as 'all of them'

        The update route passes the removed-memberships set straight through, and it is empty on
        every update that only adds.
        """
        dbm = MagicMock()

        remove_member_from_documents(dbm, DB_NAME, COLLECTION, ARRAY_KEY, MEMBER_ID, [])

        assert dbm.update_many_raw.call_args.args[2] == {ARRAY_KEY: MEMBER_ID, 'public_id': {'$in': []}}


class TestClearPolymorphicRiskAssessmentReferences:
    """The three IsmsRiskAssessment fields that may hold either kind."""

    def test_covers_the_owner_the_responsible_persons_and_the_auditor(self) -> None:
        """The assessor is not among them: it can only ever be a person, never a group."""
        assert set(POLYMORPHIC_RISK_ASSESSMENT_PERSON_KEYS) == {
            RiskAssessmentKey.RISK_OWNER_ID.value,
            RiskAssessmentKey.RESPONSIBLE_PERSONS_ID.value,
            RiskAssessmentKey.AUDITOR_ID.value,
        }

    def test_nulls_each_field_only_where_its_ref_type_matches(self) -> None:
        """
        The guard that keeps a person and a group with the same public_id apart

        Both counters start at 1 and run independently, so 'person 7' and 'group 7' both exist in any
        real database; without the ref_type half of the filter, deleting one would clear the other's
        references.
        """
        dbm = MagicMock()

        clear_polymorphic_risk_assessment_references(
            dbm, DB_NAME, RA_COLLECTION, MEMBER_ID, PersonReferenceType.PERSON_GROUP,
        )

        filters: list[dict[str, Any]] = [call.args[2] for call in dbm.update_many.call_args_list]

        assert len(filters) == len(POLYMORPHIC_RISK_ASSESSMENT_PERSON_KEYS)

        for key in POLYMORPHIC_RISK_ASSESSMENT_PERSON_KEYS:
            assert {key: MEMBER_ID, f'{key}_ref_type': 'PERSON_GROUP'} in filters

    def test_writes_the_null_into_the_reference_key(self) -> None:
        """The reference is cleared, not the document: an assessment survives its owner."""
        dbm = MagicMock()

        clear_polymorphic_risk_assessment_references(
            dbm, DB_NAME, RA_COLLECTION, MEMBER_ID, PersonReferenceType.PERSON,
        )

        for call in dbm.update_many.call_args_list:
            (key,) = call.args[3].keys()

            assert call.args[3][key] is None
            assert key in POLYMORPHIC_RISK_ASSESSMENT_PERSON_KEYS

    def test_filters_with_the_plain_string_of_the_reference_type(self) -> None:
        """A BaseStrEnum member encodes as its value, and the stored documents hold plain strings."""
        dbm = MagicMock()

        clear_polymorphic_risk_assessment_references(
            dbm, DB_NAME, RA_COLLECTION, MEMBER_ID, PersonReferenceType.PERSON,
        )

        ref_types = {
            value for call in dbm.update_many.call_args_list
            for key, value in call.args[2].items() if key.endswith('_ref_type')
        }

        assert ref_types == {'PERSON'}


class TestClearControlMeasureAssignmentReference:
    """The single polymorphic field on an IsmsControlMeasureAssignment."""

    def test_nulls_the_responsible_party_only_where_its_ref_type_matches(self) -> None:
        """Same pairing rule as the assessment fields, in the collection next door."""
        dbm = MagicMock()

        clear_control_measure_assignment_reference(
            dbm, DB_NAME, CMA_COLLECTION, MEMBER_ID, PersonReferenceType.PERSON,
        )

        dbm.update_many.assert_called_once_with(
            CMA_COLLECTION,
            DB_NAME,
            {
                ControlMeasureAssignmentKey.RESPONSIBLE_FOR_IMPLEMENTATION_ID.value: MEMBER_ID,
                ControlMeasureAssignmentKey.RESPONSIBLE_FOR_IMPLEMENTATION_ID_REF_TYPE.value: 'PERSON',
            },
            {ControlMeasureAssignmentKey.RESPONSIBLE_FOR_IMPLEMENTATION_ID.value: None},
        )

    def test_sends_the_update_through_the_default_set_wrapper(self) -> None:
        """
        The fields are handed over bare, and update_many wraps them in '$set'

        The two cascades used to disagree about this - one passed a hand-built '$set' with plain=True,
        the other passed the fields - which is the kind of split that makes a later edit land in only
        one of them.
        """
        dbm = MagicMock()

        clear_control_measure_assignment_reference(
            dbm, DB_NAME, CMA_COLLECTION, MEMBER_ID, PersonReferenceType.PERSON_GROUP,
        )

        assert 'plain' not in dbm.update_many.call_args.kwargs
        assert '$set' not in dbm.update_many.call_args.args[3]


class TestPolymorphicReferenceFilter:
    """The one spelling of the id + '_ref_type' pairing."""

    def test_pairs_the_id_with_its_ref_type(self) -> None:
        """Both keys, the reference type as its plain string."""
        assert polymorphic_reference_filter('risk_owner_id', MEMBER_ID, PersonReferenceType.PERSON_GROUP) == {
            'risk_owner_id': MEMBER_ID,
            'risk_owner_id_ref_type': 'PERSON_GROUP',
        }


class TestRiskAssessmentReferenceCriteria:
    """What the delete of one person or group changes on the assessments - exactly what the clears write."""

    def test_a_person_adds_the_person_only_fields(self) -> None:
        """The assessor and the interviewed persons can only be persons, so only a person's delete reaches them."""
        clauses = risk_assessment_reference_criteria(MEMBER_ID, PersonReferenceType.PERSON)['$or']

        assert {RiskAssessmentKey.RISK_ASSESSOR_ID.value: MEMBER_ID} in clauses
        assert {RiskAssessmentKey.INTERVIEWED_PERSONS.value: MEMBER_ID} in clauses
        assert len(clauses) == len(POLYMORPHIC_RISK_ASSESSMENT_PERSON_KEYS) + 2

    def test_a_group_reaches_the_polymorphic_fields_only(self) -> None:
        """Group 3 must not select the assessments whose assessor is person 3."""
        clauses = risk_assessment_reference_criteria(MEMBER_ID, PersonReferenceType.PERSON_GROUP)['$or']

        assert clauses == [
            polymorphic_reference_filter(key, MEMBER_ID, PersonReferenceType.PERSON_GROUP)
            for key in POLYMORPHIC_RISK_ASSESSMENT_PERSON_KEYS
        ]

    def test_every_filter_the_clear_writes_is_a_clause(self) -> None:
        """Each update_many of the clear matches a subset of the criteria, so the snapshot covers its writes."""
        dbm = MagicMock()
        clear_polymorphic_risk_assessment_references(dbm, DB_NAME, RA_COLLECTION, MEMBER_ID,
                                                     PersonReferenceType.PERSON)
        clauses = risk_assessment_reference_criteria(MEMBER_ID, PersonReferenceType.PERSON)['$or']

        assert all(call.args[2] in clauses for call in dbm.update_many.call_args_list)


class TestControlMeasureAssignmentReferenceCriteria:
    """The assignment's single polymorphic reference."""

    def test_is_the_filter_the_clear_writes(self) -> None:
        """One spelling: the snapshot reads what the clear writes."""
        dbm = MagicMock()
        clear_control_measure_assignment_reference(dbm, DB_NAME, CMA_COLLECTION, MEMBER_ID,
                                                   PersonReferenceType.PERSON)

        assert dbm.update_many.call_args.args[2] == control_measure_assignment_reference_criteria(
            MEMBER_ID, PersonReferenceType.PERSON
        )
        assert dbm.update_many.call_args.args[2] == {
            ControlMeasureAssignmentKey.RESPONSIBLE_FOR_IMPLEMENTATION_ID.value: MEMBER_ID,
            ControlMeasureAssignmentKey.RESPONSIBLE_FOR_IMPLEMENTATION_ID_REF_TYPE.value: 'PERSON',
        }


class TestPersonReferenceKeys:
    """The one list of person-reference keys per collection, shared by the cascades and the write check"""

    def test_the_risk_assessment_keys_are_the_ones_the_cascade_clears(self) -> None:
        """The write check and the delete cascade read the same tuples, so they cannot drift"""
        assert RISK_ASSESSMENT_PERSON_REFERENCE_KEYS.polymorphic is POLYMORPHIC_RISK_ASSESSMENT_PERSON_KEYS
        assert RISK_ASSESSMENT_PERSON_REFERENCE_KEYS.person_only is PERSON_ONLY_RISK_ASSESSMENT_KEYS

    def test_the_risk_assessment_person_only_keys(self) -> None:
        """The assessor and the interviewed persons can only ever be persons"""
        assert set(PERSON_ONLY_RISK_ASSESSMENT_KEYS) == {
            RiskAssessmentKey.RISK_ASSESSOR_ID.value,
            RiskAssessmentKey.INTERVIEWED_PERSONS.value,
        }

    def test_the_assignment_has_one_polymorphic_key_and_no_person_only_one(self) -> None:
        """The responsible-for-implementation reference, the key its cascade clears"""
        assert CONTROL_MEASURE_ASSIGNMENT_PERSON_REFERENCE_KEYS.polymorphic == (
            ControlMeasureAssignmentKey.RESPONSIBLE_FOR_IMPLEMENTATION_ID.value,
        )
        assert CONTROL_MEASURE_ASSIGNMENT_PERSON_REFERENCE_KEYS.person_only == ()

    @pytest.mark.parametrize('key, ref_type', [
        (RiskAssessmentKey.RISK_OWNER_ID.value, RiskAssessmentKey.RISK_OWNER_ID_REF_TYPE.value),
        (RiskAssessmentKey.RESPONSIBLE_PERSONS_ID.value, RiskAssessmentKey.RESPONSIBLE_PERSONS_ID_REF_TYPE.value),
        (RiskAssessmentKey.AUDITOR_ID.value, RiskAssessmentKey.AUDITOR_ID_REF_TYPE.value),
        (ControlMeasureAssignmentKey.RESPONSIBLE_FOR_IMPLEMENTATION_ID.value,
         ControlMeasureAssignmentKey.RESPONSIBLE_FOR_IMPLEMENTATION_ID_REF_TYPE.value),
    ])
    def test_ref_type_key_spells_the_stored_sibling(self, key: str, ref_type: str) -> None:
        """Every polymorphic key's sibling, as the model's key enums name it"""
        assert ref_type_key(key) == ref_type
