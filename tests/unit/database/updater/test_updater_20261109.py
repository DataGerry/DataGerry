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
Unit tests for cmdb.database.updater.versions.updater_20261109

The migration nulls or removes a RiskAssessment's and a ControlMeasure's reference ids that name nothing stored. Its
run against a real database is its own integration test; this module owns the frozen literals, the id rule, the row
cleaning (an unknown or repeated category removed, an unknown impact nulled), the recomputed derived values, the
per-document ``$set``, the version bump and the failure tail
"""
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.database.updater.versions import updater_20261109 as module
from cmdb.database.updater.versions.updater_20261109 import (
    StoredReferences,
    Update20261109,
    assessment_changes,
    clean_impact_rows,
    clean_matrix,
    control_measure_changes,
    derive_matrix_values,
    is_public_id,
    known_or_none,
)
from cmdb.models.extendable_option_model import CmdbExtendableOption, ExtendableOptionKey
from cmdb.models.extendable_option_model.option_type_enum import OptionType
from cmdb.models.isms_model import (
    IsmsControlMeasure,
    IsmsImpact,
    IsmsImpactCategory,
    IsmsLikelihood,
    IsmsRiskAssessment,
)
from cmdb.models.isms_model.isms_control_measure_constants import ControlMeasureKey
from cmdb.models.isms_model.isms_impact_constants import ImpactKey
from cmdb.models.isms_model.isms_risk_assessment_constants import RiskAssessmentKey
from cmdb.models.isms_model.risk_calculation_constants import RISK_CALCULATION_MATRIX_KEYS, RiskCalculationKey
from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

CREATION_DATE: int = 20261109
DATABASE_NAME: str = 'cmdb-unit'
DB_FAILURE: str = 'assessments gone'
CATEGORY_A: int = 11
CATEGORY_B: int = 12
CATEGORY_MISSING: int = 19
IMPACT_LOW: int = 21
IMPACT_HIGH: int = 22
IMPACT_MISSING: int = 29
LIKELIHOOD: int = 31
LIKELIHOOD_MISSING: int = 39
STATE: int = 41
OTHER_LIST_OPTION: int = 42
BASIS_LOW: float = 1.0
BASIS_HIGH: float = 3.0
BASIS_LIKELIHOOD: float = 2.0
BEFORE: str = 'risk_calculation_before'
AFTER: str = 'risk_calculation_after'
REFERENCES: StoredReferences = StoredReferences(
    impact_categories={CATEGORY_A, CATEGORY_B},
    impact_bases={IMPACT_LOW: BASIS_LOW, IMPACT_HIGH: BASIS_HIGH},
    likelihood_bases={LIKELIHOOD: BASIS_LIKELIHOOD},
    implementation_states={STATE},
)
NOT_AN_ID: list[Any] = [0, -1, True, False, None, '11', 1.5]
NOT_AN_ID_NAMES: list[str] = ['zero', 'negative', 'true', 'false', 'null', 'string', 'float']


def _row(category: Any, impact: Any = None) -> dict[str, Any]:
    """One stored impacts row"""
    return {'impact_category_id': category, 'impact_id': impact}


def _matrix(rows: list[Any], likelihood: Any = None, **derived: Any) -> dict[str, Any]:
    """One stored matrix, its derived values as stored"""
    return {'impacts': rows, 'likelihood_id': likelihood, 'likelihood_value': None, 'maximum_impact_id': None,
            'maximum_impact_value': None, **derived}


def _derived(matrix: dict[str, Any]) -> tuple[Any, Any, Any]:
    """The three derived values of a matrix"""
    return matrix['maximum_impact_id'], matrix['maximum_impact_value'], matrix['likelihood_value']


@pytest.mark.parametrize('frozen, live', [
    (module.RISK_ASSESSMENTS_COLLECTION, IsmsRiskAssessment.COLLECTION),
    (module.CONTROL_MEASURES_COLLECTION, IsmsControlMeasure.COLLECTION),
    (module.IMPACT_CATEGORIES_COLLECTION, IsmsImpactCategory.COLLECTION),
    (module.IMPACTS_COLLECTION, IsmsImpact.COLLECTION),
    (module.LIKELIHOODS_COLLECTION, IsmsLikelihood.COLLECTION),
    (module.OPTIONS_COLLECTION, CmdbExtendableOption.COLLECTION),
    (module.PUBLIC_ID_FIELD, RiskAssessmentKey.PUBLIC_ID.value),
    (module.CALCULATION_BASIS_FIELD, ImpactKey.CALCULATION_BASIS.value),
    (module.OPTION_TYPE_FIELD, ExtendableOptionKey.OPTION_TYPE.value),
    (module.IMPLEMENTATION_STATE_OPTION_TYPE, OptionType.IMPLEMENTATION_STATE.value),
    (module.IMPACTS_FIELD, RiskCalculationKey.IMPACTS.value),
    (module.IMPACT_CATEGORY_ID_FIELD, RiskCalculationKey.IMPACT_CATEGORY_ID.value),
    (module.IMPACT_ID_FIELD, RiskCalculationKey.IMPACT_ID.value),
    (module.LIKELIHOOD_ID_FIELD, RiskCalculationKey.LIKELIHOOD_ID.value),
    (module.LIKELIHOOD_VALUE_FIELD, RiskCalculationKey.LIKELIHOOD_VALUE.value),
    (module.MAXIMUM_IMPACT_ID_FIELD, RiskCalculationKey.MAXIMUM_IMPACT_ID.value),
    (module.MAXIMUM_IMPACT_VALUE_FIELD, RiskCalculationKey.MAXIMUM_IMPACT_VALUE.value),
    (module.ASSESSMENT_STATE_FIELD, RiskAssessmentKey.IMPLEMENTATION_STATUS.value),
    (module.CONTROL_MEASURE_STATE_FIELD, ControlMeasureKey.IMPLEMENTATION_STATE.value),
])
def test_the_frozen_literals_still_match_the_code(frozen: str, live: str) -> None:
    """The migration's copies of the names still mean what the code means today"""
    assert frozen == live


