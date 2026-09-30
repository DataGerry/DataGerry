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
Unit tests for cmdb.framework.isms.risk_matrix_report

Pure tests: no Mongo, no Flask - the three managers are stubs. Moved here (with the module itself)
beside the builder rather than the model, because a builder that orchestrates three managers
is a service rather than a model.

The counting itself is straightforward; what is worth pinning is everything around it:

  - **the current-state rule**, in both directions: an assessment contributes its after-treatment
    values only while its implementation_status is the predefined IMPLEMENTED option
  - **the two silent degradations.** A missing IMPLEMENTED option means nothing counts as implemented,
    so the current-state matrix equals the before-treatment one; an unconfigured risk matrix means
    three empty grids. The first is logged, the second is reported as `configured: false` - before
    that flag existed, "the wizard has not run yet" and "nothing has been assessed" were the same
    answer
  - **the reads**: the assessments are projected to the four keys the report uses and walked ONCE for
    all three matrices, which is what keeps the report at two queries
  - **the cell payload**, which the Angular component renders: the identity keys plus `count` and
    `risk_assessment_ids`, with `count == len(risk_assessment_ids)` per cell
"""
from typing import Any

import pytest

from cmdb.errors.framework_isms import RiskMatrixReportError
from cmdb.framework.isms.risk_matrix_report import ASSESSMENT_PROJECTION, RiskMatrixReportBuilder
from cmdb.models.extendable_option_model import ExtendableOptionKey, OptionType
from cmdb.models.isms_model.implementation_state_enum import ImplementationState
from cmdb.models.isms_model.isms_risk_assessment_constants import RiskAssessmentKey
from cmdb.models.isms_model.isms_risk_matrix_constants import (
    MatrixType,
    RiskMatrixCellKey,
    RiskMatrixReportKey,
    RiskMatrixKey,
    RISK_MATRIX_PUBLIC_ID,
)
from cmdb.models.isms_model.risk_calculation_constants import RiskCalculationKey
# -------------------------------------------------------------------------------------------------------------------- #

IMPACT_ID: int = 10
LIKELIHOOD_ID: int = 20
OTHER_IMPACT_ID: int = 11
OTHER_LIKELIHOOD_ID: int = 21
RISK_CLASS_ID: int = 3
IMPLEMENTED_STATUS_ID: int = 99
OPEN_STATUS_ID: int = 98

RISK_ASSESSMENT_ID: int = 1
OTHER_RISK_ASSESSMENT_ID: int = 2


class _StubRiskAssessmentManager:
    """Serves a fixed list of risk-assessment documents and records how they were asked for."""

    def __init__(self, risk_assessments: list[dict[str, Any]], error: Exception | None = None) -> None:
        self.risk_assessments = risk_assessments
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def find_all(self, **kwargs: Any) -> list[dict[str, Any]]:
        """Returns the configured assessments, or raises the configured error."""
        self.calls.append(kwargs)

        if self.error is not None:
            raise self.error

        return self.risk_assessments


class _StubRiskMatrixManager:
    """Serves a fixed IsmsRiskMatrix document (or None when it does not exist)."""

    def __init__(self, matrix: dict[str, Any] | None, error: Exception | None = None) -> None:
        self.matrix = matrix
        self.error = error
        self.requested_ids: list[int] = []

    def get_item(self, public_id: int, **_kwargs: Any) -> dict[str, Any] | None:
        """Returns the configured matrix document."""
        self.requested_ids.append(public_id)

        if self.error is not None:
            raise self.error

        return self.matrix


class _StubExtendableOptionsManager:
    """Serves a fixed IMPLEMENTED option (or None) and records the criteria it was asked with."""

    def __init__(self, implemented_option: dict[str, Any] | None, error: Exception | None = None) -> None:
        self.implemented_option = implemented_option
        self.error = error
        self.criteria: list[dict[str, Any]] = []

    def get_one_by(self, criteria: dict[str, Any]) -> dict[str, Any] | None:
        """Returns the configured option."""
        self.criteria.append(criteria)

        if self.error is not None:
            raise self.error

        return self.implemented_option


def _cell(impact_id: int = IMPACT_ID, likelihood_id: int = LIKELIHOOD_ID, **overrides: Any) -> dict[str, Any]:
    """One grid cell of the IsmsRiskMatrix."""
    grid_cell: dict[str, Any] = {
        RiskMatrixCellKey.ROW.value: 0,
        RiskMatrixCellKey.COLUMN.value: 0,
        RiskMatrixCellKey.IMPACT_ID.value: impact_id,
        RiskMatrixCellKey.LIKELIHOOD_ID.value: likelihood_id,
        RiskMatrixCellKey.RISK_CLASS_ID.value: RISK_CLASS_ID,
    }
    grid_cell.update(overrides)

    return grid_cell


def _matrix(cells: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """An IsmsRiskMatrix document carrying the given grid (one cell by default)."""
    return {RiskMatrixKey.RISK_MATRIX.value: cells if cells is not None else [_cell()]}


def _assessment(
        implementation_status: int | None = None,
        public_id: int = RISK_ASSESSMENT_ID,
        before: tuple[int, int] | None = (IMPACT_ID, LIKELIHOOD_ID),
        after: tuple[int, int] | None = (OTHER_IMPACT_ID, OTHER_LIKELIHOOD_ID),
) -> dict[str, Any]:
    """A projected risk assessment, by default hitting the cell before treatment only."""
    assessment: dict[str, Any] = {
        RiskAssessmentKey.PUBLIC_ID.value: public_id,
        RiskAssessmentKey.IMPLEMENTATION_STATUS.value: implementation_status,
    }

    for key, pair in ((RiskCalculationKey.BEFORE.value, before), (RiskCalculationKey.AFTER.value, after)):
        if pair is not None:
            assessment[key] = {
                RiskCalculationKey.MAXIMUM_IMPACT_ID.value: pair[0],
                RiskCalculationKey.LIKELIHOOD_ID.value: pair[1],
            }

    return assessment


def _builder(
        assessments: list[dict[str, Any]] | None = None,
        matrix: dict[str, Any] | None = None,
        implemented_option: dict[str, Any] | None = None,
        assessment_error: Exception | None = None,
        matrix_error: Exception | None = None,
        option_error: Exception | None = None,
) -> tuple[RiskMatrixReportBuilder, _StubRiskAssessmentManager,
           _StubRiskMatrixManager, _StubExtendableOptionsManager]:
    """A builder over the three stubs, returned with them so a test can inspect the calls."""
    assessment_manager = _StubRiskAssessmentManager(
        assessments if assessments is not None else [], assessment_error,
    )
    matrix_manager = _StubRiskMatrixManager(matrix if matrix is not None else _matrix(), matrix_error)
    options_manager = _StubExtendableOptionsManager(
        implemented_option if implemented_option is not None
        else {ExtendableOptionKey.PUBLIC_ID.value: IMPLEMENTED_STATUS_ID},
        option_error,
    )

    builder = RiskMatrixReportBuilder(assessment_manager, matrix_manager, options_manager)

    return builder, assessment_manager, matrix_manager, options_manager


def _first_cell(report: dict[str, Any], matrix_type: MatrixType) -> dict[str, Any]:
    """The first reported cell of one matrix."""
    return report[matrix_type.report_key][0]


def _count(report: dict[str, Any], matrix_type: MatrixType) -> int:
    """The count of the first reported cell of one matrix."""
    return _first_cell(report, matrix_type)[RiskMatrixReportKey.COUNT.value]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   the counting                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTheThreeMatrices:
    """The same grid counted by each assessment's before-, current- and after-treatment values."""

    def test_the_report_carries_one_entry_per_matrix_type(self) -> None:
        """The three keys the Angular ReportRiskMatrix model mirrors, plus the configured flag"""
        builder, *_ = _builder([_assessment()])

        report = builder.build_risk_matrix_report()

        assert set(report) == {matrix_type.report_key for matrix_type in MatrixType} | {
            RiskMatrixReportKey.CONFIGURED.value,
        }

    def test_before_treatment_counts_the_assessment_in_its_cell(self) -> None:
        """An assessment lands in the cell of its (maximum_impact_id, likelihood_id)"""
        builder, *_ = _builder([_assessment()])

        report = builder.build_risk_matrix_report()

        assert _count(report, MatrixType.BEFORE_TREATMENT) == 1
        assert _first_cell(report, MatrixType.BEFORE_TREATMENT)[
            RiskMatrixReportKey.RISK_ASSESSMENT_IDS.value
        ] == [RISK_ASSESSMENT_ID]

    def test_after_treatment_does_not_count_an_assessment_whose_after_values_miss(self) -> None:
        """The after-treatment matrix is counted from the after-treatment calculation alone"""
        builder, *_ = _builder([_assessment()])

        assert _count(builder.build_risk_matrix_report(), MatrixType.AFTER_TREATMENT) == 0

    def test_after_treatment_counts_an_assessment_whose_after_values_hit(self) -> None:
        """The positive direction of the same rule"""
        builder, *_ = _builder([_assessment(after=(IMPACT_ID, LIKELIHOOD_ID))])

        assert _count(builder.build_risk_matrix_report(), MatrixType.AFTER_TREATMENT) == 1

    def test_every_assessment_of_a_cell_is_reported(self) -> None:
        """Two assessments in one cell: the count and the id list agree"""
        builder, *_ = _builder([_assessment(), _assessment(public_id=OTHER_RISK_ASSESSMENT_ID)])

        cell = _first_cell(builder.build_risk_matrix_report(), MatrixType.BEFORE_TREATMENT)

        assert cell[RiskMatrixReportKey.COUNT.value] == 2
        assert cell[RiskMatrixReportKey.RISK_ASSESSMENT_IDS.value] == [
            RISK_ASSESSMENT_ID, OTHER_RISK_ASSESSMENT_ID,
        ]

    def test_a_cell_with_no_assessments_is_still_reported(self) -> None:
        """The grid is the report's shape: an empty cell is a zero, not a gap"""
        builder, *_ = _builder([], _matrix([_cell(), _cell(OTHER_IMPACT_ID, OTHER_LIKELIHOOD_ID)]))

        report = builder.build_risk_matrix_report()

        assert [cell[RiskMatrixReportKey.COUNT.value]
                for cell in report[MatrixType.BEFORE_TREATMENT.report_key]] == [0, 0]

    def test_a_reported_cell_carries_the_identity_keys_and_the_two_report_keys(self) -> None:
        """The cell shape the frontend renders"""
        builder, *_ = _builder([_assessment()])

        cell = _first_cell(builder.build_risk_matrix_report(), MatrixType.BEFORE_TREATMENT)

        assert set(cell) == {
            RiskMatrixCellKey.ROW.value,
            RiskMatrixCellKey.COLUMN.value,
            RiskMatrixCellKey.RISK_CLASS_ID.value,
            RiskMatrixReportKey.COUNT.value,
            RiskMatrixReportKey.RISK_ASSESSMENT_IDS.value,
        }

    def test_the_count_always_matches_the_id_list(self) -> None:
        """One invariant across every cell of every matrix"""
        builder, *_ = _builder(
            [_assessment(), _assessment(public_id=OTHER_RISK_ASSESSMENT_ID, before=(OTHER_IMPACT_ID,
                                                                                    OTHER_LIKELIHOOD_ID))],
            _matrix([_cell(), _cell(OTHER_IMPACT_ID, OTHER_LIKELIHOOD_ID)]),
        )

        report = builder.build_risk_matrix_report()

        for matrix_type in MatrixType:
            for cell in report[matrix_type.report_key]:
                assert cell[RiskMatrixReportKey.COUNT.value] == len(
                    cell[RiskMatrixReportKey.RISK_ASSESSMENT_IDS.value]
                )


