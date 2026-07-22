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
Functional smoke for the ``/isms/reports`` routes

Each report GET drives a full aggregation pipeline (or the RiskMatrix report builder) plus the
object-summary post-processing. These smoke tests assert the routes wire up and respond 200 with a
parseable body; the report contents are exercised against whatever ISMS data is present. The SOA
test additionally checks that the extendable-option ids are resolved to their labels. The routes
are ISMS-license gated, so the check is stubbed.
"""
from http import HTTPStatus

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.isms_model import IsmsControlMeasure
from cmdb.models.extendable_option_model import CmdbExtendableOption, OptionType
from cmdb.security.license.license_constants import LicenseFeature
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/isms/reports'
LIST_REPORTS: list[str] = ['risk_treatment_plan', 'soa', 'risk_assessments']

# SOA-specific fixtures: a control measure whose source / implementation_state ids get resolved to labels
SOA_CM_ID: int = 99401
SOA_SOURCE_OPTION_ID: int = 99402
SOA_STATE_OPTION_ID: int = 99403
SOA_SOURCE_VALUE: str = 'ImportTest ISO Source'
SOA_STATE_VALUE: str = 'ImportTest Implemented State'


@pytest.fixture(autouse=True)
def _isms_licensed(monkeypatch: pytest.MonkeyPatch):
    """Licenses the ISMS feature so the gated report routes are reachable."""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.ISMS)


class TestIsmsReports:
    """Every ISMS report route responds 200 with a parseable body."""

    def test_risk_matrix_report_responds(self, rest_api) -> None:
        """The RiskMatrix report returns 200 with a dict body (builder guards missing data)."""
        response = rest_api.get(f'{ROUTE_URL}/risk_matrix')

        assert response.status_code == HTTPStatus.OK
        assert isinstance(response.get_json(), dict)

    @pytest.mark.parametrize('report', LIST_REPORTS)
    def test_list_report_responds(self, rest_api, report: str) -> None:
        """The list-shaped reports (treatment plan / SOA / risk assessments) return 200 with a list."""
        response = rest_api.get(f'{ROUTE_URL}/{report}')

        assert response.status_code == HTTPStatus.OK
        assert isinstance(response.get_json(), list)

    def test_soa_resolves_option_ids_to_values(self, rest_api,
                                               database_manager: MongoDatabaseManager, database_name: str) -> None:
        """SOA replaces the control measure's source / implementation_state ids with their option labels."""
        options = database_manager.get_collection(CmdbExtendableOption.COLLECTION, database_name)
        measures = database_manager.get_collection(IsmsControlMeasure.COLLECTION, database_name)
        options.insert_one({'public_id': SOA_SOURCE_OPTION_ID, 'value': SOA_SOURCE_VALUE,
                            'option_type': OptionType.CONTROL_MEASURE, 'predefined': False})
        options.insert_one({'public_id': SOA_STATE_OPTION_ID, 'value': SOA_STATE_VALUE,
                            'option_type': OptionType.IMPLEMENTATION_STATE, 'predefined': False})
        measures.insert_one({'public_id': SOA_CM_ID, 'title': 'SOA CM', 'control_measure_type': 'CONTROL',
                             'source': SOA_SOURCE_OPTION_ID, 'implementation_state': SOA_STATE_OPTION_ID})
        try:
            response = rest_api.get(f'{ROUTE_URL}/soa')

            assert response.status_code == HTTPStatus.OK
            entry = next(cm for cm in response.get_json() if cm['public_id'] == SOA_CM_ID)
            assert entry['source'] == SOA_SOURCE_VALUE
            assert entry['implementation_state'] == SOA_STATE_VALUE
        finally:
            options.delete_many({'public_id': {'$in': [SOA_SOURCE_OPTION_ID, SOA_STATE_OPTION_ID]}})
            measures.delete_one({'public_id': SOA_CM_ID})
