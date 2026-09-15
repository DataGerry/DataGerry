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
"""
from typing import Any
from unittest.mock import MagicMock

from cmdb.manager.person_reference_helper import (
    POLYMORPHIC_RISK_ASSESSMENT_PERSON_KEYS,
    add_member_to_documents,
    clear_control_measure_assignment_reference,
    clear_polymorphic_risk_assessment_references,
    remove_member_from_documents,
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

        dbm.update_many_pull.assert_called_once_with(
            COLLECTION,
            DB_NAME,
            {ARRAY_KEY: MEMBER_ID, 'public_id': {'$in': [10]}},
            {ARRAY_KEY: MEMBER_ID},
        )

    def test_reaches_every_listing_document_when_none_are_named(self) -> None:
        """
        What a deletion needs: the member is gone, so no document may keep listing them

        The absence of a selection is the instruction here, which is why it is None rather than an
        empty list - the two mean opposite things in this function.
        """
        dbm = MagicMock()

        remove_member_from_documents(dbm, DB_NAME, COLLECTION, ARRAY_KEY, MEMBER_ID)

        dbm.update_many_pull.assert_called_once_with(
            COLLECTION,
            DB_NAME,
            {ARRAY_KEY: MEMBER_ID},
            {ARRAY_KEY: MEMBER_ID},
        )

    def test_an_empty_selection_pulls_from_nothing(self) -> None:
        """
        An empty list is a selection of no documents, and must not be read as 'all of them'

        The update route passes the removed-memberships set straight through, and it is empty on
        every update that only adds.
        """
        dbm = MagicMock()

        remove_member_from_documents(dbm, DB_NAME, COLLECTION, ARRAY_KEY, MEMBER_ID, [])

        assert dbm.update_many_pull.call_args.args[2] == {ARRAY_KEY: MEMBER_ID, 'public_id': {'$in': []}}


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
