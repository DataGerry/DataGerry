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
Unit tests for RiskAssessmentManager - which of the two deletes of delete_with_follow_up runs first, what each
failure becomes, the scale read of recalculate_risk_values (handed in by the caller, or read here), and the
ImpactCategory and assessed-object existence reads

Pure: the manager is a MagicMock whose two delete calls are recorded in one list, so the ORDER is asserted.
"""
from unittest.mock import MagicMock

import pytest

from cmdb.manager.isms_manager.isms_manager_helper import RiskCalculationBases
from cmdb.manager.isms_manager.risk_assessment_manager import RiskAssessmentManager
from cmdb.models.isms_model import IsmsControlMeasureAssignment, IsmsImpact, IsmsImpactCategory, IsmsLikelihood, IsmsRisk
from cmdb.models.object_group_model import CmdbObjectGroup, ObjectReferenceType
from cmdb.models.object_model import CmdbObject
from cmdb.models.isms_model.isms_control_measure_assignment_constants import ControlMeasureAssignmentKey
from cmdb.errors.manager import BaseManagerDeleteError, BaseManagerGetError
from cmdb.errors.manager.risk_assessment_manager import (
    RiskAssessmentManagerDeleteError,
    RiskAssessmentManagerRiskReadError,
    RiskAssessmentManagerScaleReadError,
)
# -------------------------------------------------------------------------------------------------------------------- #

RA_ID: int = 41


def _manager(calls: list[str]) -> MagicMock:
    """A manager recording the order of its two deletes."""
    manager = MagicMock()
    manager.delete_item.side_effect = lambda _public_id: calls.append('assessment') or True
    manager.delete_many_from_other_collection.side_effect = lambda *_a: calls.append('assignments')

    return manager


def test_the_assessment_is_deleted_before_its_assignments() -> None:
    """
    A failure between the two then leaves orphaned assignments - which readers treat as unassigned - instead of a
    surviving assessment that silently lost them
    """
    calls: list[str] = []
    manager = _manager(calls)

    assert RiskAssessmentManager.delete_with_follow_up(manager, RA_ID) is True
    assert calls == ['assessment', 'assignments']
    manager.delete_many_from_other_collection.assert_called_once_with(
        IsmsControlMeasureAssignment.COLLECTION, {ControlMeasureAssignmentKey.RISK_ASSESSMENT_ID.value: RA_ID},
    )


def test_a_failed_assessment_delete_leaves_the_assignments_alone() -> None:
    """Nothing after the failing step runs."""
    calls: list[str] = []
    manager = _manager(calls)
    failure = RiskAssessmentManagerDeleteError('delete failed')
    manager.delete_item.side_effect = failure

    with pytest.raises(RiskAssessmentManagerDeleteError) as excinfo:
        RiskAssessmentManager.delete_with_follow_up(manager, RA_ID)

    # delete_item's own typed error, not wrapped in itself again
    assert excinfo.value is failure
    manager.delete_many_from_other_collection.assert_not_called()


def test_a_failed_assignment_delete_is_the_delete_error() -> None:
    """The cross-collection delete's BaseManagerDeleteError becomes RiskAssessmentManagerDeleteError."""
    manager = _manager([])
    manager.delete_many_from_other_collection.side_effect = BaseManagerDeleteError('down')

    with pytest.raises(RiskAssessmentManagerDeleteError):
        RiskAssessmentManager.delete_with_follow_up(manager, RA_ID)


def test_a_bug_in_the_assignment_delete_propagates_as_itself() -> None:
    """A programming error is not a failed delete: it is not wrapped, so the route answers 500."""
    manager = _manager([])
    manager.delete_many_from_other_collection.side_effect = RuntimeError('bug')

    with pytest.raises(RuntimeError):
        RiskAssessmentManager.delete_with_follow_up(manager, RA_ID)


def test_a_failed_scale_read_is_the_scale_read_error() -> None:
    """load_calculation_bases reads both scales; a failed read is its own typed error"""
    manager = MagicMock()
    manager.get_many_from_other_collection.side_effect = BaseManagerGetError('down')

    with pytest.raises(RiskAssessmentManagerScaleReadError):
        RiskAssessmentManager.load_calculation_bases(manager)


def test_without_bases_the_recalculation_reads_them_itself_and_a_failure_leaves_the_payload() -> None:
    """recalculate_risk_values reads the scales when the caller hands none; the read's error propagates"""
    manager = MagicMock()
    manager.load_calculation_bases.side_effect = RiskAssessmentManagerScaleReadError('down')
    data: dict = {}

    with pytest.raises(RiskAssessmentManagerScaleReadError):
        RiskAssessmentManager.recalculate_risk_values(manager, data)

    assert not data


