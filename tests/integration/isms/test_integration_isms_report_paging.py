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
Integration tests for ``read_report_page`` against a real MongoDB, through the real RiskAssessmentManager

The one-pass ``$facet`` read of a bounded page and the cursor reads of an export and of a page above
``REPORT_FACET_MAX_LIMIT`` must agree row for row and on the total. The bound is lowered for the cursor cases so
a handful of seeded assessments is enough.
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_constants import MONGO_ID_FIELD
from cmdb.manager.isms_manager.risk_assessment_manager import RiskAssessmentManager
from cmdb.models.isms_model import IsmsRiskAssessment
from cmdb.utils import Builder
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.rest_api.routes.isms_routes import isms_report_helper
from cmdb.interface.rest_api.routes.isms_routes.isms_report_helper import read_report_page
# -------------------------------------------------------------------------------------------------------------------- #

BASE_ID: int = 99670
SEEDED_COUNT: int = 5
SEEDED_IDS: list[int] = list(range(BASE_ID, BASE_ID + SEEDED_COUNT))
# The display field the test pipeline projects - descending against public_id, so a sort mix-up shows
DISPLAY_KEY: str = 'display'
TEST_FACET_BOUND: int = 1
PAGE_SIZE: int = 2
# With five rows at two per page: page 2 is full, page 3 holds the one last row, page 4 is past the end
FULL_PAGE: int = 2
LAST_PAGE: int = 3
PAST_THE_END_PAGE: int = 4


@pytest.fixture(name='manager')
def fixture_manager(database_manager: MongoDatabaseManager, database_name: str):
    """A RiskAssessmentManager over SEEDED_COUNT bare assessments, removed again"""
    assessments = database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)
    assessments.delete_many({'public_id': {'$in': SEEDED_IDS}})
    assessments.insert_many([{'public_id': public_id, 'priority': -public_id} for public_id in SEEDED_IDS])

    yield RiskAssessmentManager(database_manager)

    assessments.delete_many({'public_id': {'$in': SEEDED_IDS}})


def _pipeline() -> list[dict[str, Any]]:
    """The seeded assessments, projected the way a report projects its display fields"""
    return [
        Builder.match_({'public_id': {'$in': SEEDED_IDS}}),
        Builder.project_({MONGO_ID_FIELD: 0, 'public_id': 1, DISPLAY_KEY: '$priority'}),
    ]


def _params(limit: int | str, page: int = 1) -> CollectionParameters:
    """Paging parameters sorted by the display field, ascending"""
    return CollectionParameters('', limit=limit, page=page, sort=DISPLAY_KEY, order=1)


def _all_rows() -> list[dict[str, Any]]:
    """Every seeded row in the order the display sort gives, without the public_id tiebreaker"""
    return [{DISPLAY_KEY: -public_id} for public_id in reversed(SEEDED_IDS)]


def test_the_export_reads_every_row_sorted(manager: RiskAssessmentManager) -> None:
    """limit=0: every row, in sort order, public_id dropped, and their number as the total"""
    assert read_report_page(manager, _pipeline(), _params('0')) == (_all_rows(), SEEDED_COUNT)


def test_a_bounded_page_reads_through_the_facet(manager: RiskAssessmentManager) -> None:
    """The one-pass read: the requested window and the full count"""
    rows, total = read_report_page(manager, _pipeline(), _params(PAGE_SIZE, FULL_PAGE))

    assert rows == _all_rows()[PAGE_SIZE:2 * PAGE_SIZE]
    assert total == SEEDED_COUNT


@pytest.mark.parametrize('page', [FULL_PAGE, LAST_PAGE, PAST_THE_END_PAGE])
def test_a_page_above_the_bound_matches_the_facet(manager: RiskAssessmentManager, monkeypatch, page: int) -> None:
    """Full, last and past-the-end pages read through a cursor answer what the facet answers"""
    expected: tuple[list[dict[str, Any]], int] = read_report_page(manager, _pipeline(), _params(PAGE_SIZE, page))
    monkeypatch.setattr(isms_report_helper, 'REPORT_FACET_MAX_LIMIT', TEST_FACET_BOUND)

    assert read_report_page(manager, _pipeline(), _params(PAGE_SIZE, page)) == expected
    assert expected[1] == SEEDED_COUNT


def test_an_empty_result_is_zero(manager: RiskAssessmentManager, monkeypatch) -> None:
    """No row matches: no rows and a total of 0 on every path"""
    empty: list[dict[str, Any]] = [Builder.match_({'public_id': {'$in': []}})]
    monkeypatch.setattr(isms_report_helper, 'REPORT_FACET_MAX_LIMIT', TEST_FACET_BOUND)

    assert read_report_page(manager, empty, _params('0')) == ([], 0)
    assert read_report_page(manager, empty, _params(PAGE_SIZE, FULL_PAGE)) == ([], 0)
