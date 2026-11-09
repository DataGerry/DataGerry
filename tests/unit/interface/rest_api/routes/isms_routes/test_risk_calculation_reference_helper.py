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
Unit tests for risk_calculation_reference_helper: the checks a RiskAssessment's risk calculation passes before a write

Pure tests against a MagicMock RiskAssessmentManager. Pinned:

  - an ImpactCategory rated twice in a matrix is a 400 naming the matrix and the category; once per matrix (and a
    missing category) is legal
  - every ImpactCategory, Impact and Likelihood the matrices name is resolved; one 400 names every unknown id with its
    field path, in document order
  - the ImpactCategories are read once for all the ids, the scales once - and the scales come back to the caller
  - a failed ImpactCategory read is its own 400; a failed scale read propagates as the manager's typed error
  - a module census: the function set is pinned
"""
import inspect
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.manager.isms_manager.isms_manager_helper import RiskCalculationBases
from cmdb.errors.manager import BaseManagerGetError
from cmdb.errors.manager.risk_assessment_manager import RiskAssessmentManagerScaleReadError
from cmdb.interface.rest_api.routes.isms_routes import risk_calculation_reference_helper
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import (
    DUPLICATE_IMPACT_CATEGORIES_MSG,
    IMPACT_CATEGORY_LOOKUP_FAILED_MSG,
    RISK_CALCULATION_REASON,
    RISK_CALCULATION_REASON_SEPARATOR,
    UNKNOWN_RISK_CALCULATION_REFERENCES_MSG,
    RiskCalculationReferenceKind,
)
from cmdb.interface.rest_api.routes.isms_routes.risk_calculation_reference_helper import (
    RiskCalculationReference,
    abort_on_duplicate_impact_categories,
    check_risk_calculation_references,
    collect_risk_calculation_references,
    duplicate_impact_categories,
    field_path,
    ids_of_kind,
    impact_rows,
    named_ids,
    present_matrices,
    read_missing_impact_categories,
    unknown_reference_reasons,
)
# -------------------------------------------------------------------------------------------------------------------- #

BEFORE: str = 'risk_calculation_before'
AFTER: str = 'risk_calculation_after'
CATEGORY_A: int = 11
CATEGORY_B: int = 12
CATEGORY_MISSING: int = 19
IMPACT_LOW: int = 21
IMPACT_HIGH: int = 22
IMPACT_MISSING: int = 29
LIKELIHOOD: int = 31
LIKELIHOOD_MISSING: int = 39
BASIS_LOW: float = 1.0
BASIS_HIGH: float = 3.0
BASIS_LIKELIHOOD: float = 2.0
BASES: RiskCalculationBases = RiskCalculationBases(
    impact={IMPACT_LOW: BASIS_LOW, IMPACT_HIGH: BASIS_HIGH},
    likelihood={LIKELIHOOD: BASIS_LIKELIHOOD},
)
CATEGORY_PATH: str = 'impacts.impact_category_id'
IMPACT_PATH: str = 'impacts.impact_id'
LIKELIHOOD_PATH: str = 'likelihood_id'


def _row(category: Any, impact: Any = None) -> dict[str, Any]:
    """One impacts row"""
    return {'impact_category_id': category, 'impact_id': impact}


def _matrix(rows: list[Any] | None = None, likelihood: Any = None) -> dict[str, Any]:
    """One matrix"""
    return {'impacts': rows if rows is not None else [], 'likelihood_id': likelihood}


def _payload(before: dict[str, Any] | None = None, after: dict[str, Any] | None = None) -> dict[str, Any]:
    """A payload carrying the given matrices"""
    payload: dict[str, Any] = {}

    if before is not None:
        payload[BEFORE] = before

    if after is not None:
        payload[AFTER] = after

    return payload


def _manager(missing_categories: set[int] | None = None) -> MagicMock:
    """A RiskAssessmentManager reporting the given categories missing and answering BASES"""
    manager = MagicMock()
    manager.get_missing_impact_category_ids.return_value = missing_categories or set()
    manager.load_calculation_bases.return_value = BASES

    return manager


def _refusal(call: Any) -> HTTPException:
    """The HTTPException a call raises"""
    with pytest.raises(HTTPException) as raised:
        call()

    return raised.value


def _reason(field: str, ids: list[int]) -> str:
    """One refusal reason"""
    return RISK_CALCULATION_REASON.format(field=field, ids=ids)


class TestBuildingBlocks:
    """The small readers the checks are built from"""

    def test_field_path_joins_the_keys(self) -> None:
        """As the refusals name a field"""
        assert field_path(BEFORE, 'impacts', 'impact_id') == f'{BEFORE}.{IMPACT_PATH}'

    def test_present_matrices_are_the_dicts_in_document_order(self) -> None:
        """A missing or non-dict matrix is left out"""
        before: dict[str, Any] = _matrix()
        after: dict[str, Any] = _matrix(likelihood=LIKELIHOOD)

        assert present_matrices({AFTER: after, BEFORE: before}) == [(BEFORE, before), (AFTER, after)]
        assert present_matrices({BEFORE: None, AFTER: []}) == []

    def test_impact_rows_skip_what_is_no_row(self) -> None:
        """A null list reads as no rows"""
        row: dict[str, Any] = _row(CATEGORY_A)

        assert impact_rows({'impacts': [row, None, CATEGORY_A]}) == [row]
        assert impact_rows({'impacts': None}) == []
        assert impact_rows({}) == []

    def test_named_ids_leave_out_null(self) -> None:
        """null is unrated"""
        assert named_ids([None, IMPACT_LOW, None, IMPACT_LOW]) == frozenset({IMPACT_LOW})

    def test_ids_of_kind_gather_across_field_paths(self) -> None:
        """Both matrices together"""
        references: list[RiskCalculationReference] = [
            RiskCalculationReference('a', RiskCalculationReferenceKind.IMPACT, frozenset({IMPACT_LOW})),
            RiskCalculationReference('b', RiskCalculationReferenceKind.IMPACT, frozenset({IMPACT_HIGH})),
            RiskCalculationReference('c', RiskCalculationReferenceKind.LIKELIHOOD, frozenset({LIKELIHOOD})),
        ]

        assert ids_of_kind(references, RiskCalculationReferenceKind.IMPACT) == {IMPACT_LOW, IMPACT_HIGH}
        assert ids_of_kind(references, RiskCalculationReferenceKind.IMPACT_CATEGORY) == set()


class TestDuplicateImpactCategories:
    """An ImpactCategory is rated at most once per matrix"""

    def test_a_category_rated_twice_is_named(self) -> None:
        """Sorted, each once"""
        matrix: dict[str, Any] = _matrix([_row(CATEGORY_B), _row(CATEGORY_A), _row(CATEGORY_B), _row(CATEGORY_A)])

        assert duplicate_impact_categories(matrix) == [CATEGORY_A, CATEGORY_B]

    def test_each_category_once_is_legal(self) -> None:
        """The frontend's shape"""
        assert not duplicate_impact_categories(_matrix([_row(CATEGORY_A), _row(CATEGORY_B)]))

    def test_the_refusal_names_every_matrix(self) -> None:
        """One 400 for both"""
        twice: list[dict[str, Any]] = [_row(CATEGORY_A), _row(CATEGORY_A)]

        refusal: HTTPException = _refusal(lambda: abort_on_duplicate_impact_categories(
            _payload(_matrix(twice), _matrix(twice)),
        ))

        reasons: list[str] = [_reason(f'{BEFORE}.impacts', [CATEGORY_A]), _reason(f'{AFTER}.impacts', [CATEGORY_A])]

        assert refusal.code == HTTPStatus.BAD_REQUEST
        assert refusal.description == DUPLICATE_IMPACT_CATEGORIES_MSG.format(
            reasons=RISK_CALCULATION_REASON_SEPARATOR.join(reasons),
        )

    def test_the_same_category_in_both_matrices_is_legal(self) -> None:
        """Each matrix rates it once"""
        abort_on_duplicate_impact_categories(_payload(_matrix([_row(CATEGORY_A)]), _matrix([_row(CATEGORY_A)])))

    def test_a_missing_category_is_legal(self) -> None:
        """It reads as unrated"""
        abort_on_duplicate_impact_categories(_payload(_matrix([]), _matrix()))


