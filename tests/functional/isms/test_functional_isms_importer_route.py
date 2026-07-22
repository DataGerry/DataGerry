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
Functional smoke for the ``/isms/importer/<target>`` CSV import route

Covers the four import targets (threat / vulnerability / control_measure / risk) end-to-end - a
posted CSV is parsed, validated, de-duplicated and inserted - plus the route guards (invalid target,
missing file, missing headers) and the de-duplication counting. The route is ISMS-license gated, so
the check is stubbed.
"""
import io
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.isms_model import (
    IsmsThreat,
    IsmsVulnerability,
    IsmsControlMeasure,
    IsmsRisk,
    IsmsProtectionGoal,
)
from cmdb.security.license.license_constants import LicenseFeature
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/isms/importer'
FILE_KEY: str = 'file'

# Unique markers so cleanup only removes what these tests created
THREAT_NAME: str = 'ImportTest Threat'
VULNERABILITY_NAME: str = 'ImportTest Vulnerability'
CONTROL_MEASURE_TITLE: str = 'ImportTest Control'
RISK_NAME: str = 'ImportTest Risk'

THREAT_CSV: str = f'name,source,identifier,description\n{THREAT_NAME},,,\n'
VULNERABILITY_CSV: str = f'name,source,identifier,description\n{VULNERABILITY_NAME},,,\n'
CONTROL_MEASURE_CSV: str = (
    'title,control_measure_type,source,implementation_state,identifier,chapter,description,is_applicable,reason\n'
    f'{CONTROL_MEASURE_TITLE},CONTROL,,,,,,true,\n'
)
# EVENT risks need consequences + description and no threats / vulnerabilities (keeps the import self-contained)
RISK_CSV: str = (
    'name,risk_type,protection_goals,threats,vulnerabilities,identifier,consequences,description\n'
    f'{RISK_NAME},EVENT,,,,,A consequence,A description\n'
)

# A THREAT_X_VULNERABILITY risk resolves (and auto-creates) its threats / vulnerabilities / goals by name
TXV_RISK_NAME: str = 'ImportTest TXV Risk'
TXV_THREAT_NAME: str = 'ImportTest TXV Threat'
TXV_VULNERABILITY_NAME: str = 'ImportTest TXV Vulnerability'
TXV_GOAL_NAME: str = 'ImportTest TXV Goal'
TXV_RISK_CSV: str = (
    'name,risk_type,protection_goals,threats,vulnerabilities,identifier,consequences,description\n'
    f'{TXV_RISK_NAME},THREAT_X_VULNERABILITY,{TXV_GOAL_NAME},{TXV_THREAT_NAME},{TXV_VULNERABILITY_NAME},,,\n'
)


@pytest.fixture(autouse=True)
def _isms_licensed(monkeypatch: pytest.MonkeyPatch):
    """Licenses the ISMS feature so the gated importer route is reachable."""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.ISMS)


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any objects the imports created, before and after each test."""
    def _purge() -> None:
        database_manager.get_collection(IsmsThreat.COLLECTION, database_name).delete_many({'name': THREAT_NAME})
        database_manager.get_collection(IsmsVulnerability.COLLECTION, database_name)\
            .delete_many({'name': VULNERABILITY_NAME})
        database_manager.get_collection(IsmsControlMeasure.COLLECTION, database_name)\
            .delete_many({'title': CONTROL_MEASURE_TITLE})
        database_manager.get_collection(IsmsRisk.COLLECTION, database_name).delete_many({'name': RISK_NAME})
        database_manager.get_collection(IsmsRisk.COLLECTION, database_name).delete_many({'name': TXV_RISK_NAME})
        database_manager.get_collection(IsmsThreat.COLLECTION, database_name).delete_many({'name': TXV_THREAT_NAME})
        database_manager.get_collection(IsmsVulnerability.COLLECTION, database_name)\
            .delete_many({'name': TXV_VULNERABILITY_NAME})
        database_manager.get_collection(IsmsProtectionGoal.COLLECTION, database_name)\
            .delete_many({'name': TXV_GOAL_NAME})

    _purge()
    yield
    _purge()


def _post_csv(rest_api, target: str, csv_text: str):
    """Posts a CSV file to the importer route for the given target."""
    return rest_api.post(
        f'{ROUTE_URL}/{target}',
        data={FILE_KEY: (io.BytesIO(csv_text.encode('utf-8')), 'import.csv')},
        content_type='multipart/form-data',
    )


