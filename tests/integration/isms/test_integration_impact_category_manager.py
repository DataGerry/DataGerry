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
Integration tests for the ImpactCategoryManager database-backed follow-up methods.

Covers ``create_with_follow_up`` (pushes a placeholder impact entry into every RiskAssessment),
``delete_with_follow_up`` (drops the category from every RiskAssessment and recomputes the maximum
impact from the IsmsImpact collection - the recompute must not wipe the maximum while other impacts
remain), and the ImpactCategory-side impact fan-out helpers ``add_new_impact_to_categories`` /
``remove_deleted_impact_from_categories``.
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.isms_manager.impact_category_manager import ImpactCategoryManager
from cmdb.models.isms_model import IsmsImpact, IsmsImpactCategory, IsmsRiskAssessment
# -------------------------------------------------------------------------------------------------------------------- #

IMPACT_LOW: int = 95501
IMPACT_HIGH: int = 95502
CATEGORY_A: int = 95511
CATEGORY_B: int = 95512
RISK_ASSESSMENT_ID: int = 95521

BASIS_LOW: float = 1.0
BASIS_HIGH: float = 3.0

ALL_IMPACT_IDS: list[int] = [IMPACT_LOW, IMPACT_HIGH]
ALL_CATEGORY_IDS: list[int] = [CATEGORY_A, CATEGORY_B]
ALL_RISK_ASSESSMENT_IDS: list[int] = [RISK_ASSESSMENT_ID]


