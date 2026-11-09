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
Integration test for cmdb.database.updater.versions.updater_20261109 against a real MongoDB

Seeds what the old writes let through - an assessment with a 0 likelihood, a ``true`` impact (stored as the maximum),
a row of a missing category, one category rated twice and a state of another option list; a ControlMeasure with an
unknown state - next to documents that must not change (a clean assessment, a ControlMeasure without a state, a
ControlMeasureAssignment whose required state is invalid), runs the migration twice and reads them back: the dirty
ones are in line with their derived values recomputed, the rest untouched, and the second run changes nothing
"""
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20261109 import Update20261109
from cmdb.models.extendable_option_model import CmdbExtendableOption
from cmdb.models.extendable_option_model.option_type_enum import OptionType
from cmdb.models.isms_model import (
    IsmsControlMeasure,
    IsmsControlMeasureAssignment,
    IsmsImpact,
    IsmsImpactCategory,
    IsmsLikelihood,
    IsmsRiskAssessment,
)
# -------------------------------------------------------------------------------------------------------------------- #

CATEGORY_A: int = 943301
CATEGORY_B: int = 943302
CATEGORY_MISSING: int = 943309
IMPACT_LOW: int = 943311
IMPACT_HIGH: int = 943312
LIKELIHOOD: int = 943321
STATE: int = 943331
OTHER_LIST_OPTION: int = 943332
MISSING_STATE: int = 943339
DIRTY_RA: int = 943341
CLEAN_RA: int = 943342
DIRTY_CM: int = 943351
CLEAN_CM: int = 943352
STRICT_CMA: int = 943361
BASIS_LOW: float = 1.0
BASIS_HIGH: float = 3.0
BASIS_LIKELIHOOD: float = 2.0
BEFORE: str = 'risk_calculation_before'
AFTER: str = 'risk_calculation_after'

SEEDED: dict[str, list[int]] = {
    IsmsImpactCategory.COLLECTION: [CATEGORY_A, CATEGORY_B],
    IsmsImpact.COLLECTION: [IMPACT_LOW, IMPACT_HIGH],
    IsmsLikelihood.COLLECTION: [LIKELIHOOD],
    CmdbExtendableOption.COLLECTION: [STATE, OTHER_LIST_OPTION],
    IsmsRiskAssessment.COLLECTION: [DIRTY_RA, CLEAN_RA],
    IsmsControlMeasure.COLLECTION: [DIRTY_CM, CLEAN_CM],
    IsmsControlMeasureAssignment.COLLECTION: [STRICT_CMA],
}


def _matrix(rows: list[dict[str, Any]], likelihood: Any, maximum_id: Any = None, maximum_value: Any = None,
            likelihood_value: Any = None) -> dict[str, Any]:
    """One stored matrix"""
    return {'impacts': rows, 'likelihood_id': likelihood, 'likelihood_value': likelihood_value,
            'maximum_impact_id': maximum_id, 'maximum_impact_value': maximum_value}


def _row(category: Any, impact: Any) -> dict[str, Any]:
    """One stored impacts row"""
    return {'impact_category_id': category, 'impact_id': impact}


CLEAN_MATRIX: dict[str, Any] = _matrix([_row(CATEGORY_A, IMPACT_HIGH)], LIKELIHOOD, IMPACT_HIGH, BASIS_HIGH,
                                       BASIS_LIKELIHOOD)


def _purge(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """Removes every seeded document"""
    for collection, public_ids in SEEDED.items():
        database_manager.get_collection(collection, database_name).delete_many({'public_id': {'$in': public_ids}})


@pytest.fixture(name='collections')
def fixture_collections(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The seeded documents, removed afterwards; answers a reader of one stored document"""
    def _insert(collection: str, *documents: dict[str, Any]) -> None:
        database_manager.get_collection(collection, database_name).insert_many(list(documents))

    _purge(database_manager, database_name)
    _insert(IsmsImpactCategory.COLLECTION, {'public_id': CATEGORY_A, 'name': 'A'}, {'public_id': CATEGORY_B,
                                                                                    'name': 'B'})
    _insert(IsmsImpact.COLLECTION, {'public_id': IMPACT_LOW, 'calculation_basis': BASIS_LOW},
            {'public_id': IMPACT_HIGH, 'calculation_basis': BASIS_HIGH})
    _insert(IsmsLikelihood.COLLECTION, {'public_id': LIKELIHOOD, 'calculation_basis': BASIS_LIKELIHOOD})
    _insert(CmdbExtendableOption.COLLECTION,
            {'public_id': STATE, 'value': 'Integration state 943331',
             'option_type': OptionType.IMPLEMENTATION_STATE.value},
            {'public_id': OTHER_LIST_OPTION, 'value': 'Integration risk category 943332',
             'option_type': OptionType.RISK.value})
    _insert(IsmsRiskAssessment.COLLECTION,
            {'public_id': DIRTY_RA, 'implementation_status': OTHER_LIST_OPTION,
             BEFORE: _matrix([_row(CATEGORY_A, True), _row(CATEGORY_MISSING, IMPACT_HIGH),
                              _row(CATEGORY_B, IMPACT_LOW), _row(CATEGORY_B, IMPACT_HIGH)], 0,
                             maximum_id=True, maximum_value=BASIS_HIGH, likelihood_value=0.0),
             AFTER: CLEAN_MATRIX},
            {'public_id': CLEAN_RA, 'implementation_status': STATE, BEFORE: CLEAN_MATRIX, AFTER: CLEAN_MATRIX})
    _insert(IsmsControlMeasure.COLLECTION, {'public_id': DIRTY_CM, 'implementation_state': MISSING_STATE},
            {'public_id': CLEAN_CM, 'implementation_state': None})
    _insert(IsmsControlMeasureAssignment.COLLECTION, {'public_id': STRICT_CMA, 'implementation_status': 0})

    def _read(collection: str, public_id: int) -> dict[str, Any]:
        return database_manager.get_collection(collection, database_name).find_one({'public_id': public_id},
                                                                                  {'_id': 0})

    yield _read
    _purge(database_manager, database_name)


