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
Unit tests for cmdb.manager.isms_manager.likelihood_manager.LikelihoodManager

Pure tests: the manager's own methods run against a ``MagicMock(spec=LikelihoodManager)`` whose database
methods are stubbed. Pinned: the reference query and the update pipeline name both matrices through the
enums, the update records both of its writes in the ledger (the Likelihood with its stored snapshot, the
likelihood values BEFORE they are rewritten), typed failures become the manager's own errors and a programming
error propagates as itself, and the calculation-basis check answers its own error class.
"""
# pylint: disable=protected-access
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.framework.write_ledger import WriteLedger
from cmdb.manager.base_manager import BaseManager
from cmdb.framework.write_ledger_constants import WriteKind
from cmdb.manager.isms_manager.likelihood_manager import LIKELIHOOD_VALUE_PATHS, LikelihoodManager
from cmdb.models.isms_model import IsmsLikelihood, IsmsRiskAssessment

from cmdb.errors.manager import BaseManagerGetError, BaseManagerUpdateError
from cmdb.errors.manager.likelihood_manager import (
    LIKELIHOOD_MANAGER_ERRORS,
    LikelihoodManagerAssessmentUsageError,
    LikelihoodManagerCalculationBasisError,
    LikelihoodManagerGetError,
    LikelihoodManagerUpdateError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LIKELIHOOD_ID: int = 6
RA_ID: int = 61
OLD_BASIS: float = 1.5
NEW_BASIS: float = 4.5
DB_NAME: str = 'isms-db'


def _likelihood(basis: float) -> dict[str, Any]:
    """An IsmsLikelihood document"""
    return {'public_id': LIKELIHOOD_ID, 'name': 'Often', 'calculation_basis': basis, 'description': None}


def _manager(affected: list[dict[str, Any]] | None = None) -> MagicMock:
    """A LikelihoodManager whose Likelihood is stored and whose RiskAssessment read answers ``affected``"""
    mgr = MagicMock(spec=LikelihoodManager)
    mgr.exceptions = LIKELIHOOD_MANAGER_ERRORS
    mgr.db_name = DB_NAME
    mgr.dbm = MagicMock(name='dbm')
    mgr.get_item.return_value = _likelihood(OLD_BASIS)
    mgr.likelihood_reference_query = LikelihoodManager.likelihood_reference_query
    mgr.likelihood_value_pipeline = LikelihoodManager.likelihood_value_pipeline
    mgr._propagate_calculation_basis = lambda *args: LikelihoodManager._propagate_calculation_basis(mgr, *args)
    # The real write wrapper, so the database layer's call is what the tests read
    mgr.update_many_raw.side_effect = lambda *args, **kwargs: BaseManager.update_many_raw(mgr, *args, **kwargs)
    mgr.get_many_from_other_collection.return_value = (
        [{'public_id': RA_ID, 'risk_calculation_before': {'likelihood_value': OLD_BASIS}}]
        if affected is None else affected
    )

    return mgr


class TestQueries:
    """The reference query and the update pipeline cover both matrices."""

    def test_the_reference_query_names_both_matrices(self) -> None:
        """An $or over the likelihood_id of before and after."""
        assert LikelihoodManager.likelihood_reference_query(LIKELIHOOD_ID) == {'$or': [
            {'risk_calculation_before.likelihood_id': LIKELIHOOD_ID},
            {'risk_calculation_after.likelihood_id': LIKELIHOOD_ID},
        ]}

    def test_the_pipeline_rewrites_only_matching_matrices(self) -> None:
        """Each matrix keeps its value unless it names the Likelihood."""
        [stage] = LikelihoodManager.likelihood_value_pipeline(LIKELIHOOD_ID, NEW_BASIS)

        assert stage == {'$set': {
            'risk_calculation_before.likelihood_value': {'$cond': [
                {'$eq': ['$risk_calculation_before.likelihood_id', LIKELIHOOD_ID]},
                NEW_BASIS,
                '$risk_calculation_before.likelihood_value',
            ]},
            'risk_calculation_after.likelihood_value': {'$cond': [
                {'$eq': ['$risk_calculation_after.likelihood_id', LIKELIHOOD_ID]},
                NEW_BASIS,
                '$risk_calculation_after.likelihood_value',
            ]},
        }}


class TestUpdateWithFollowUp:
    """The Likelihood and the RiskAssessments naming it - two writes, both in the ledger."""

    def test_both_writes_are_recorded_and_the_values_rewritten(self) -> None:
        """The update with its snapshot, then the compensated propagation, then the pipeline update."""
        mgr = _manager()
        ledger = WriteLedger()

        stored = LikelihoodManager.update_with_follow_up(mgr, LIKELIHOOD_ID, _likelihood(NEW_BASIS), ledger)

        assert stored['calculation_basis'] == NEW_BASIS
        assert [entry.kind for entry in ledger.entries] == [WriteKind.UPDATE, WriteKind.COMPENSATED]
        assert ledger.entries[0].prior == _likelihood(OLD_BASIS)
        kwargs = mgr.dbm.update_many_raw.call_args.kwargs
        assert kwargs['collection'] == IsmsRiskAssessment.COLLECTION
        assert kwargs['db_name'] == DB_NAME
        assert kwargs['filter_query'] == LikelihoodManager.likelihood_reference_query(LIKELIHOOD_ID)
        assert kwargs['update'] == LikelihoodManager.likelihood_value_pipeline(LIKELIHOOD_ID, NEW_BASIS)

    def test_the_snapshot_reads_only_the_values(self) -> None:
        """Projected to the two likelihood values."""
        mgr = _manager()

        LikelihoodManager.update_with_follow_up(mgr, LIKELIHOOD_ID, _likelihood(NEW_BASIS), WriteLedger())

        projection = mgr.get_many_from_other_collection.call_args.kwargs['projection']
        assert set(projection) == {'public_id', '_id', *LIKELIHOOD_VALUE_PATHS}

    def test_no_affected_assessment_runs_no_update(self) -> None:
        """Only the Likelihood's own update."""
        mgr = _manager(affected=[])
        ledger = WriteLedger()

        LikelihoodManager.update_with_follow_up(mgr, LIKELIHOOD_ID, _likelihood(NEW_BASIS), ledger)

        mgr.dbm.update_many_raw.assert_not_called()
        assert [entry.kind for entry in ledger.entries] == [WriteKind.UPDATE]

    @pytest.mark.parametrize('error', [BaseManagerGetError('down'), BaseManagerUpdateError('down')],
                             ids=['read', 'write'])
    def test_a_failed_propagation_is_the_update_error(self, error: Exception) -> None:
        """A typed failure of the RiskAssessment read or write."""
        mgr = _manager()
        mgr.get_many_from_other_collection.side_effect = error

        with pytest.raises(LikelihoodManagerUpdateError) as excinfo:
            LikelihoodManager.update_with_follow_up(mgr, LIKELIHOOD_ID, _likelihood(NEW_BASIS), WriteLedger())

        assert excinfo.value.args[0] is error

    def test_data_the_model_cannot_read_is_the_update_error(self) -> None:
        """A document missing a required key is refused before anything is written; the model's error is kept."""
        mgr = _manager()
        unreadable: dict[str, Any] = _likelihood(NEW_BASIS)
        del unreadable['name']

        with pytest.raises(LikelihoodManagerUpdateError) as excinfo:
            LikelihoodManager.update_with_follow_up(mgr, LIKELIHOOD_ID, unreadable, WriteLedger())

        assert isinstance(excinfo.value.args[0], IsmsLikelihood.INIT_FROM_DATA_ERROR)
        mgr.update_item.assert_not_called()

    def test_a_bug_in_the_propagation_propagates_as_itself(self) -> None:
        """A programming error is not a failed update."""
        mgr = _manager()
        mgr.get_many_from_other_collection.side_effect = RuntimeError('bug')

        with pytest.raises(RuntimeError):
            LikelihoodManager.update_with_follow_up(mgr, LIKELIHOOD_ID, _likelihood(NEW_BASIS), WriteLedger())

    def test_a_missing_likelihood_is_the_update_error(self) -> None:
        """Nothing is written for a Likelihood that is gone."""
        mgr = _manager()
        mgr.get_item.return_value = None

        with pytest.raises(LikelihoodManagerUpdateError):
            LikelihoodManager.update_with_follow_up(mgr, LIKELIHOOD_ID, _likelihood(NEW_BASIS), WriteLedger())

        mgr.update_item.assert_not_called()


