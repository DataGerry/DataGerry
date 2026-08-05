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
Integration test for ControlMeasureManager.is_control_measure_used, run against the bound collections.

The helper is a cross-collection read: it reports whether any IsmsControlMeasureAssignment references
the control measure via its control_measure_id.
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.isms_manager.control_measure_manager import ControlMeasureManager
from cmdb.models.isms_model import IsmsControlMeasure, IsmsControlMeasureAssignment
# -------------------------------------------------------------------------------------------------------------------- #

CONTROL_MEASURE_ID: int = 98201
CONTROL_ASSIGNMENT_ID: int = 98202

ALL_CONTROL_MEASURE_IDS: list[int] = [CONTROL_MEASURE_ID]
ALL_CONTROL_ASSIGNMENT_IDS: list[int] = [CONTROL_ASSIGNMENT_ID]


@pytest.fixture(name='control_measure_manager')
def fixture_control_measure_manager(database_manager: MongoDatabaseManager) -> ControlMeasureManager:
    """Provides a ControlMeasureManager wired to the test database."""
    return ControlMeasureManager(database_manager)


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any control measures / assignments seeded by a test, before and after each test."""
    def _purge() -> None:
        database_manager.get_collection(IsmsControlMeasure.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_CONTROL_MEASURE_IDS}})
        database_manager.get_collection(IsmsControlMeasureAssignment.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_CONTROL_ASSIGNMENT_IDS}})

    _purge()
    yield
    _purge()


def _insert(database_manager: MongoDatabaseManager, database_name: str,
            collection: str, doc: dict[str, Any]) -> None:
    """Inserts a document directly via the given collection."""
    database_manager.get_collection(collection, database_name).insert_one(doc)


class TestIsControlMeasureUsed:
    """is_control_measure_used reports whether any assignment references the control measure."""

    def test_true_when_referenced_by_assignment(self, control_measure_manager: ControlMeasureManager,
                                                database_manager: MongoDatabaseManager,
                                                database_name: str) -> None:
        """A ControlMeasure referenced by an assignment returns True."""
        _insert(database_manager, database_name, IsmsControlMeasureAssignment.COLLECTION,
                {'public_id': CONTROL_ASSIGNMENT_ID, 'control_measure_id': CONTROL_MEASURE_ID})

        assert control_measure_manager.is_control_measure_used(CONTROL_MEASURE_ID) is True

    def test_false_when_not_referenced(self, control_measure_manager: ControlMeasureManager) -> None:
        """A ControlMeasure no assignment references returns False."""
        assert control_measure_manager.is_control_measure_used(CONTROL_MEASURE_ID) is False
