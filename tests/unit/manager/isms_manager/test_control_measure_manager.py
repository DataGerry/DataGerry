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
Unit tests for cmdb.manager.isms_manager.control_measure_manager.ControlMeasureManager

Pure tests: no Mongo. The manager is driven against a ``MagicMock(spec=ControlMeasureManager)`` with
its cross-collection database collaborator (aggregate_all) stubbed, so only the
manager's own behavior is exercised - the grouped ``$in`` pipeline shape, the empty-input short
circuit, the error-wrapping into the ControlMeasureManager error hierarchy (and nothing but the
aggregation's own error: a bug propagates as itself), and the delete-if-unused refusal. The aggregation
itself is exercised against real MongoDB by the integration tier.
"""
from unittest.mock import MagicMock

import pytest
from pymongo import UpdateOne

from cmdb.manager.isms_manager.control_measure_manager import ControlMeasureManager
from cmdb.models.isms_model import IsmsControlMeasure, IsmsControlMeasureAssignment

from cmdb.errors.manager import BaseManagerGetError, BaseManagerIterationError, BaseManagerUpdateError
from cmdb.errors.manager.control_measure_manager import (
    CONTROL_MEASURE_MANAGER_ERRORS,
    ControlMeasureManagerAssignmentUsageError,
    ControlMeasureManagerDeleteError,
    ControlMeasureManagerGetError,
    ControlMeasureManagerIterationError,
    ControlMeasureManagerUpdateError,
)
# -------------------------------------------------------------------------------------------------------------------- #

CONTROL_ID_A: int = 101
CONTROL_ID_B: int = 102
CONTROL_ID_C: int = 103


def _mock_manager() -> MagicMock:
    """A MagicMock standing in for a ControlMeasureManager instance."""
    return MagicMock(spec=ControlMeasureManager)


class TestGetUsedControlMeasureIds:
    """``get_used_control_measure_ids`` reports which candidates an assignment references."""

    def test_returns_the_referenced_subset(self) -> None:
        """Only the control ids the grouped aggregation returns are reported as used."""
        mgr = _mock_manager()
        mgr.aggregate_all.return_value = [{'_id': CONTROL_ID_A}, {'_id': CONTROL_ID_C}]

        result = ControlMeasureManager.get_used_control_measure_ids(mgr, [CONTROL_ID_A, CONTROL_ID_B, CONTROL_ID_C])

        assert result == {CONTROL_ID_A, CONTROL_ID_C}

    def test_pipeline_matches_candidates_and_groups_by_control_measure_id(self) -> None:
        """The aggregation runs on the assignment collection, matching the candidates and grouping them."""
        mgr = _mock_manager()
        mgr.aggregate_all.return_value = []

        ControlMeasureManager.get_used_control_measure_ids(mgr, [CONTROL_ID_A, CONTROL_ID_B])

        pipeline, collection = mgr.aggregate_all.call_args.args
        assert collection == IsmsControlMeasureAssignment.COLLECTION
        assert pipeline[0]['$match'] == {'control_measure_id': {'$in': [CONTROL_ID_A, CONTROL_ID_B]}}
        assert pipeline[-1]['$group'] == {'_id': '$control_measure_id'}

    def test_empty_input_returns_empty_without_querying(self) -> None:
        """An empty candidate list short-circuits to an empty set and never queries."""
        mgr = _mock_manager()

        assert ControlMeasureManager.get_used_control_measure_ids(mgr, []) == set()
        mgr.aggregate_all.assert_not_called()

    def test_iteration_error_wraps_as_control_measure_get_error(self) -> None:
        """A ``BaseManagerIterationError`` from the aggregation becomes ``ControlMeasureManagerGetError``."""
        mgr = _mock_manager()
        mgr.aggregate_all.side_effect = BaseManagerIterationError('bad pipeline')

        with pytest.raises(ControlMeasureManagerGetError):
            ControlMeasureManager.get_used_control_measure_ids(mgr, [CONTROL_ID_A])

    def test_a_bug_propagates_as_itself(self) -> None:
        """A programming error is not a failed lookup: it is not wrapped, so the route answers 500."""
        mgr = _mock_manager()
        mgr.aggregate_all.side_effect = RuntimeError('boom')

        with pytest.raises(RuntimeError):
            ControlMeasureManager.get_used_control_measure_ids(mgr, [CONTROL_ID_A])


class TestDeleteIfUnused:
    """``delete_if_unused`` refuses a referenced control measure and deletes an unreferenced one."""

    @staticmethod
    def _manager(used: bool) -> MagicMock:
        """A manager whose control measure is (not) referenced, and stored"""
        mgr = _mock_manager()
        mgr.exceptions = CONTROL_MEASURE_MANAGER_ERRORS
        mgr.collection = IsmsControlMeasure.COLLECTION
        mgr.is_control_measure_used.return_value = used
        mgr.find_one_and_delete.return_value = {'public_id': CONTROL_ID_A}

        return mgr

    def test_a_referenced_control_measure_is_refused_before_anything_is_deleted(self) -> None:
        """The usage error is raised unwrapped and nothing is deleted."""
        mgr = self._manager(used=True)

        with pytest.raises(ControlMeasureManagerAssignmentUsageError):
            ControlMeasureManager.delete_if_unused(mgr, CONTROL_ID_A)

        mgr.find_one_and_delete.assert_not_called()

    def test_an_unreferenced_control_measure_is_deleted(self) -> None:
        """One atomic delete by public_id, and True."""
        mgr = self._manager(used=False)

        assert ControlMeasureManager.delete_if_unused(mgr, CONTROL_ID_A) is True
        mgr.find_one_and_delete.assert_called_once_with({'public_id': CONTROL_ID_A})

    def test_a_failed_usage_check_is_the_delete_error(self) -> None:
        """The check's BaseManagerGetError becomes ControlMeasureManagerDeleteError."""
        mgr = self._manager(used=False)
        mgr.is_control_measure_used.side_effect = BaseManagerGetError('down')

        with pytest.raises(ControlMeasureManagerDeleteError):
            ControlMeasureManager.delete_if_unused(mgr, CONTROL_ID_A)


CATALOG_ID: str = 'nist-sp800-53-rev5'
OTHER_CATALOG_ID: str = 'eu-nis2'
CATALOG_COUNT: int = 3
OTHER_CATALOG_COUNT: int = 7


class TestGetCatalogControls:
    """``get_catalog_controls`` reads one catalog's controls, trimmed"""

    def test_reads_the_catalog_trimmed_to_id_identifier_and_the_asked_keys(self) -> None:
        """One find on catalog_id; public_id, identifier and the further keys projected, _id left out"""
        mgr = _mock_manager()
        mgr.find.return_value = [{'public_id': CONTROL_ID_A}]

        assert ControlMeasureManager.get_catalog_controls(mgr, CATALOG_ID, ('title',)) == [{'public_id': CONTROL_ID_A}]

        mgr.find.assert_called_once_with({'catalog_id': CATALOG_ID},
                                         projection={'_id': 0, 'public_id': 1, 'identifier': 1, 'title': 1})

    def test_a_failed_read_is_the_get_error(self) -> None:
        """Wrapped, carrying the exception"""
        mgr = _mock_manager()
        cause = BaseManagerGetError('read failed')
        mgr.find.side_effect = cause

        with pytest.raises(ControlMeasureManagerGetError) as caught:
            ControlMeasureManager.get_catalog_controls(mgr, CATALOG_ID)

        assert caught.value.__cause__ is cause


class TestUpdateCatalogFields:
    """``update_catalog_fields`` writes every change in one bulk write"""

    def test_one_bulk_write_with_one_set_per_control(self) -> None:
        """An UpdateOne per control, keyed by public_id, setting only the given keys"""
        mgr = _mock_manager()
        mgr.bulk_write.return_value = 2

        assert ControlMeasureManager.update_catalog_fields(mgr, [(CONTROL_ID_A, {'title': 'A'}),
                                                                 (CONTROL_ID_B, {'chapter': None})]) == 2

        (operations,) = mgr.bulk_write.call_args.args
        assert operations == [UpdateOne({'public_id': CONTROL_ID_A}, {'$set': {'title': 'A'}}),
                              UpdateOne({'public_id': CONTROL_ID_B}, {'$set': {'chapter': None}})]

    def test_nothing_to_update_writes_nothing(self) -> None:
        """No round trip for an unchanged catalog"""
        mgr = _mock_manager()

        assert ControlMeasureManager.update_catalog_fields(mgr, []) == 0

        mgr.bulk_write.assert_not_called()

    def test_a_failed_bulk_write_is_the_update_error(self) -> None:
        """Wrapped, carrying the exception"""
        mgr = _mock_manager()
        cause = BaseManagerUpdateError('bulk write failed')
        mgr.bulk_write.side_effect = cause

        with pytest.raises(ControlMeasureManagerUpdateError) as caught:
            ControlMeasureManager.update_catalog_fields(mgr, [(CONTROL_ID_A, {'title': 'A'})])

        assert caught.value.__cause__ is cause


class TestCountControlsPerCatalog:
    """``count_controls_per_catalog`` groups the imported controls by catalog"""

    def test_answers_the_count_per_catalog(self) -> None:
        """catalog_id -> count, from the grouped rows"""
        mgr = _mock_manager()
        mgr.aggregate_all.return_value = [{'_id': CATALOG_ID, 'count': CATALOG_COUNT},
                                          {'_id': OTHER_CATALOG_ID, 'count': OTHER_CATALOG_COUNT}]

        assert ControlMeasureManager.count_controls_per_catalog(mgr) == {
            CATALOG_ID: CATALOG_COUNT, OTHER_CATALOG_ID: OTHER_CATALOG_COUNT,
        }

    def test_the_pipeline_skips_manual_controls_and_groups_by_catalog(self) -> None:
        """A control without a catalog (missing, null or blank) is not counted"""
        mgr = _mock_manager()
        mgr.aggregate_all.return_value = []

        ControlMeasureManager.count_controls_per_catalog(mgr)

        (pipeline,) = mgr.aggregate_all.call_args.args
        assert pipeline == [{'$match': {'catalog_id': {'$nin': [None, '']}}},
                            {'$group': {'_id': '$catalog_id', 'count': {'$sum': 1}}}]

    def test_a_failed_aggregation_is_the_iteration_error(self) -> None:
        """Wrapped, carrying the exception"""
        mgr = _mock_manager()
        cause = BaseManagerIterationError('aggregation failed')
        mgr.aggregate_all.side_effect = cause

        with pytest.raises(ControlMeasureManagerIterationError) as caught:
            ControlMeasureManager.count_controls_per_catalog(mgr)

        assert caught.value.__cause__ is cause