class TestCalculationBasisExists:
    """The readable half of the uniqueness rule."""

    def test_a_failed_read_is_its_own_error_class(self) -> None:
        """CalculationBasisError - a GetError."""
        mgr = _manager()
        mgr.get_one_by.side_effect = BaseManagerGetError('down')

        with pytest.raises(LikelihoodManagerCalculationBasisError) as excinfo:
            LikelihoodManager.likelihood_calculation_basis_exists(mgr, NEW_BASIS)

        assert isinstance(excinfo.value, LikelihoodManagerGetError)

    def test_a_bug_propagates_as_itself(self) -> None:
        """Not wrapped."""
        mgr = _manager()
        mgr.get_one_by.side_effect = RuntimeError('bug')

        with pytest.raises(RuntimeError):
            LikelihoodManager.likelihood_calculation_basis_exists(mgr, NEW_BASIS)


class TestDeleteIfUnused:
    """A Likelihood a RiskAssessment uses is refused."""

    def test_a_used_likelihood_is_refused(self) -> None:
        """The usage error, nothing deleted."""
        mgr = _manager()
        mgr.collection = 'isms.likelihood'
        mgr.is_likelihood_used.return_value = True

        with pytest.raises(LikelihoodManagerAssessmentUsageError):
            LikelihoodManager.delete_if_unused(mgr, LIKELIHOOD_ID)

        mgr.find_one_and_delete.assert_not_called()