def test_the_frozen_matrix_keys_match_the_code() -> None:
    """Both matrices, in document order"""
    assert module.MATRIX_KEYS == tuple(matrix_key.value for matrix_key in RISK_CALCULATION_MATRIX_KEYS)


class TestTheIdRule:
    """A public_id is an int from 1; a bool is none"""

    @pytest.mark.parametrize('value', NOT_AN_ID, ids=NOT_AN_ID_NAMES)
    def test_no_id(self, value: Any) -> None:
        """Each is refused by the write routes now"""
        assert not is_public_id(value)

    def test_an_id(self) -> None:
        """The control"""
        assert is_public_id(IMPACT_LOW)

    def test_known_or_none(self) -> None:
        """A stored id stays, anything else is None"""
        assert known_or_none(IMPACT_LOW, REFERENCES.impact_bases) == IMPACT_LOW
        assert known_or_none(IMPACT_MISSING, REFERENCES.impact_bases) is None
        assert known_or_none(True, {1: BASIS_LOW}) is None


class TestCleanImpactRows:
    """Every category stored and rated once, every impact stored or null"""

    def test_a_row_of_an_unknown_or_invalid_category_is_removed(self) -> None:
        """It rates nothing a reader can show"""
        rows: list[Any] = [_row(CATEGORY_MISSING, IMPACT_LOW), _row(True, IMPACT_LOW), _row(0), None,
                           _row(CATEGORY_A, IMPACT_LOW)]

        assert clean_impact_rows(rows, REFERENCES) == [_row(CATEGORY_A, IMPACT_LOW)]

    def test_the_first_row_of_a_category_is_kept(self) -> None:
        """Stored order"""
        rows: list[Any] = [_row(CATEGORY_A, IMPACT_LOW), _row(CATEGORY_B), _row(CATEGORY_A, IMPACT_HIGH)]

        assert clean_impact_rows(rows, REFERENCES) == [_row(CATEGORY_A, IMPACT_LOW), _row(CATEGORY_B)]

    @pytest.mark.parametrize('impact', [IMPACT_MISSING, 0, True], ids=['unknown', 'zero', 'true'])
    def test_an_unknown_or_invalid_impact_becomes_unrated(self, impact: Any) -> None:
        """The row stays"""
        assert clean_impact_rows([_row(CATEGORY_A, impact)], REFERENCES) == [_row(CATEGORY_A, None)]