# -------------------------------------------------------------------------------------------------------------------- #
#                                              the current-state rule                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTheCurrentStateRule:
    """After-treatment values only while the assessment is implemented - the report's one real rule."""

    def test_an_implemented_assessment_uses_its_after_values(self) -> None:
        """So it leaves the cell its before-values pointed at"""
        builder, *_ = _builder([_assessment(implementation_status=IMPLEMENTED_STATUS_ID)])

        assert _count(builder.build_risk_matrix_report(), MatrixType.CURRENT_STATE) == 0

    def test_an_implemented_assessment_lands_in_its_after_cell(self) -> None:
        """The positive direction: it is counted where its after-values point"""
        builder, *_ = _builder(
            [_assessment(implementation_status=IMPLEMENTED_STATUS_ID, after=(IMPACT_ID, LIKELIHOOD_ID))],
        )

        assert _count(builder.build_risk_matrix_report(), MatrixType.CURRENT_STATE) == 1

    @pytest.mark.parametrize('status', [None, OPEN_STATUS_ID], ids=['no-status', 'other-status'])
    def test_an_unimplemented_assessment_uses_its_before_values(self, status: int | None) -> None:
        """Any status that is not the IMPLEMENTED one counts as not implemented"""
        builder, *_ = _builder([_assessment(implementation_status=status)])

        assert _count(builder.build_risk_matrix_report(), MatrixType.CURRENT_STATE) == 1

    def test_the_implemented_option_is_resolved_by_its_predefined_value(self) -> None:
        """
        The criteria, composed rather than re-spelled as a literal

        The seeding writes `ImplementationState.IMPLEMENTED`; the report resolves the same constant,
        so a renamed option cannot silently make the current-state matrix a copy of the
        before-treatment one.
        """
        builder, _assessments, _matrix_manager, options_manager = _builder([_assessment()])

        builder.build_risk_matrix_report()

        assert options_manager.criteria == [{
            ExtendableOptionKey.VALUE.value: ImplementationState.IMPLEMENTED.value,
            ExtendableOptionKey.OPTION_TYPE.value: OptionType.IMPLEMENTATION_STATE.value,
            ExtendableOptionKey.PREDEFINED.value: True,
        }]

    def test_a_missing_implemented_option_means_nothing_is_implemented(self) -> None:
        """The degradation is deliberate (and logged): before-treatment values for everyone"""
        builder, *_ = _builder(
            [_assessment(implementation_status=IMPLEMENTED_STATUS_ID)], implemented_option={},
        )

        assert _count(builder.build_risk_matrix_report(), MatrixType.CURRENT_STATE) == 1

    def test_the_option_is_resolved_once_for_the_whole_report(self) -> None:
        """Three matrices, one lookup"""
        builder, _assessments, _matrix_manager, options_manager = _builder(
            [_assessment(), _assessment(public_id=OTHER_RISK_ASSESSMENT_ID)],
        )

        builder.build_risk_matrix_report()

        assert len(options_manager.criteria) == 1