@pytest.fixture(name='impact_category_manager')
def fixture_impact_category_manager(database_manager: MongoDatabaseManager) -> ImpactCategoryManager:
    """Provides an ImpactCategoryManager wired to the test database."""
    return ImpactCategoryManager(database_manager)


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any impacts / categories / risk assessments seeded by a test, before and after each test."""
    def _purge() -> None:
        database_manager.get_collection(IsmsImpact.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_IMPACT_IDS}})
        database_manager.get_collection(IsmsImpactCategory.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_CATEGORY_IDS}})
        database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_RISK_ASSESSMENT_IDS}})

    _purge()
    yield
    _purge()


def _insert(database_manager: MongoDatabaseManager, database_name: str,
            collection: str, doc: dict[str, Any]) -> None:
    """Inserts a document directly via the given collection."""
    database_manager.get_collection(collection, database_name).insert_one(doc)


def _risk_assessment(database_manager: MongoDatabaseManager, database_name: str) -> dict[str, Any]:
    """Returns the seeded IsmsRiskAssessment document."""
    return database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)\
        .find_one({'public_id': RISK_ASSESSMENT_ID})


def _category(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> dict[str, Any]:
    """Returns a seeded IsmsImpactCategory document."""
    return database_manager.get_collection(IsmsImpactCategory.COLLECTION, database_name)\
        .find_one({'public_id': public_id})


def _seed_two_category_risk_assessment(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """
    Seeds two Impacts, two ImpactCategories and one RiskAssessment.

    In both matrices category A points at the low-basis Impact and category B at the high-basis
    Impact, so the recorded maximum is the high-basis Impact.
    """
    _insert(database_manager, database_name, IsmsImpact.COLLECTION,
            {'public_id': IMPACT_LOW, 'name': 'Low', 'calculation_basis': BASIS_LOW})
    _insert(database_manager, database_name, IsmsImpact.COLLECTION,
            {'public_id': IMPACT_HIGH, 'name': 'High', 'calculation_basis': BASIS_HIGH})
    _insert(database_manager, database_name, IsmsImpactCategory.COLLECTION,
            {'public_id': CATEGORY_A, 'name': 'A', 'impact_descriptions': [], 'sort': 1})
    _insert(database_manager, database_name, IsmsImpactCategory.COLLECTION,
            {'public_id': CATEGORY_B, 'name': 'B', 'impact_descriptions': [], 'sort': 2})

    matrix = {
        'impacts': [
            {'impact_category_id': CATEGORY_A, 'impact_id': IMPACT_LOW},
            {'impact_category_id': CATEGORY_B, 'impact_id': IMPACT_HIGH},
        ],
        'maximum_impact_id': IMPACT_HIGH,
        'maximum_impact_value': BASIS_HIGH,
    }
    _insert(database_manager, database_name, IsmsRiskAssessment.COLLECTION, {
        'public_id': RISK_ASSESSMENT_ID,
        'risk_calculation_before': {**matrix, 'impacts': list(matrix['impacts'])},
        'risk_calculation_after': {**matrix, 'impacts': list(matrix['impacts'])},
    })


class TestCreateWithFollowUp:
    """create_with_follow_up inserts the category and references it in every RiskAssessment."""

    def test_pushes_placeholder_entry_into_both_matrices(self, impact_category_manager: ImpactCategoryManager,
                                                         database_manager: MongoDatabaseManager,
                                                         database_name: str) -> None:
        """A newly created category is appended (with impact_id None) to both risk-calculation matrices."""
        _insert(database_manager, database_name, IsmsRiskAssessment.COLLECTION, {
            'public_id': RISK_ASSESSMENT_ID,
            'risk_calculation_before': {'impacts': []},
            'risk_calculation_after': {'impacts': []},
        })

        new_id = impact_category_manager.create_with_follow_up(
            {'public_id': CATEGORY_A, 'name': 'A', 'impact_descriptions': [], 'sort': 1}
        )
        assert new_id == CATEGORY_A

        risk_assessment = _risk_assessment(database_manager, database_name)
        for matrix_key in ('risk_calculation_before', 'risk_calculation_after'):
            impacts = risk_assessment[matrix_key]['impacts']
            assert impacts == [{'impact_category_id': CATEGORY_A, 'impact_id': None}]


class TestDeleteWithFollowUp:
    """delete_with_follow_up removes the category and recomputes the maximum from IsmsImpact."""

    def test_recomputes_maximum_from_remaining_impact(self, impact_category_manager: ImpactCategoryManager,
                                                      database_manager: MongoDatabaseManager,
                                                      database_name: str) -> None:
        """Deleting the high-basis category leaves the low-basis Impact as the new maximum (not None)."""
        _seed_two_category_risk_assessment(database_manager, database_name)

        assert impact_category_manager.delete_with_follow_up(CATEGORY_B) is True

        risk_assessment = _risk_assessment(database_manager, database_name)
        for matrix_key in ('risk_calculation_before', 'risk_calculation_after'):
            matrix = risk_assessment[matrix_key]
            assert matrix['impacts'] == [{'impact_category_id': CATEGORY_A, 'impact_id': IMPACT_LOW}]
            assert matrix['maximum_impact_id'] == IMPACT_LOW
            assert matrix['maximum_impact_value'] == BASIS_LOW

        assert _category(database_manager, database_name, CATEGORY_B) is None

    def test_maximum_becomes_none_when_no_impacts_remain(self, impact_category_manager: ImpactCategoryManager,
                                                        database_manager: MongoDatabaseManager,
                                                        database_name: str) -> None:
        """Deleting the only referenced category clears the maximum to None."""
        _insert(database_manager, database_name, IsmsImpact.COLLECTION,
                {'public_id': IMPACT_HIGH, 'name': 'High', 'calculation_basis': BASIS_HIGH})
        _insert(database_manager, database_name, IsmsImpactCategory.COLLECTION,
                {'public_id': CATEGORY_A, 'name': 'A', 'impact_descriptions': [], 'sort': 1})
        _insert(database_manager, database_name, IsmsRiskAssessment.COLLECTION, {
            'public_id': RISK_ASSESSMENT_ID,
            'risk_calculation_before': {
                'impacts': [{'impact_category_id': CATEGORY_A, 'impact_id': IMPACT_HIGH}],
                'maximum_impact_id': IMPACT_HIGH,
                'maximum_impact_value': BASIS_HIGH,
            },
            'risk_calculation_after': {
                'impacts': [{'impact_category_id': CATEGORY_A, 'impact_id': IMPACT_HIGH}],
                'maximum_impact_id': IMPACT_HIGH,
                'maximum_impact_value': BASIS_HIGH,
            },
        })

        impact_category_manager.delete_with_follow_up(CATEGORY_A)

        risk_assessment = _risk_assessment(database_manager, database_name)
        for matrix_key in ('risk_calculation_before', 'risk_calculation_after'):
            matrix = risk_assessment[matrix_key]
            assert matrix['impacts'] == []
            assert matrix['maximum_impact_id'] is None
            assert matrix['maximum_impact_value'] is None


class TestImpactFanOut:
    """add_new_impact_to_categories / remove_deleted_impact_from_categories keep categories in sync."""

    def test_add_and_remove_impact_description(self, impact_category_manager: ImpactCategoryManager,
                                              database_manager: MongoDatabaseManager,
                                              database_name: str) -> None:
        """A new Impact adds a description entry to every category; deleting it removes the entry again."""
        _insert(database_manager, database_name, IsmsImpactCategory.COLLECTION,
                {'public_id': CATEGORY_A, 'name': 'A', 'impact_descriptions': [], 'sort': 1})
        _insert(database_manager, database_name, IsmsImpactCategory.COLLECTION,
                {'public_id': CATEGORY_B, 'name': 'B', 'impact_descriptions': [], 'sort': 2})

        impact_category_manager.add_new_impact_to_categories(IMPACT_HIGH)

        for category_id in ALL_CATEGORY_IDS:
            descriptions = _category(database_manager, database_name, category_id)['impact_descriptions']
            assert {'impact_id': IMPACT_HIGH, 'value': '-'} in descriptions

        impact_category_manager.remove_deleted_impact_from_categories(IMPACT_HIGH)

        for category_id in ALL_CATEGORY_IDS:
            descriptions = _category(database_manager, database_name, category_id)['impact_descriptions']
            assert all(entry['impact_id'] != IMPACT_HIGH for entry in descriptions)
