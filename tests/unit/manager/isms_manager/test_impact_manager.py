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
Unit tests for cmdb.manager.isms_manager.impact_manager.ImpactManager

Pure tests: the manager's own methods run against a ``MagicMock(spec=ImpactManager)`` whose database
methods are stubbed. Pinned: the update records both of its writes in the ledger (the Impact with its stored
snapshot, the propagation BEFORE it runs), the propagation reads only the paths it needs and rewrites only the
maximum impact, every typed failure becomes the manager's own error and a programming error propagates as
itself, and the calculation-basis check answers its own error class.
"""
# pylint: disable=protected-access
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.framework.write_ledger import WriteLedger
from cmdb.manager.base_manager import BaseManager
from cmdb.framework.write_ledger_constants import WriteKind
from cmdb.manager.isms_manager.impact_manager import MAXIMUM_IMPACT_PATHS, ImpactManager
from cmdb.models.isms_model import IsmsImpact, IsmsRiskAssessment

from cmdb.errors.manager import BaseManagerGetError, BaseManagerUpdateError
from cmdb.errors.manager.impact_manager import (
    IMPACT_MANAGER_ERRORS,
    ImpactManagerAssessmentUsageError,
    ImpactManagerCalculationBasisError,
    ImpactManagerGetError,
    ImpactManagerUpdateError,
)
# -------------------------------------------------------------------------------------------------------------------- #

IMPACT_ID: int = 3
OTHER_IMPACT_ID: int = 4
RA_ID: int = 51
OLD_BASIS: float = 2.0
NEW_BASIS: float = 5.0
OTHER_BASIS: float = 3.0
DB_NAME: str = 'isms-db'


def _impact(basis: float) -> dict[str, Any]:
    """An IsmsImpact document"""
    return {'public_id': IMPACT_ID, 'name': 'High', 'calculation_basis': basis, 'description': None}


def _assessment() -> dict[str, Any]:
    """A RiskAssessment naming both Impacts in its before matrix, none in its after matrix"""
    return {
        'public_id': RA_ID,
        'risk_calculation_before': {
            'impacts': [{'impact_id': IMPACT_ID}, {'impact_id': OTHER_IMPACT_ID}],
            'maximum_impact_id': OTHER_IMPACT_ID,
            'maximum_impact_value': OTHER_BASIS,
        },
        'risk_calculation_after': {'impacts': [], 'maximum_impact_id': None, 'maximum_impact_value': None},
    }


def _manager(affected: list[dict[str, Any]] | None = None) -> MagicMock:
    """An ImpactManager whose Impact is stored and whose RiskAssessment read answers ``affected``"""
    mgr = MagicMock(spec=ImpactManager)
    mgr.exceptions = IMPACT_MANAGER_ERRORS
    mgr.db_name = DB_NAME
    mgr.dbm = MagicMock(name='dbm')
    mgr.get_item.return_value = _impact(OLD_BASIS)
    mgr.impact_reference_query = ImpactManager.impact_reference_query
    mgr.max_impact_operations = ImpactManager.max_impact_operations
    mgr._propagate_calculation_basis = lambda *args: ImpactManager._propagate_calculation_basis(mgr, *args)
    # The real write wrapper, so the database layer's call is what the tests read
    mgr.bulk_write.side_effect = lambda *args, **kwargs: BaseManager.bulk_write(mgr, *args, **kwargs)

    def read(collection: str, **_kwargs: Any) -> list[dict[str, Any]]:
        if collection == IsmsRiskAssessment.COLLECTION:
            return [_assessment()] if affected is None else affected

        return [{'public_id': IMPACT_ID, 'calculation_basis': OLD_BASIS},
                {'public_id': OTHER_IMPACT_ID, 'calculation_basis': OTHER_BASIS}]

    mgr.get_many_from_other_collection.side_effect = read

    return mgr


class TestUpdateWithFollowUp:
    """The Impact and the RiskAssessments using it - two writes, both in the ledger."""

    def test_both_writes_are_recorded_and_the_maximum_recomputed(self) -> None:
        """The update with its snapshot, then the compensated propagation; the new maximum is the Impact."""
        mgr = _manager()
        ledger = WriteLedger()

        stored = ImpactManager.update_with_follow_up(mgr, IMPACT_ID, _impact(NEW_BASIS), ledger)

        assert stored['calculation_basis'] == NEW_BASIS
        kinds = [entry.kind for entry in ledger.entries]
        assert kinds == [WriteKind.UPDATE, WriteKind.COMPENSATED]
        assert ledger.entries[0].prior == _impact(OLD_BASIS)

        collection, db_name, operations = mgr.dbm.bulk_write.call_args.args
        assert (collection, db_name) == (IsmsRiskAssessment.COLLECTION, DB_NAME)
        assert operations[0]._doc['$set'] == {  # pylint: disable=protected-access
            'risk_calculation_before.maximum_impact_id': IMPACT_ID,
            'risk_calculation_before.maximum_impact_value': NEW_BASIS,
            'risk_calculation_after.maximum_impact_id': None,
            'risk_calculation_after.maximum_impact_value': None,
        }

    def test_the_read_is_projected_to_the_matrices(self) -> None:
        """Only the impact lists and the maximum fields of both matrices, filtered to the Impact's users."""
        mgr = _manager()

        ImpactManager.update_with_follow_up(mgr, IMPACT_ID, _impact(NEW_BASIS), WriteLedger())

        call = mgr.get_many_from_other_collection.call_args_list[0]
        assert set(call.kwargs['projection']) == {
            'public_id', '_id', 'risk_calculation_before.impacts', 'risk_calculation_after.impacts',
            *MAXIMUM_IMPACT_PATHS,
        }
        assert call.kwargs['criteria'] == ImpactManager.impact_reference_query(IMPACT_ID)

    def test_no_affected_assessment_writes_and_records_nothing_more(self) -> None:
        """Only the Impact's own update."""
        mgr = _manager(affected=[])
        ledger = WriteLedger()

        ImpactManager.update_with_follow_up(mgr, IMPACT_ID, _impact(NEW_BASIS), ledger)

        mgr.dbm.bulk_write.assert_not_called()
        assert [entry.kind for entry in ledger.entries] == [WriteKind.UPDATE]

    def test_a_missing_impact_is_the_update_error(self) -> None:
        """Nothing is written for an Impact that is gone."""
        mgr = _manager()
        mgr.get_item.return_value = None

        with pytest.raises(ImpactManagerUpdateError):
            ImpactManager.update_with_follow_up(mgr, IMPACT_ID, _impact(NEW_BASIS), WriteLedger())

        mgr.update_item.assert_not_called()

    @pytest.mark.parametrize('error', [BaseManagerGetError('down'), BaseManagerUpdateError('down')],
                             ids=['read', 'write'])
    def test_a_failed_propagation_is_the_update_error(self, error: Exception) -> None:
        """A typed failure of the RiskAssessment read or write; the Impact update stays in the ledger."""
        mgr = _manager()
        mgr.get_many_from_other_collection.side_effect = error
        ledger = WriteLedger()

        with pytest.raises(ImpactManagerUpdateError) as excinfo:
            ImpactManager.update_with_follow_up(mgr, IMPACT_ID, _impact(NEW_BASIS), ledger)

        assert excinfo.value.args[0] is error
        assert [entry.kind for entry in ledger.entries] == [WriteKind.UPDATE]

    def test_data_the_model_cannot_read_is_the_update_error(self) -> None:
        """A document missing a required key is refused before anything is written; the model's error is kept."""
        mgr = _manager()
        unreadable: dict[str, Any] = _impact(NEW_BASIS)
        del unreadable['name']

        with pytest.raises(ImpactManagerUpdateError) as excinfo:
            ImpactManager.update_with_follow_up(mgr, IMPACT_ID, unreadable, WriteLedger())

        assert isinstance(excinfo.value.args[0], IsmsImpact.INIT_FROM_DATA_ERROR)
        mgr.update_item.assert_not_called()

    def test_a_bug_in_the_propagation_propagates_as_itself(self) -> None:
        """A programming error is not a failed update."""
        mgr = _manager()
        mgr.get_many_from_other_collection.side_effect = RuntimeError('bug')

        with pytest.raises(RuntimeError):
            ImpactManager.update_with_follow_up(mgr, IMPACT_ID, _impact(NEW_BASIS), WriteLedger())

    def test_a_failed_stored_read_is_the_get_error(self) -> None:
        """get_item's own typed error passes through; nothing is written."""
        mgr = _manager()
        mgr.get_item.side_effect = ImpactManagerGetError('down')

        with pytest.raises(ImpactManagerGetError):
            ImpactManager.update_with_follow_up(mgr, IMPACT_ID, _impact(NEW_BASIS), WriteLedger())

        mgr.update_item.assert_not_called()