class TestDeriveMatrixValues:
    """Recomputed as every write derives them"""

    def test_the_highest_basis_and_the_likelihood_basis(self) -> None:
        """Maximum impact id + value, likelihood value"""
        matrix: dict[str, Any] = _matrix([_row(CATEGORY_A, IMPACT_LOW), _row(CATEGORY_B, IMPACT_HIGH)], LIKELIHOOD)

        assert _derived(derive_matrix_values(matrix, REFERENCES)) == (IMPACT_HIGH, BASIS_HIGH, BASIS_LIKELIHOOD)

    def test_the_first_row_wins_a_tie(self) -> None:
        """Strictly greater replaces"""
        references: StoredReferences = REFERENCES._replace(impact_bases={IMPACT_LOW: BASIS_HIGH,
                                                                         IMPACT_HIGH: BASIS_HIGH})
        matrix: dict[str, Any] = _matrix([_row(CATEGORY_A, IMPACT_LOW), _row(CATEGORY_B, IMPACT_HIGH)])

        assert _derived(derive_matrix_values(matrix, references))[0] == IMPACT_LOW

    def test_nothing_rated_is_all_null(self) -> None:
        """Unrated"""
        assert _derived(derive_matrix_values(_matrix([_row(CATEGORY_A)]), REFERENCES)) == (None, None, None)


class TestCleanMatrix:
    """A matrix brought in line, or None when it already is"""

    def test_a_clean_matrix_is_left_alone(self) -> None:
        """Even with stale derived values: the update only rewrites what it cleans"""
        matrix: dict[str, Any] = _matrix([_row(CATEGORY_A, IMPACT_LOW)], LIKELIHOOD, maximum_impact_value=99.0)

        assert clean_matrix(matrix, REFERENCES) is None

    def test_a_boolean_impact_is_nulled_and_the_values_rederived(self) -> None:
        """``true`` used to be read as Impact 1 and stored as the maximum"""
        matrix: dict[str, Any] = _matrix([_row(CATEGORY_A, True), _row(CATEGORY_B, IMPACT_LOW)], True,
                                         maximum_impact_id=True, maximum_impact_value=BASIS_HIGH,
                                         likelihood_value=BASIS_HIGH)

        cleaned: dict[str, Any] | None = clean_matrix(matrix, REFERENCES)

        assert cleaned['impacts'] == [_row(CATEGORY_A, None), _row(CATEGORY_B, IMPACT_LOW)]
        assert cleaned['likelihood_id'] is None
        assert _derived(cleaned) == (IMPACT_LOW, BASIS_LOW, None)

    @pytest.mark.parametrize('likelihood', [LIKELIHOOD_MISSING, 0], ids=['unknown', 'zero'])
    def test_an_unknown_likelihood_becomes_unrated(self, likelihood: Any) -> None:
        """Its value with it"""
        cleaned: dict[str, Any] | None = clean_matrix(_matrix([], likelihood), REFERENCES)

        assert (cleaned['likelihood_id'], cleaned['likelihood_value']) == (None, None)

    def test_impacts_that_are_no_list_are_left_alone(self) -> None:
        """Only the likelihood is judged"""
        matrix: dict[str, Any] = _matrix(None, LIKELIHOOD_MISSING)

        assert clean_matrix(matrix, REFERENCES)['impacts'] is None


class TestDocumentChanges:
    """The ``$set`` of one stored document"""

    def test_an_assessment_in_line_has_no_changes(self) -> None:
        """Both matrices clean, the state an option"""
        assessment: dict[str, Any] = {BEFORE: _matrix([_row(CATEGORY_A, IMPACT_LOW)]), AFTER: _matrix([]),
                                      'implementation_status': STATE}

        assert not assessment_changes(assessment, REFERENCES)

    def test_only_the_matrices_that_changed_are_set(self) -> None:
        """The other one is not rewritten"""
        assessment: dict[str, Any] = {BEFORE: _matrix([_row(CATEGORY_A, IMPACT_LOW)]),
                                      AFTER: _matrix([_row(CATEGORY_MISSING)]), 'implementation_status': None}

        assert set(assessment_changes(assessment, REFERENCES)) == {AFTER}

    @pytest.mark.parametrize('state', [OTHER_LIST_OPTION, 0, True], ids=['other-list', 'zero', 'true'])
    def test_a_state_that_is_no_option_becomes_null(self, state: Any) -> None:
        """No state chosen"""
        assert assessment_changes({'implementation_status': state}, REFERENCES) == {'implementation_status': None}

    def test_a_matrix_that_is_no_dict_is_skipped(self) -> None:
        """Nothing to clean"""
        assert not assessment_changes({BEFORE: None, AFTER: []}, REFERENCES)

    @pytest.mark.parametrize('state, expected', [
        (STATE, {}), (None, {}), (OTHER_LIST_OPTION, {'implementation_state': None}),
        (False, {'implementation_state': None}),
    ], ids=['an-option', 'null', 'other-list', 'false'])
    def test_a_control_measure_state(self, state: Any, expected: dict[str, Any]) -> None:
        """The same rule"""
        assert control_measure_changes({'implementation_state': state}, REFERENCES) == expected