def _count(database_manager: MongoDatabaseManager, database_name: str, collection: str, criteria: dict) -> int:
    """Counts documents matching the criteria in the collection."""
    return database_manager.get_collection(collection, database_name).count_documents(criteria)


class TestImportThreats:
    """POST /isms/importer/threat imports IsmsThreats from a CSV."""

    def test_creates_threat(self, rest_api, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A valid threat row is created and reported in the result counts."""
        response = _post_csv(rest_api, 'threat', THREAT_CSV)

        assert response.status_code == HTTPStatus.OK
        body: dict[str, Any] = response.get_json()
        assert body['created_objects'] == 1
        assert body['imported_objects'] == 1
        assert _count(database_manager, database_name, IsmsThreat.COLLECTION, {'name': THREAT_NAME}) == 1

    def test_reimport_counts_as_existing(self, rest_api,
                                        database_manager: MongoDatabaseManager, database_name: str) -> None:
        """Re-importing the same threat reports it as existing and creates no duplicate."""
        _post_csv(rest_api, 'threat', THREAT_CSV)

        response = _post_csv(rest_api, 'threat', THREAT_CSV)

        assert response.get_json()['existing_objects'] == 1
        assert _count(database_manager, database_name, IsmsThreat.COLLECTION, {'name': THREAT_NAME}) == 1

    def test_invalid_row_is_reported(self, rest_api) -> None:
        """A row with no name is collected as invalid, not created."""
        csv_text = f'name,source,identifier,description\n{THREAT_NAME},,,\n,,,\n'

        body = _post_csv(rest_api, 'threat', csv_text).get_json()

        assert body['created_objects'] == 1
        assert len(body['invalid_objects']) == 1


class TestImportOtherTargets:
    """The vulnerability / control_measure / risk targets import their objects."""

    def test_creates_vulnerability(self, rest_api,
                                  database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A valid vulnerability row is created."""
        response = _post_csv(rest_api, 'vulnerability', VULNERABILITY_CSV)

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['created_objects'] == 1
        assert _count(database_manager, database_name, IsmsVulnerability.COLLECTION,
                      {'name': VULNERABILITY_NAME}) == 1

    def test_creates_control_measure(self, rest_api,
                                    database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A valid control-measure row is created."""
        response = _post_csv(rest_api, 'control_measure', CONTROL_MEASURE_CSV)

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['created_objects'] == 1
        assert _count(database_manager, database_name, IsmsControlMeasure.COLLECTION,
                      {'title': CONTROL_MEASURE_TITLE}) == 1

    def test_creates_risk(self, rest_api, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A valid EVENT risk row is created."""
        response = _post_csv(rest_api, 'risk', RISK_CSV)

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['created_objects'] == 1
        assert _count(database_manager, database_name, IsmsRisk.COLLECTION, {'name': RISK_NAME}) == 1

    def test_threat_x_vulnerability_risk_resolves_and_creates_references(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A THREAT_X_VULNERABILITY risk auto-creates its threat / vulnerability / goal by name."""
        response = _post_csv(rest_api, 'risk', TXV_RISK_CSV)

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['created_objects'] == 1
        assert _count(database_manager, database_name, IsmsRisk.COLLECTION, {'name': TXV_RISK_NAME}) == 1
        assert _count(database_manager, database_name, IsmsThreat.COLLECTION, {'name': TXV_THREAT_NAME}) == 1
        assert _count(database_manager, database_name, IsmsVulnerability.COLLECTION,
                      {'name': TXV_VULNERABILITY_NAME}) == 1
        assert _count(database_manager, database_name, IsmsProtectionGoal.COLLECTION, {'name': TXV_GOAL_NAME}) == 1


class TestImportGuards:
    """Route-level guards for the importer."""

    def test_invalid_target_returns_400(self, rest_api) -> None:
        """An unknown import target is rejected with 400."""
        assert _post_csv(rest_api, 'not_a_target', THREAT_CSV).status_code == HTTPStatus.BAD_REQUEST

    def test_missing_file_returns_400(self, rest_api) -> None:
        """A request without a file is rejected with 400."""
        assert rest_api.post(f'{ROUTE_URL}/threat').status_code == HTTPStatus.BAD_REQUEST

    def test_missing_headers_returns_400(self, rest_api) -> None:
        """A CSV missing required headers is rejected with 400."""
        assert _post_csv(rest_api, 'threat', 'name\nOnlyName\n').status_code == HTTPStatus.BAD_REQUEST