def _snapshot(read: Any) -> list[dict[str, Any]]:
    """Every seeded document as stored"""
    return [read(collection, public_id) for collection, public_ids in SEEDED.items() for public_id in public_ids]


def test_the_migration_brings_the_dirty_documents_in_line_and_is_rerun_safe(
        database_manager: MongoDatabaseManager, database_name: str, collections: Any) -> None:
    """Dirty ones cleaned and re-derived, clean ones untouched, the second run a no-op"""
    clean_before: list[dict[str, Any]] = [collections(IsmsRiskAssessment.COLLECTION, CLEAN_RA),
                                          collections(IsmsControlMeasure.COLLECTION, CLEAN_CM),
                                          collections(IsmsControlMeasureAssignment.COLLECTION, STRICT_CMA)]

    Update20261109(database_manager, database_name).start_update()

    assessment: dict[str, Any] = collections(IsmsRiskAssessment.COLLECTION, DIRTY_RA)
    assert assessment[BEFORE] == _matrix([_row(CATEGORY_A, None), _row(CATEGORY_B, IMPACT_LOW)], None,
                                         IMPACT_LOW, BASIS_LOW, None)
    assert assessment[AFTER] == CLEAN_MATRIX
    assert assessment['implementation_status'] is None
    assert collections(IsmsControlMeasure.COLLECTION, DIRTY_CM)['implementation_state'] is None
    assert [collections(IsmsRiskAssessment.COLLECTION, CLEAN_RA),
            collections(IsmsControlMeasure.COLLECTION, CLEAN_CM),
            collections(IsmsControlMeasureAssignment.COLLECTION, STRICT_CMA)] == clean_before

    after_first_run: list[dict[str, Any]] = _snapshot(collections)

    Update20261109(database_manager, database_name).start_update()

    assert _snapshot(collections) == after_first_run