# -------------------------------------------------------------------------------------------------------------------- #
#                                            the unconfigured matrix                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTheUnconfiguredMatrix:
    """An ISMS whose config wizard has not produced the grid yet says so."""

    @pytest.mark.parametrize('matrix', [None, {}, {RiskMatrixKey.RISK_MATRIX.value: []}],
                             ids=['missing', 'empty-document', 'empty-grid'])
    def test_it_is_reported_as_not_configured(self, matrix: dict[str, Any] | None) -> None:
        """
        `configured: false` beside three empty grids

        Without the flag this is indistinguishable from a configured matrix that nothing has been
        assessed against - the same "empty means complete" shape the risk-matrix helper sweep found.
        """
        builder, *_ = _builder([_assessment()], matrix=matrix if matrix is not None else _matrix([]))

        report = builder.build_risk_matrix_report()

        assert report[RiskMatrixReportKey.CONFIGURED.value] is False
        assert all(report[matrix_type.report_key] == [] for matrix_type in MatrixType)

    def test_a_configured_matrix_says_so(self) -> None:
        """The flag is True as soon as the grid has a cell"""
        builder, *_ = _builder([_assessment()])

        assert builder.build_risk_matrix_report()[RiskMatrixReportKey.CONFIGURED.value] is True

    def test_the_singleton_is_read_by_its_declared_id(self) -> None:
        """The matrix is one document, always at RISK_MATRIX_PUBLIC_ID"""
        builder, _assessments, matrix_manager, _options = _builder([])

        builder.build_risk_matrix_report()

        assert matrix_manager.requested_ids == [RISK_MATRIX_PUBLIC_ID]


