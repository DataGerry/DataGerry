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
Unit tests for is_risk_data_valid (risk_routes)

The helper is pure (no database): it checks that the risk_type is known and that the extra fields
required for that risk_type are present - threats (+ vulnerabilities) for the threat variants,
consequences + description for events.
"""
from typing import Any

from cmdb.interface.rest_api.routes.isms_routes.risk_routes import is_risk_data_valid
from cmdb.models.isms_model import RiskType
# -------------------------------------------------------------------------------------------------------------------- #

RISK_TYPE_KEY: str = 'risk_type'
THREATS_KEY: str = 'threats'
VULNERABILITIES_KEY: str = 'vulnerabilities'
CONSEQUENCES_KEY: str = 'consequences'
DESCRIPTION_KEY: str = 'description'


def _data(**fields: Any) -> dict[str, Any]:
    """Builds a risk-data dict from the given fields."""
    return dict(fields)


class TestIsRiskDataValidType:
    """An unknown or missing risk_type is always invalid."""

    def test_missing_risk_type_is_invalid(self) -> None:
        """Data with no risk_type is rejected."""
        assert is_risk_data_valid(_data()) is False

    def test_unknown_risk_type_is_invalid(self) -> None:
        """Data with an unrecognised risk_type is rejected."""
        assert is_risk_data_valid(_data(risk_type='SOMETHING_ELSE')) is False


class TestIsRiskDataValidThreatXVulnerability:
    """THREAT_X_VULNERABILITY requires both threats and vulnerabilities."""

    def test_valid_with_threats_and_vulnerabilities(self) -> None:
        """Both lists present -> valid."""
        data = _data(risk_type=RiskType.THREAT_X_VULNERABILITY, threats=[1], vulnerabilities=[2])

        assert is_risk_data_valid(data) is True

    def test_invalid_without_vulnerabilities(self) -> None:
        """Missing vulnerabilities -> invalid."""
        data = _data(risk_type=RiskType.THREAT_X_VULNERABILITY, threats=[1])

        assert is_risk_data_valid(data) is False

    def test_invalid_without_threats(self) -> None:
        """Missing threats -> invalid."""
        data = _data(risk_type=RiskType.THREAT_X_VULNERABILITY, vulnerabilities=[2])

        assert is_risk_data_valid(data) is False


class TestIsRiskDataValidThreat:
    """THREAT requires threats only (description is not enforced)."""

    def test_valid_with_threats(self) -> None:
        """Threats present -> valid, even without a description."""
        assert is_risk_data_valid(_data(risk_type=RiskType.THREAT, threats=[1])) is True

    def test_invalid_without_threats(self) -> None:
        """Missing threats -> invalid."""
        assert is_risk_data_valid(_data(risk_type=RiskType.THREAT)) is False


class TestIsRiskDataValidEvent:
    """EVENT requires both consequences and description."""

    def test_valid_with_consequences_and_description(self) -> None:
        """Both fields present -> valid."""
        data = _data(risk_type=RiskType.EVENT, consequences='c', description='d')

        assert is_risk_data_valid(data) is True

    def test_invalid_without_consequences(self) -> None:
        """Missing consequences -> invalid."""
        assert is_risk_data_valid(_data(risk_type=RiskType.EVENT, description='d')) is False

    def test_invalid_without_description(self) -> None:
        """Missing description -> invalid."""
        assert is_risk_data_valid(_data(risk_type=RiskType.EVENT, consequences='c')) is False