def test_the_answer_is_whether_the_assessment_was_deleted() -> None:
    """Not the cascade's result: a missing assessment is False even when its orphans are cleaned up."""
    manager = _manager([])
    manager.delete_item.side_effect = lambda _public_id: False

    assert RiskAssessmentManager.delete_with_follow_up(manager, RA_ID) is False


class TestGetMissingRiskIds:
    """get_missing_risk_ids - which named Risks do not exist"""

    def test_answers_the_ids_no_risk_carries(self) -> None:
        """One projected $in read"""
        manager = MagicMock()
        manager.get_many_from_other_collection.return_value = [{'public_id': 5}]

        assert RiskAssessmentManager.get_missing_risk_ids(manager, {5, 9, 3}) == {9, 3}
        manager.get_many_from_other_collection.assert_called_once_with(
            IsmsRisk.COLLECTION, projection={'public_id': 1}, criteria={'public_id': {'$in': [3, 5, 9]}},
        )

    def test_no_ids_read_nothing(self) -> None:
        """Nothing named, nothing missing"""
        manager = MagicMock()

        assert RiskAssessmentManager.get_missing_risk_ids(manager, set()) == set()
        manager.get_many_from_other_collection.assert_not_called()

    def test_a_failed_read_is_the_risk_read_error(self) -> None:
        """Its own class, mapped to its own 400 - the cause kept"""
        manager = MagicMock()
        failure = BaseManagerGetError('risks')
        manager.get_many_from_other_collection.side_effect = failure

        with pytest.raises(RiskAssessmentManagerRiskReadError) as caught:
            RiskAssessmentManager.get_missing_risk_ids(manager, {5})

        assert caught.value.args[0] is failure


IMPACT_LOW: int = 21
IMPACT_HIGH: int = 22
LIKELIHOOD: int = 31
BASIS_LOW: float = 1.0
BASIS_HIGH: float = 3.0
BASIS_LIKELIHOOD: float = 2.0
CATEGORY_STORED: int = 11
CATEGORY_MISSING: int = 19


class TestLoadCalculationBases:
    """load_calculation_bases - both scales, one projected read each"""

    def test_reads_both_scales(self) -> None:
        """public_id -> calculation_basis per scale"""
        manager = MagicMock()
        manager.get_many_from_other_collection.side_effect = lambda collection, **_kwargs: {
            IsmsImpact.COLLECTION: [{'public_id': IMPACT_LOW, 'calculation_basis': BASIS_LOW}],
            IsmsLikelihood.COLLECTION: [{'public_id': LIKELIHOOD, 'calculation_basis': BASIS_LIKELIHOOD}],
        }[collection]

        assert RiskAssessmentManager.load_calculation_bases(manager) == RiskCalculationBases(
            impact={IMPACT_LOW: BASIS_LOW}, likelihood={LIKELIHOOD: BASIS_LIKELIHOOD},
        )
        assert manager.get_many_from_other_collection.call_count == len(RiskCalculationBases._fields)

    def test_the_cause_is_kept(self) -> None:
        """Wrapped, not stringified"""
        manager = MagicMock()
        failure = BaseManagerGetError('down')
        manager.get_many_from_other_collection.side_effect = failure

        with pytest.raises(RiskAssessmentManagerScaleReadError) as raised:
            RiskAssessmentManager.load_calculation_bases(manager)

        assert raised.value.__cause__ is failure


class TestRecalculateWithHandedBases:
    """recalculate_risk_values with the scales the caller already read"""

    def test_derives_from_the_handed_bases_without_a_read(self) -> None:
        """The scales are read once per write"""
        manager = MagicMock()
        bases = RiskCalculationBases(impact={IMPACT_LOW: BASIS_LOW, IMPACT_HIGH: BASIS_HIGH},
                                     likelihood={LIKELIHOOD: BASIS_LIKELIHOOD})
        data: dict = {
            'risk_calculation_before': {
                'impacts': [{'impact_category_id': CATEGORY_STORED, 'impact_id': IMPACT_HIGH},
                            {'impact_category_id': CATEGORY_MISSING, 'impact_id': IMPACT_LOW}],
                'likelihood_id': LIKELIHOOD,
            },
            'risk_calculation_after': {'impacts': [], 'likelihood_id': None},
        }

        RiskAssessmentManager.recalculate_risk_values(manager, data, bases)

        before: dict = data['risk_calculation_before']
        assert (before['maximum_impact_id'], before['maximum_impact_value'], before['likelihood_value']) == (
            IMPACT_HIGH, BASIS_HIGH, BASIS_LIKELIHOOD,
        )
        assert (data['risk_calculation_after']['maximum_impact_id'],
                data['risk_calculation_after']['likelihood_value']) == (None, None)
        manager.load_calculation_bases.assert_not_called()


