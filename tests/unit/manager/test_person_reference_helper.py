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

Pure tests: no Mongo. Persons and person groups are CmdbObjects of the PERSON / PERSON_GROUP SpecialTypes, so
what is left of the module is:

  - the key lists (``PersonReferenceKeys``) the ISMS write check and the delete cleanup share
  - ``ref_type_key``, the spelling of a polymorphic key's '_ref_type' sibling
  - ``clear_object_person_references``, run from the object delete path: object ids are unique across all
    objects, so the id alone names the deleted object and the clears need **no** '_ref_type' filter. An empty
    id list writes NOTHING, rather than issuing a query matching every document
"""
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.manager.person_reference_helper import (
    CONTROL_MEASURE_ASSIGNMENT_PERSON_REFERENCE_KEYS,
    PERSON_ONLY_RISK_ASSESSMENT_KEYS,
    POLYMORPHIC_RISK_ASSESSMENT_PERSON_KEYS,
    RISK_ASSESSMENT_PERSON_REFERENCE_KEYS,
    clear_object_person_references,
    ref_type_key,
)
from cmdb.models.isms_model.isms_control_measure_assignment_constants import ControlMeasureAssignmentKey
from cmdb.models.isms_model.isms_risk_assessment_constants import RiskAssessmentKey
# -------------------------------------------------------------------------------------------------------------------- #

DB_NAME: str = 'testdb'
RA_COLLECTION: str = 'isms.riskAssessment'
CMA_COLLECTION: str = 'isms.controlMeasureAssignment'
IDS_FILTER: dict[str, Any] = {'$in': [7, 8]}


def _clear(dbm: MagicMock, ids: list[int]) -> None:
    clear_object_person_references(dbm, DB_NAME, RA_COLLECTION, CMA_COLLECTION, ids)


class TestClearObjectPersonReferences:
    """The ISMS cleanup the object delete path runs for every deleted object"""

    def test_an_empty_id_list_writes_nothing(self) -> None:
        """An '$in: []' would match nothing anyway, but no write is the stronger guarantee"""
        dbm = MagicMock()

        _clear(dbm, [])

        dbm.update_many.assert_not_called()
        dbm.update_many_raw.assert_not_called()

    def test_nulls_every_scalar_risk_assessment_reference(self) -> None:
        """The three polymorphic keys and the assessor, each matched by the bare id"""
        dbm = MagicMock()

        _clear(dbm, [7, 8])

        risk_assessment_calls = [
            call.args for call in dbm.update_many.call_args_list if call.args[0] == RA_COLLECTION
        ]
        expected_keys: list[str] = [*POLYMORPHIC_RISK_ASSESSMENT_PERSON_KEYS, RiskAssessmentKey.RISK_ASSESSOR_ID.value]

        assert risk_assessment_calls == [
            (RA_COLLECTION, DB_NAME, {key: IDS_FILTER}, {key: None}) for key in expected_keys
        ]

    def test_no_clear_filters_on_the_ref_type(self) -> None:
        """Object ids are unique, so a '_ref_type' clause would only make a stale reference survive"""
        dbm = MagicMock()

        _clear(dbm, [7, 8])

        for call in dbm.update_many.call_args_list + dbm.update_many_raw.call_args_list:
            criteria: dict[str, Any] = call.args[2]
            assert not any(key.endswith('_ref_type') for key in criteria)

    def test_pulls_the_ids_out_of_the_interviewed_persons(self) -> None:
        """A list key is not nulled: the deleted persons are pulled, the others stay"""
        dbm = MagicMock()

        _clear(dbm, [7, 8])

        key: str = RiskAssessmentKey.INTERVIEWED_PERSONS.value
        dbm.update_many_raw.assert_called_once_with(
            RA_COLLECTION, DB_NAME, {key: IDS_FILTER}, {'$pull': {key: IDS_FILTER}},
        )

    def test_nulls_the_responsible_party_of_an_assignment(self) -> None:
        """The control measure assignment's one polymorphic key"""
        dbm = MagicMock()

        _clear(dbm, [7, 8])

        key: str = ControlMeasureAssignmentKey.RESPONSIBLE_FOR_IMPLEMENTATION_ID.value
        assert (CMA_COLLECTION, DB_NAME, {key: IDS_FILTER}, {key: None}) in [
            call.args for call in dbm.update_many.call_args_list
        ]

    def test_clears_exactly_the_keys_the_write_check_judges(self) -> None:
        """Every key of the shared lists is written by the cleanup, and no other"""
        dbm = MagicMock()

        _clear(dbm, [7])

        written: set[str] = {
            key for call in dbm.update_many.call_args_list + dbm.update_many_raw.call_args_list
            for key in call.args[2]
        }

        assert written == {
            *RISK_ASSESSMENT_PERSON_REFERENCE_KEYS.polymorphic,
            *RISK_ASSESSMENT_PERSON_REFERENCE_KEYS.person_only,
            *CONTROL_MEASURE_ASSIGNMENT_PERSON_REFERENCE_KEYS.polymorphic,
        }

    def test_one_write_per_key_however_many_ids(self) -> None:
        """Bulk writes: the number of calls does not grow with the number of deleted objects"""
        few, many = MagicMock(), MagicMock()

        _clear(few, [1])
        _clear(many, list(range(1, 200)))

        assert few.update_many.call_count == many.update_many.call_count
        assert few.update_many_raw.call_count == many.update_many_raw.call_count


class TestPersonReferenceKeys:
    """The one list of person-reference keys per collection, shared by the cleanup and the write check"""

    def test_the_risk_assessment_keys_are_the_module_tuples(self) -> None:
        """The write check and the delete cleanup read the same tuples, so they cannot drift"""
        assert RISK_ASSESSMENT_PERSON_REFERENCE_KEYS.polymorphic is POLYMORPHIC_RISK_ASSESSMENT_PERSON_KEYS
        assert RISK_ASSESSMENT_PERSON_REFERENCE_KEYS.person_only is PERSON_ONLY_RISK_ASSESSMENT_KEYS

    def test_the_polymorphic_risk_assessment_keys(self) -> None:
        """The owner, the responsible persons and the auditor can each be a person or a group"""
        assert set(POLYMORPHIC_RISK_ASSESSMENT_PERSON_KEYS) == {
            RiskAssessmentKey.RISK_OWNER_ID.value,
            RiskAssessmentKey.RESPONSIBLE_PERSONS_ID.value,
            RiskAssessmentKey.AUDITOR_ID.value,
        }

    def test_the_risk_assessment_person_only_keys(self) -> None:
        """The assessor and the interviewed persons can only ever be persons"""
        assert set(PERSON_ONLY_RISK_ASSESSMENT_KEYS) == {
            RiskAssessmentKey.RISK_ASSESSOR_ID.value,
            RiskAssessmentKey.INTERVIEWED_PERSONS.value,
        }

    def test_the_assignment_has_one_polymorphic_key_and_no_person_only_one(self) -> None:
        """The responsible-for-implementation reference"""
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