class TestCalculationBasisExists:
    """The readable half of the uniqueness rule."""

    @pytest.mark.parametrize('stored, expected', [({'public_id': IMPACT_ID}, True), (None, False)])
    def test_answers_whether_an_impact_holds_the_basis(self, stored: dict | None, expected: bool) -> None:
        """Asked by the basis itself."""
        mgr = _manager()
        mgr.get_one_by.return_value = stored

        assert ImpactManager.impact_calculation_basis_exists(mgr, NEW_BASIS) is expected
        mgr.get_one_by.assert_called_once_with({'calculation_basis': NEW_BASIS})

    def test_a_failed_read_is_its_own_error_class(self) -> None:
        """CalculationBasisError - a GetError, so the route can name the check, not the created Impact."""
        mgr = _manager()
        mgr.get_one_by.side_effect = BaseManagerGetError('down')

        with pytest.raises(ImpactManagerCalculationBasisError) as excinfo:
            ImpactManager.impact_calculation_basis_exists(mgr, NEW_BASIS)

        assert isinstance(excinfo.value, ImpactManagerGetError)

    def test_a_bug_propagates_as_itself(self) -> None:
        """Not wrapped."""
        mgr = _manager()
        mgr.get_one_by.side_effect = RuntimeError('bug')

        with pytest.raises(RuntimeError):
            ImpactManager.impact_calculation_basis_exists(mgr, NEW_BASIS)


class TestDeleteIfUnused:
    """An Impact a RiskAssessment uses is refused."""

    def test_a_used_impact_is_refused(self) -> None:
        """The usage error, nothing deleted."""
        mgr = _manager()
        mgr.collection = 'isms.impact'
        mgr.is_impact_used.return_value = True

        with pytest.raises(ImpactManagerAssessmentUsageError):
            ImpactManager.delete_if_unused(mgr, IMPACT_ID)

        mgr.find_one_and_delete.assert_not_called()

    def test_an_unused_impact_is_deleted(self) -> None:
        """One atomic delete."""
        mgr = _manager()
        mgr.is_impact_used.return_value = False
        mgr.find_one_and_delete.return_value = _impact(OLD_BASIS)

        assert ImpactManager.delete_if_unused(mgr, IMPACT_ID) is True