class TestCollectReferences:
    """Every id the matrices name, by field path, in document order"""

    def test_both_matrices_in_document_order(self) -> None:
        """Category, impact, likelihood - before, then after"""
        payload: dict[str, Any] = _payload(
            _matrix([_row(CATEGORY_A, IMPACT_LOW), _row(CATEGORY_B, None)], LIKELIHOOD),
            _matrix([_row(CATEGORY_B, IMPACT_HIGH)]),
        )

        assert collect_risk_calculation_references(payload) == [
            RiskCalculationReference(f'{BEFORE}.{CATEGORY_PATH}', RiskCalculationReferenceKind.IMPACT_CATEGORY,
                                     frozenset({CATEGORY_A, CATEGORY_B})),
            RiskCalculationReference(f'{BEFORE}.{IMPACT_PATH}', RiskCalculationReferenceKind.IMPACT,
                                     frozenset({IMPACT_LOW})),
            RiskCalculationReference(f'{BEFORE}.{LIKELIHOOD_PATH}', RiskCalculationReferenceKind.LIKELIHOOD,
                                     frozenset({LIKELIHOOD})),
            RiskCalculationReference(f'{AFTER}.{CATEGORY_PATH}', RiskCalculationReferenceKind.IMPACT_CATEGORY,
                                     frozenset({CATEGORY_B})),
            RiskCalculationReference(f'{AFTER}.{IMPACT_PATH}', RiskCalculationReferenceKind.IMPACT,
                                     frozenset({IMPACT_HIGH})),
        ]

    def test_an_unrated_calculation_names_nothing(self) -> None:
        """No row, no likelihood"""
        assert not collect_risk_calculation_references(_payload(_matrix(), _matrix()))


