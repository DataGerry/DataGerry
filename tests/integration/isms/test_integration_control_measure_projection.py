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
Integration tests for the projected control-measure read the SOA report is built from

``BaseManager.get_many`` hands a projection to the driver, so the SOA reads only its columns from the
bound collection - the stored free-text description stays in the database.
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.isms_manager.control_measure_manager import ControlMeasureManager
from cmdb.models.isms_model import IsmsControlMeasure
from cmdb.interface.rest_api.routes.isms_routes.isms_report_routes import SOA_PROJECTION
# -------------------------------------------------------------------------------------------------------------------- #

CONTROL_MEASURE_ID: int = 98951
# Stored option ids; the manager read does not resolve them, so their values do not matter
STATE_OPTION_ID: int = 98952
SOURCE_OPTION_ID: int = 98953

STORED_CONTROL_MEASURE: dict[str, Any] = {
    'public_id': CONTROL_MEASURE_ID,
    'title': 'Projection CM',
    'control_measure_type': 'CONTROL',
    'identifier': 'PR.1',
    'chapter': 'PR',
    'is_applicable': True,
    'reason': 'Projection reason',
    'implementation_state': STATE_OPTION_ID,
    'source': SOURCE_OPTION_ID,
    'description': 'A free-text description the SOA does not read',
}


@pytest.fixture(name='control_measure_manager')
def fixture_control_measure_manager(database_manager: MongoDatabaseManager) -> ControlMeasureManager:
    """Provides a ControlMeasureManager wired to the test database."""
    return ControlMeasureManager(database_manager)


@pytest.fixture(autouse=True)
def _seeded_control_measure(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds one control measure carrying every stored key, and removes it afterwards."""
    measures = database_manager.get_collection(IsmsControlMeasure.COLLECTION, database_name)
    measures.delete_one({'public_id': CONTROL_MEASURE_ID})
    measures.insert_one(dict(STORED_CONTROL_MEASURE))
    yield
    measures.delete_one({'public_id': CONTROL_MEASURE_ID})


def _seeded_row(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Returns the seeded control measure out of a read of the whole collection."""
    return next(row for row in rows if row['public_id'] == CONTROL_MEASURE_ID)


def test_the_soa_projection_reads_only_the_report_columns(control_measure_manager: ControlMeasureManager) -> None:
    """The projected read returns the SOA columns with their stored values, and nothing else"""
    row = _seeded_row(control_measure_manager.get_many(projection=SOA_PROJECTION))

    expected = {key: value for key, value in STORED_CONTROL_MEASURE.items() if SOA_PROJECTION.get(key) == 1}
    assert row == expected


def test_an_unprojected_read_still_returns_the_whole_document(
        control_measure_manager: ControlMeasureManager) -> None:
    """Without a projection get_many keeps its old answer: every stored key except `_id`"""
    row = _seeded_row(control_measure_manager.get_many())

    assert row == STORED_CONTROL_MEASURE