# -------------------------------------------------------------------------------------------------------------------- #
#                                            the drifted documents                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDriftedDocuments:
    """One broken document costs itself, never the report."""

    @pytest.mark.parametrize('missing_key', [RiskMatrixCellKey.IMPACT_ID, RiskMatrixCellKey.LIKELIHOOD_ID],
                             ids=['impact', 'likelihood'])
    def test_a_cell_without_its_identity_is_skipped(self, missing_key: RiskMatrixCellKey) -> None:
        """
        A KeyError here is reported by the route as a 500 for the whole report

        A cell that does not carry the pair the assessments are indexed by cannot be filled, so it is
        reported and skipped while the rest of the grid is answered.
        """
        broken_cell = _cell()
        del broken_cell[missing_key.value]
        builder, *_ = _builder([_assessment()], _matrix([broken_cell, _cell()]))

        report = builder.build_risk_matrix_report()

        assert len(report[MatrixType.BEFORE_TREATMENT.report_key]) == 1
        assert _count(report, MatrixType.BEFORE_TREATMENT) == 1

    @pytest.mark.parametrize('calculation', [None, {}, 'not-a-calculation'],
                             ids=['absent', 'empty', 'not-a-dict'])
    def test_an_assessment_without_a_usable_calculation_is_skipped(self, calculation: Any) -> None:
        """It is simply not placed - the other assessments still are"""
        assessment = _assessment(before=None)

        if calculation is not None:
            assessment[RiskCalculationKey.BEFORE.value] = calculation

        builder, *_ = _builder([assessment, _assessment(public_id=OTHER_RISK_ASSESSMENT_ID)])

        report = builder.build_risk_matrix_report()

        assert _first_cell(report, MatrixType.BEFORE_TREATMENT)[
            RiskMatrixReportKey.RISK_ASSESSMENT_IDS.value
        ] == [OTHER_RISK_ASSESSMENT_ID]

    @pytest.mark.parametrize('incomplete', [
        {RiskCalculationKey.MAXIMUM_IMPACT_ID.value: IMPACT_ID},
        {RiskCalculationKey.LIKELIHOOD_ID.value: LIKELIHOOD_ID},
    ], ids=['no-likelihood', 'no-impact'])
    def test_a_calculation_missing_one_id_is_skipped(self, incomplete: dict[str, Any]) -> None:
        """Half a coordinate is no coordinate - one of the two arms no test reached before"""
        assessment = _assessment(before=None)
        assessment[RiskCalculationKey.BEFORE.value] = incomplete

        builder, *_ = _builder([assessment])

        assert _count(builder.build_risk_matrix_report(), MatrixType.BEFORE_TREATMENT) == 0

    def test_an_assessment_without_a_public_id_is_skipped(self) -> None:
        """There would be nothing to report in `risk_assessment_ids`"""
        builder, *_ = _builder([_assessment(public_id=None)])

        assert _count(builder.build_risk_matrix_report(), MatrixType.BEFORE_TREATMENT) == 0


