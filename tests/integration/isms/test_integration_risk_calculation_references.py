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
Integration tests for the reads a RiskAssessment, ControlMeasureAssignment and ControlMeasure write resolves its
risk calculation and implementation states by, against a real MongoDB

- ``RiskAssessmentManager.get_missing_impact_category_ids`` answers exactly the named ImpactCategories not stored
- ``RiskAssessmentManager.load_calculation_bases`` reads both scales, and ``check_risk_calculation_references`` on top
  of them passes a stored calculation (answering those scales) and names an unknown Impact with its field path
- ``ExtendableOptionsManager.get_missing_option_ids`` counts an option of another list as missing
"""
from typing import Any, Iterator

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ExtendableOptionsManager
from cmdb.manager.isms_manager.isms_manager_helper import RiskCalculationBases
from cmdb.manager.isms_manager.risk_assessment_manager import RiskAssessmentManager
from cmdb.models.extendable_option_model import CmdbExtendableOption
from cmdb.models.extendable_option_model.option_type_enum import OptionType
from cmdb.models.isms_model import IsmsImpact, IsmsImpactCategory, IsmsLikelihood
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import (
    RISK_CALCULATION_REASON,
    UNKNOWN_RISK_CALCULATION_REFERENCES_MSG,
)
from cmdb.interface.rest_api.routes.isms_routes.risk_calculation_reference_helper import (
    check_risk_calculation_references,
)
# -------------------------------------------------------------------------------------------------------------------- #

CATEGORY: int = 943401
CATEGORY_MISSING: int = 943409
IMPACT: int = 943411
IMPACT_MISSING: int = 943419
LIKELIHOOD: int = 943421
STATE: int = 943431
OTHER_LIST_OPTION: int = 943432
MISSING_OPTION: int = 943439
BASIS_IMPACT: float = 2.0
BASIS_LIKELIHOOD: float = 3.0
HTTP_BAD_REQUEST: int = 400

SEEDED: dict[str, list[int]] = {
    IsmsImpactCategory.COLLECTION: [CATEGORY],
    IsmsImpact.COLLECTION: [IMPACT],
    IsmsLikelihood.COLLECTION: [LIKELIHOOD],
    CmdbExtendableOption.COLLECTION: [STATE, OTHER_LIST_OPTION],
}


def _purge(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """Removes every seeded document"""
    for collection, public_ids in SEEDED.items():
        database_manager.get_collection(collection, database_name).delete_many({'public_id': {'$in': public_ids}})


@pytest.fixture(name='seeded', autouse=True)
def fixture_seeded(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[None]:
    """One ImpactCategory, Impact, Likelihood, implementation state and option of another list; removed again"""
    _purge(database_manager, database_name)
    database_manager.get_collection(IsmsImpactCategory.COLLECTION, database_name).insert_one(
        {'public_id': CATEGORY, 'name': 'Integration category'})
    database_manager.get_collection(IsmsImpact.COLLECTION, database_name).insert_one(
        {'public_id': IMPACT, 'name': 'Integration impact', 'calculation_basis': BASIS_IMPACT})
    database_manager.get_collection(IsmsLikelihood.COLLECTION, database_name).insert_one(
        {'public_id': LIKELIHOOD, 'name': 'Integration likelihood', 'calculation_basis': BASIS_LIKELIHOOD})
    database_manager.get_collection(CmdbExtendableOption.COLLECTION, database_name).insert_many([
        {'public_id': STATE, 'value': 'Integration state 943431',
         'option_type': OptionType.IMPLEMENTATION_STATE.value},
        {'public_id': OTHER_LIST_OPTION, 'value': 'Integration risk category 943432',
         'option_type': OptionType.RISK.value},
    ])
    yield
    _purge(database_manager, database_name)


@pytest.fixture(name='manager')
def fixture_manager(database_manager: MongoDatabaseManager) -> RiskAssessmentManager:
    """A RiskAssessmentManager of the test database"""
    return RiskAssessmentManager(database_manager)


def _payload(impact: int, likelihood: int | None = None) -> dict[str, Any]:
    """A payload with one rated row before treatment and nothing after"""
    return {
        'risk_calculation_before': {'impacts': [{'impact_category_id': CATEGORY, 'impact_id': impact}],
                                    'likelihood_id': likelihood},
        'risk_calculation_after': {'impacts': [], 'likelihood_id': None},
    }


class TestImpactCategories:
    """get_missing_impact_category_ids"""

    def test_only_the_absent_ids_are_missing(self, manager: RiskAssessmentManager) -> None:
        """Stored never, absent always"""
        assert manager.get_missing_impact_category_ids({CATEGORY, CATEGORY_MISSING}) == {CATEGORY_MISSING}

    def test_no_ids_answer_none(self, manager: RiskAssessmentManager) -> None:
        """Nothing named"""
        assert manager.get_missing_impact_category_ids(set()) == set()


class TestTheScalesAndTheCheck:
    """load_calculation_bases and check_risk_calculation_references on top of it"""

    def test_both_scales_are_read(self, manager: RiskAssessmentManager) -> None:
        """Each seeded entry with its basis"""
        bases: RiskCalculationBases = manager.load_calculation_bases()

        assert (bases.impact[IMPACT], bases.likelihood[LIKELIHOOD]) == (BASIS_IMPACT, BASIS_LIKELIHOOD)

    def test_a_stored_calculation_passes_and_derives_from_the_answered_scales(
            self, manager: RiskAssessmentManager) -> None:
        """The same scales feed the recalculation"""
        payload: dict[str, Any] = _payload(IMPACT, LIKELIHOOD)

        manager.recalculate_risk_values(payload, check_risk_calculation_references(manager, payload))

        before: dict[str, Any] = payload['risk_calculation_before']
        assert (before['maximum_impact_id'], before['maximum_impact_value'], before['likelihood_value']) == (
            IMPACT, BASIS_IMPACT, BASIS_LIKELIHOOD,
        )

    def test_an_unknown_impact_is_named_with_its_field_path(self, manager: RiskAssessmentManager) -> None:
        """The 400 the routes answer"""
        with pytest.raises(HTTPException) as raised:
            check_risk_calculation_references(manager, _payload(IMPACT_MISSING))

        assert raised.value.code == HTTP_BAD_REQUEST
        assert raised.value.description == UNKNOWN_RISK_CALCULATION_REFERENCES_MSG.format(
            reasons=RISK_CALCULATION_REASON.format(field='risk_calculation_before.impacts.impact_id',
                                                   ids=[IMPACT_MISSING]),
        )


class TestOptionsOfOneList:
    """ExtendableOptionsManager.get_missing_option_ids"""

    def test_an_option_of_another_list_counts_as_missing(self, database_manager: MongoDatabaseManager) -> None:
        """As does an id no option carries; the state itself never"""
        options = ExtendableOptionsManager(database_manager)

        assert options.get_missing_option_ids(
            OptionType.IMPLEMENTATION_STATE.value, {STATE, OTHER_LIST_OPTION, MISSING_OPTION},
        ) == {OTHER_LIST_OPTION, MISSING_OPTION}