class TestGetMissingImpactCategoryIds:
    """get_missing_impact_category_ids - which named ImpactCategories do not exist"""

    def test_answers_the_ids_no_category_carries(self) -> None:
        """One projected $in read"""
        manager = MagicMock()
        manager.get_many_from_other_collection.return_value = [{'public_id': CATEGORY_STORED}]

        assert RiskAssessmentManager.get_missing_impact_category_ids(
            manager, {CATEGORY_STORED, CATEGORY_MISSING},
        ) == {CATEGORY_MISSING}
        manager.get_many_from_other_collection.assert_called_once_with(
            IsmsImpactCategory.COLLECTION, projection={'public_id': 1},
            criteria={'public_id': {'$in': [CATEGORY_STORED, CATEGORY_MISSING]}},
        )

    def test_no_ids_read_nothing(self) -> None:
        """Nothing named, nothing missing"""
        manager = MagicMock()

        assert RiskAssessmentManager.get_missing_impact_category_ids(manager, set()) == set()
        manager.get_many_from_other_collection.assert_not_called()

    def test_a_failed_read_propagates_as_the_base_error(self) -> None:
        """The route helper answers it with its own 400"""
        manager = MagicMock()
        manager.get_many_from_other_collection.side_effect = BaseManagerGetError('down')

        with pytest.raises(BaseManagerGetError):
            RiskAssessmentManager.get_missing_impact_category_ids(manager, {CATEGORY_STORED})


ASSESSED_ID: int = 51
MISSING_ASSESSED_ID: int = 59
DENIED_TYPE_IDS: list[int] = [62, 61]


class TestGetMissingAssessedIds:
    """get_missing_assessed_ids - the assessed objects / groups not there for the caller"""

    def test_an_object_read_leaves_out_the_denied_types(self) -> None:
        """A hidden object is not in the answer of the read, so it counts as missing"""
        manager = MagicMock()
        manager.get_many_from_other_collection.return_value = [{'public_id': ASSESSED_ID}]

        assert RiskAssessmentManager.get_missing_assessed_ids(
            manager, ObjectReferenceType.OBJECT, {ASSESSED_ID, MISSING_ASSESSED_ID}, DENIED_TYPE_IDS,
        ) == {MISSING_ASSESSED_ID}
        manager.get_many_from_other_collection.assert_called_once_with(
            CmdbObject.COLLECTION, projection={'public_id': 1},
            criteria={'public_id': {'$in': [ASSESSED_ID, MISSING_ASSESSED_ID]}, 'type_id': {'$nin': [61, 62]}},
        )

    def test_nothing_denied_is_no_type_clause(self) -> None:
        """The common case"""
        manager = MagicMock()
        manager.get_many_from_other_collection.return_value = []

        RiskAssessmentManager.get_missing_assessed_ids(manager, ObjectReferenceType.OBJECT, {ASSESSED_ID}, [])

        assert manager.get_many_from_other_collection.call_args.kwargs['criteria'] == {
            'public_id': {'$in': [ASSESSED_ID]},
        }

    def test_a_group_is_judged_by_existence_alone(self) -> None:
        """The denied types are ignored"""
        manager = MagicMock()
        manager.get_many_from_other_collection.return_value = []

        assert RiskAssessmentManager.get_missing_assessed_ids(
            manager, ObjectReferenceType.OBJECT_GROUP, {ASSESSED_ID}, DENIED_TYPE_IDS,
        ) == {ASSESSED_ID}
        manager.get_many_from_other_collection.assert_called_once_with(
            CmdbObjectGroup.COLLECTION, projection={'public_id': 1}, criteria={'public_id': {'$in': [ASSESSED_ID]}},
        )

    def test_no_ids_read_nothing(self) -> None:
        """Nothing named"""
        manager = MagicMock()

        assert RiskAssessmentManager.get_missing_assessed_ids(
            manager, ObjectReferenceType.OBJECT, set(), DENIED_TYPE_IDS,
        ) == set()
        manager.get_many_from_other_collection.assert_not_called()

    def test_a_failed_read_propagates_as_the_base_error(self) -> None:
        """The route helper answers it"""
        manager = MagicMock()
        manager.get_many_from_other_collection.side_effect = BaseManagerGetError('down')

        with pytest.raises(BaseManagerGetError):
            RiskAssessmentManager.get_missing_assessed_ids(manager, ObjectReferenceType.OBJECT, {ASSESSED_ID}, [])