def _updater(collections: dict[str, list[dict[str, Any]]]) -> tuple[Update20261109, MagicMock]:
    """The migration over a mocked database manager answering each collection's documents"""
    dbm = MagicMock()
    dbm.find.side_effect = lambda **kwargs: iter(collections.get(kwargs['collection'], []))
    updater = Update20261109(dbm, DATABASE_NAME)
    updater.increase_updater_version = MagicMock()

    return updater, dbm


def _stored() -> dict[str, list[dict[str, Any]]]:
    """What the scales and lists hold"""
    return {
        IsmsImpactCategory.COLLECTION: [{'public_id': CATEGORY_A}, {'public_id': CATEGORY_B}],
        IsmsImpact.COLLECTION: [{'public_id': IMPACT_LOW, 'calculation_basis': BASIS_LOW}],
        IsmsLikelihood.COLLECTION: [{'public_id': LIKELIHOOD, 'calculation_basis': BASIS_LIKELIHOOD}],
        CmdbExtendableOption.COLLECTION: [{'public_id': STATE}],
    }


def test_the_version_and_description() -> None:
    """The date it is registered under"""
    updater, _dbm = _updater({})

    assert updater.creation_date() == CREATION_DATE
    assert updater.description()


def test_the_states_are_read_from_the_implementation_state_list_only() -> None:
    """An option of another list names no state"""
    updater, dbm = _updater(_stored())

    updater.read_stored_references()

    criteria: list[dict[str, Any]] = [call.kwargs['filter'] for call in dbm.find.call_args_list
                                      if call.kwargs['collection'] == CmdbExtendableOption.COLLECTION]
    assert criteria == [{'option_type': OptionType.IMPLEMENTATION_STATE.value}]


def test_out_of_line_documents_are_rewritten_in_one_write_each_then_the_version() -> None:
    """One bulk write per collection, the clean document left out"""
    stored: dict[str, list[dict[str, Any]]] = {
        **_stored(),
        IsmsRiskAssessment.COLLECTION: [
            {'_id': 'a', 'public_id': 1, BEFORE: _matrix([_row(CATEGORY_A, IMPACT_LOW)]), 'implementation_status': 0},
            {'_id': 'b', 'public_id': 2, BEFORE: _matrix([_row(CATEGORY_A, IMPACT_LOW)]),
             'implementation_status': STATE},
        ],
        IsmsControlMeasure.COLLECTION: [{'_id': 'c', 'public_id': 3, 'implementation_state': OTHER_LIST_OPTION}],
    }
    updater, dbm = _updater(stored)

    updater.start_update()

    writes: dict[str, Any] = {call.args[0]: call.args[2] for call in dbm.bulk_write.call_args_list}
    assert set(writes) == {IsmsRiskAssessment.COLLECTION, IsmsControlMeasure.COLLECTION}
    # pylint: disable-next=protected-access
    assert [(op._filter, op._doc) for op in writes[IsmsRiskAssessment.COLLECTION]] == [
        ({'_id': 'a'}, {'$set': {'implementation_status': None}}),
    ]
    # pylint: disable-next=protected-access
    assert [(op._filter, op._doc) for op in writes[IsmsControlMeasure.COLLECTION]] == [
        ({'_id': 'c'}, {'$set': {'implementation_state': None}}),
    ]
    updater.increase_updater_version.assert_called_once_with(CREATION_DATE)


def test_a_clean_database_writes_nothing_and_still_bumps() -> None:
    """The second run"""
    updater, dbm = _updater(_stored())

    updater.start_update()

    dbm.bulk_write.assert_not_called()
    updater.increase_updater_version.assert_called_once_with(CREATION_DATE)


def test_a_failing_write_is_the_updater_exception_carrying_the_error() -> None:
    """The exception itself, not its text; the version is not bumped"""
    stored: dict[str, list[dict[str, Any]]] = {
        **_stored(), IsmsControlMeasure.COLLECTION: [{'_id': 'c', 'implementation_state': 0}],
    }
    updater, dbm = _updater(stored)
    failure = RuntimeError(DB_FAILURE)
    dbm.bulk_write.side_effect = failure

    with pytest.raises(UpdaterException) as raised:
        updater.start_update()

    assert raised.value.args[0] is failure
    updater.increase_updater_version.assert_not_called()