class TestUnknownReferenceReasons:
    """One reason per field path naming an unknown id"""

    def test_only_unknown_ids_of_the_field_paths_kind_are_named(self) -> None:
        """The same number may be a stored Impact and a missing Likelihood"""
        references: list[RiskCalculationReference] = [
            RiskCalculationReference('a', RiskCalculationReferenceKind.IMPACT, frozenset({IMPACT_LOW, IMPACT_HIGH})),
            RiskCalculationReference('b', RiskCalculationReferenceKind.LIKELIHOOD, frozenset({IMPACT_HIGH})),
        ]

        assert unknown_reference_reasons(references, {
            RiskCalculationReferenceKind.IMPACT: {IMPACT_HIGH, IMPACT_LOW},
            RiskCalculationReferenceKind.LIKELIHOOD: set(),
        }) == [_reason('a', [IMPACT_LOW, IMPACT_HIGH])]

    def test_nothing_unknown_is_no_reason(self) -> None:
        """The control"""
        references: list[RiskCalculationReference] = [
            RiskCalculationReference('a', RiskCalculationReferenceKind.IMPACT, frozenset({IMPACT_LOW})),
        ]

        assert not unknown_reference_reasons(references, {})


class TestReadMissingImpactCategories:
    """The ImpactCategory read"""

    def test_answers_the_managers_missing_ids(self) -> None:
        """Passed through"""
        manager: MagicMock = _manager({CATEGORY_MISSING})

        assert read_missing_impact_categories(manager, {CATEGORY_A, CATEGORY_MISSING}) == {CATEGORY_MISSING}
        manager.get_missing_impact_category_ids.assert_called_once_with({CATEGORY_A, CATEGORY_MISSING})

    def test_a_failed_read_is_its_own_400(self) -> None:
        """Not the route's error table"""
        manager: MagicMock = _manager()
        manager.get_missing_impact_category_ids.side_effect = BaseManagerGetError('down')

        refusal: HTTPException = _refusal(lambda: read_missing_impact_categories(manager, {CATEGORY_A}))

        assert (refusal.code, refusal.description) == (HTTPStatus.BAD_REQUEST, IMPACT_CATEGORY_LOOKUP_FAILED_MSG)

    def test_a_programming_error_propagates(self) -> None:
        """Not a failed read"""
        manager: MagicMock = _manager()
        manager.get_missing_impact_category_ids.side_effect = RuntimeError('bug')

        with pytest.raises(RuntimeError):
            read_missing_impact_categories(manager, {CATEGORY_A})