# -------------------------------------------------------------------------------------------------------------------- #
#                                              the reads and the errors                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTheReads:
    """Two queries, projected, however many assessments there are."""

    def test_the_assessments_are_read_once_and_projected(self) -> None:
        """
        Three matrices from one pass over one read

        The projection is what keeps every assessment's impacts, dates and person references out of a
        report that uses four of their keys.
        """
        builder, assessment_manager, _matrix_manager, _options = _builder([_assessment()])

        builder.build_risk_matrix_report()

        assert assessment_manager.calls == [{'projection': ASSESSMENT_PROJECTION}]

    def test_the_projection_names_exactly_what_the_report_uses(self) -> None:
        """A key added to the report has to be added here, or it reads as absent"""
        assert set(ASSESSMENT_PROJECTION) == {
            RiskAssessmentKey.PUBLIC_ID.value,
            RiskAssessmentKey.IMPLEMENTATION_STATUS.value,
            RiskCalculationKey.BEFORE.value,
            RiskCalculationKey.AFTER.value,
            '_id',
        }

    @pytest.mark.parametrize('failure', ['assessment_error', 'matrix_error', 'option_error'])
    def test_a_failing_read_is_reported_as_a_report_error(self, failure: str) -> None:
        """
        The route answers 400 with "the report could not be built"

        Every failure otherwise reaches the route's blanket handler as a 500, whatever went wrong.
        """
        builder, *_ = _builder([_assessment()], **{failure: RuntimeError('boom')})

        with pytest.raises(RiskMatrixReportError):
            builder.build_risk_matrix_report()
