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

Also pins the three behaviours fixed on 2026-07-30: a rejected row leaves NO master data behind (it
used to create the referenced options / threats / goals before deciding the row was invalid), a short
row is a normal invalid row rather than a 500, and a CSV carrying a UTF-8 BOM (i.e. saved by Excel) is
accepted instead of being reported as missing its first header.
"""
import io
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.extendable_option_model import CmdbExtendableOption
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

# Rows that must be rejected WITHOUT creating the master data they reference
ORPHAN_SOURCE: str = 'ImportTest Orphan Source'
ORPHAN_THREAT_NAME: str = 'ImportTest Orphan Threat'
ORPHAN_GOAL_NAME: str = 'ImportTest Orphan Goal'

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


# A nameless threat row that still names a source: the source must not be created
INVALID_THREAT_WITH_SOURCE_CSV: str = f'name,source,identifier,description\n,{ORPHAN_SOURCE},,\n'

# A risk row that is invalid (EVENT must not carry threats) but references a threat and a goal
INVALID_RISK_WITH_REFS_CSV: str = (
    'name,risk_type,protection_goals,threats,vulnerabilities,identifier,consequences,description\n'
    f'ImportTest Orphan Risk,EVENT,{ORPHAN_GOAL_NAME},{ORPHAN_THREAT_NAME},,,A consequence,A description\n'
)

# Fewer cells than the header - DictReader fills the rest with None
SHORT_THREAT_CSV: str = f'name,source,identifier,description\n{THREAT_NAME}\n'
SHORT_RISK_CSV: str = (
    'name,risk_type,protection_goals,threats,vulnerabilities,identifier,consequences,description\n'
    f'{RISK_NAME},EVENT\n'
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
        database_manager.get_collection(IsmsThreat.COLLECTION, database_name)\
            .delete_many({'name': ORPHAN_THREAT_NAME})
        database_manager.get_collection(IsmsProtectionGoal.COLLECTION, database_name)\
            .delete_many({'name': ORPHAN_GOAL_NAME})
        database_manager.get_collection(CmdbExtendableOption.COLLECTION, database_name)\
            .delete_many({'value': ORPHAN_SOURCE})
        database_manager.get_collection(IsmsRisk.COLLECTION, database_name)\
            .delete_many({'name': 'ImportTest Orphan Risk'})

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


# -------------------------------------------------------------------------------------------------------------------- #
#                                       REJECTED ROWS LEAVE NOTHING BEHIND                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class TestRejectedRowsHaveNoSideEffects:
    """A row that is reported invalid must not create the master data it references."""

    def test_a_nameless_threat_row_does_not_create_its_source_option(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The source option of a rejected threat row is never inserted."""
        body = _post_csv(rest_api, 'threat', INVALID_THREAT_WITH_SOURCE_CSV).get_json()

        assert body['created_objects'] == 0
        assert len(body['invalid_objects']) == 1
        assert _count(database_manager, database_name,
                      CmdbExtendableOption.COLLECTION, {'value': ORPHAN_SOURCE}) == 0

    def test_an_invalid_risk_row_does_not_create_its_references(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """An EVENT risk carrying threats is rejected - and its threat / goal stay uncreated."""
        body = _post_csv(rest_api, 'risk', INVALID_RISK_WITH_REFS_CSV).get_json()

        assert body['created_objects'] == 0
        assert len(body['invalid_objects']) == 1
        assert _count(database_manager, database_name, IsmsThreat.COLLECTION,
                      {'name': ORPHAN_THREAT_NAME}) == 0
        assert _count(database_manager, database_name, IsmsProtectionGoal.COLLECTION,
                      {'name': ORPHAN_GOAL_NAME}) == 0


# -------------------------------------------------------------------------------------------------------------------- #
#                                        SHORT ROWS, BOM AND ENCODING                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class TestMalformedFiles:
    """A file the caller got slightly wrong is answered, not turned into a 500."""

    def test_a_short_threat_row_is_imported_with_empty_cells(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A row with only the name is valid - the missing cells are simply empty (used to be a 500)."""
        response = _post_csv(rest_api, 'threat', SHORT_THREAT_CSV)

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['created_objects'] == 1
        assert _count(database_manager, database_name, IsmsThreat.COLLECTION, {'name': THREAT_NAME}) == 1

    def test_a_short_risk_row_is_reported_invalid_not_a_server_error(self, rest_api) -> None:
        """An EVENT risk row without consequences / description is one invalid row, not a 500."""
        response = _post_csv(rest_api, 'risk', SHORT_RISK_CSV)

        assert response.status_code == HTTPStatus.OK

        body = response.get_json()

        assert body['created_objects'] == 0
        assert len(body['invalid_objects']) == 1

    def test_a_csv_with_a_utf8_bom_is_accepted(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A file saved by Excel starts with a BOM; its first header must still be recognised."""
        response = rest_api.post(
            f'{ROUTE_URL}/threat',
            data={FILE_KEY: (io.BytesIO(THREAT_CSV.encode('utf-8-sig')), 'import.csv')},
            content_type='multipart/form-data',
        )

        assert response.status_code == HTTPStatus.OK
        assert _count(database_manager, database_name, IsmsThreat.COLLECTION, {'name': THREAT_NAME}) == 1

    def test_a_non_utf8_file_returns_400(self, rest_api) -> None:
        """A latin-1 encoded file is the caller's problem, answered with 400 instead of a 500."""
        response = rest_api.post(
            f'{ROUTE_URL}/threat',
            data={FILE_KEY: (io.BytesIO('name,source,identifier,description\nCaf\xe9,,,\n'.encode('latin-1')),
                             'import.csv')},
            content_type='multipart/form-data',
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST


# -------------------------------------------------------------------------------------------------------------------- #
#                                            REPORT SHAPE AND COUNTERS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TestRouteErrorMapping:
    """An unexpected failure inside a handler is answered with a 500, not a traceback."""

    def test_an_unexpected_handler_error_returns_500(self, rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
        """Any error the handlers do not model surfaces as a 500."""
        monkeypatch.setattr(
            'cmdb.interface.rest_api.routes.importer_routes.importer_isms_routes.handle_isms_import',
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError('boom')),
        )

        assert _post_csv(rest_api, 'threat', THREAT_CSV).status_code == HTTPStatus.INTERNAL_SERVER_ERROR


class TestImportReport:
    """The result dict reports every counter the frontend shows, plus the row total."""

    def test_every_counter_is_reported(self, rest_api) -> None:
        """total_rows counts data rows; imported_objects is created + existing."""
        body = _post_csv(rest_api, 'threat', THREAT_CSV).get_json()

        assert body['total_rows'] == 1
        assert body['imported_objects'] == 1
        assert body['created_objects'] == 1
        assert body['existing_objects'] == 0
        assert body['invalid_objects'] == []

    def test_an_invalid_row_counts_in_total_rows_only(self, rest_api) -> None:
        """A rejected row is counted as a row read, not as an imported object."""
        csv_text = f'name,source,identifier,description\n{THREAT_NAME},,,\n,,,\n'

        body = _post_csv(rest_api, 'threat', csv_text).get_json()

        assert body['total_rows'] == 2
        assert body['imported_objects'] == 1
        assert len(body['invalid_objects']) == 1

    def test_a_reimport_reports_existing_not_created(self, rest_api) -> None:
        """imported_objects stays 1 across a re-import, but it is counted as existing."""
        _post_csv(rest_api, 'threat', THREAT_CSV)

        body = _post_csv(rest_api, 'threat', THREAT_CSV).get_json()

        assert body['imported_objects'] == 1
        assert body['created_objects'] == 0
        assert body['existing_objects'] == 1


# -------------------------------------------------------------------------------------------------------------------- #
#                                      is_applicable REJECTS UNKNOWN VALUES                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class TestControlMeasureBooleanRule:
    """'is_applicable' follows the shared strict import-bool parser."""

    @pytest.mark.parametrize('raw_value, expected', [('true', True), ('yes', True), ('1', True),
                                                     ('false', False), ('no', False), ('0', False)])
    def test_recognised_values_are_parsed(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
        raw_value: str, expected: bool,
    ) -> None:
        """Every documented truthy / falsy spelling is accepted."""
        csv_text = (
            'title,control_measure_type,source,implementation_state,identifier,chapter,description,'
            'is_applicable,reason\n'
            f'{CONTROL_MEASURE_TITLE},CONTROL,,,,,,{raw_value},\n'
        )

        assert _post_csv(rest_api, 'control_measure', csv_text).get_json()['created_objects'] == 1

        stored = database_manager.get_collection(IsmsControlMeasure.COLLECTION, database_name)\
            .find_one({'title': CONTROL_MEASURE_TITLE})
        assert stored['is_applicable'] is expected

    def test_an_unrecognised_value_rejects_the_row(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """'maybe' is not a boolean - the row is reported instead of silently becoming False."""
        csv_text = (
            'title,control_measure_type,source,implementation_state,identifier,chapter,description,'
            'is_applicable,reason\n'
            f'{CONTROL_MEASURE_TITLE},CONTROL,,,,,,maybe,\n'
        )

        body = _post_csv(rest_api, 'control_measure', csv_text).get_json()

        assert body['created_objects'] == 0
        assert len(body['invalid_objects']) == 1
        assert _count(database_manager, database_name,
                      IsmsControlMeasure.COLLECTION, {'title': CONTROL_MEASURE_TITLE}) == 0

    def test_an_empty_value_defaults_to_false(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """An empty cell keeps the historical default rather than rejecting the row."""
        csv_text = (
            'title,control_measure_type,source,implementation_state,identifier,chapter,description,'
            'is_applicable,reason\n'
            f'{CONTROL_MEASURE_TITLE},CONTROL,,,,,,,\n'
        )

        assert _post_csv(rest_api, 'control_measure', csv_text).get_json()['created_objects'] == 1

        stored = database_manager.get_collection(IsmsControlMeasure.COLLECTION, database_name)\
            .find_one({'title': CONTROL_MEASURE_TITLE})
        assert stored['is_applicable'] is False