class TestCheckRiskCalculationReferences:
    """The whole check, as the routes call it"""

    def test_a_stored_calculation_passes_and_answers_the_scales(self) -> None:
        """The scales are the ones the caller derives from"""
        manager: MagicMock = _manager()
        payload: dict[str, Any] = _payload(_matrix([_row(CATEGORY_A, IMPACT_LOW)], LIKELIHOOD), _matrix())

        assert check_risk_calculation_references(manager, payload) is BASES
        manager.get_missing_impact_category_ids.assert_called_once_with({CATEGORY_A})
        manager.load_calculation_bases.assert_called_once_with()

    def test_every_unknown_id_is_named_in_one_400(self) -> None:
        """Category, impact and likelihood, both matrices"""
        manager: MagicMock = _manager({CATEGORY_MISSING})
        payload: dict[str, Any] = _payload(
            _matrix([_row(CATEGORY_MISSING, IMPACT_MISSING)], LIKELIHOOD_MISSING),
            _matrix([_row(CATEGORY_A, IMPACT_MISSING)]),
        )

        refusal: HTTPException = _refusal(lambda: check_risk_calculation_references(manager, payload))

        assert refusal.code == HTTPStatus.BAD_REQUEST
        assert refusal.description == UNKNOWN_RISK_CALCULATION_REFERENCES_MSG.format(
            reasons=RISK_CALCULATION_REASON_SEPARATOR.join([
                _reason(f'{BEFORE}.{CATEGORY_PATH}', [CATEGORY_MISSING]),
                _reason(f'{BEFORE}.{IMPACT_PATH}', [IMPACT_MISSING]),
                _reason(f'{BEFORE}.{LIKELIHOOD_PATH}', [LIKELIHOOD_MISSING]),
                _reason(f'{AFTER}.{IMPACT_PATH}', [IMPACT_MISSING]),
            ]),
        )

    def test_a_duplicate_category_is_refused_before_anything_is_read(self) -> None:
        """The cheap check first"""
        manager: MagicMock = _manager()

        refusal: HTTPException = _refusal(lambda: check_risk_calculation_references(
            manager, _payload(_matrix([_row(CATEGORY_A), _row(CATEGORY_A)])),
        ))

        assert refusal.code == HTTPStatus.BAD_REQUEST
        manager.get_missing_impact_category_ids.assert_not_called()
        manager.load_calculation_bases.assert_not_called()

    def test_a_failed_scale_read_propagates_typed(self) -> None:
        """The routes' error tables map it to SCALE_READ"""
        manager: MagicMock = _manager()
        manager.load_calculation_bases.side_effect = RiskAssessmentManagerScaleReadError('down')

        with pytest.raises(RiskAssessmentManagerScaleReadError):
            check_risk_calculation_references(manager, _payload(_matrix()))


def test_the_module_function_set_is_pinned() -> None:
    """A new public function is a deliberate change"""
    functions: set[str] = {
        name for name, member in inspect.getmembers(risk_calculation_reference_helper, inspect.isfunction)
        if member.__module__ == risk_calculation_reference_helper.__name__
    }

    assert functions == {
        'abort_on_duplicate_impact_categories',
        'check_risk_calculation_references',
        'collect_risk_calculation_references',
        'duplicate_impact_categories',
        'field_path',
        'ids_of_kind',
        'impact_rows',
        'named_ids',
        'present_matrices',
        'read_missing_impact_categories',
        'unknown_reference_reasons',
    }
