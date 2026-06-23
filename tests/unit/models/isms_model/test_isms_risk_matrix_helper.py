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
Unit tests for ensure_default_risk_matrix (RiskMatrix singleton self-heal)

Isolates the helper from Mongo with a stub manager: when the singleton (public_id 1) already
exists it is returned untouched and nothing is inserted; when it is missing the embedded default
is inserted (pinned to public_id 1, empty cell list, no unit) and the recreated document returned
"""
from typing import Any, Optional

from cmdb.models.isms_model.isms_helper import ensure_default_risk_matrix
from cmdb.database.predefined_data.predefined_data_constants import RiskMatrixKey
# -------------------------------------------------------------------------------------------------------------------- #

EXISTING_MATRIX_ID: int = 1


class _StubRiskMatrixManager:
    """
    Stub RiskMatrixManager recording inserts and serving a configurable get_item result

    get_item returns ``initial`` until an insert happens, then serves the inserted document, so a
    single instance models both the "already present" and "missing then recreated" flows
    """

    def __init__(self, initial: Optional[dict[str, Any]]) -> None:
        self._current: Optional[dict[str, Any]] = initial
        self.inserted: list[dict[str, Any]] = []

    def get_item(self, public_id: int, as_dict: bool = False) -> Optional[dict[str, Any]]:
        """Returns the current document for public_id 1, else None"""
        return self._current if public_id == EXISTING_MATRIX_ID else None

    def insert_item(self, document: dict[str, Any]) -> int:
        """Records the insert and makes the document the new current matrix"""
        self.inserted.append(document)
        self._current = document

        return document[RiskMatrixKey.PUBLIC_ID]


def test_returns_existing_matrix_without_inserting() -> None:
    """When the singleton already exists it is returned as-is and no insert is performed"""
    existing: dict[str, Any] = {
        RiskMatrixKey.PUBLIC_ID: EXISTING_MATRIX_ID,
        RiskMatrixKey.RISK_MATRIX: [{'risk_class_id': 2}],
        RiskMatrixKey.MATRIX_UNIT: 'EUR',
    }
    manager = _StubRiskMatrixManager(existing)

    result = ensure_default_risk_matrix(manager)

    assert result is existing
    assert manager.inserted == []


def test_creates_default_matrix_when_missing() -> None:
    """When the singleton is missing the empty default is inserted at public_id 1 and returned"""
    manager = _StubRiskMatrixManager(None)

    result = ensure_default_risk_matrix(manager)

    assert len(manager.inserted) == 1
    assert result[RiskMatrixKey.PUBLIC_ID] == EXISTING_MATRIX_ID
    assert result[RiskMatrixKey.RISK_MATRIX] == []
    assert result[RiskMatrixKey.MATRIX_UNIT] is None
