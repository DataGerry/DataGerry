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
Functional coverage for how both risk reports show an assessment's assessed object

The RiskAssessment report and the Risk Treatment Plan read the same discriminator and must agree:

  - neither answers ``object_id_ref_type``; both still filter on it
  - an object is named by its summary line, a group by its name, and the type column says which
  - a deleted object is 'Unknown object', a deleted group 'Unknown object group' - never blank
  - a legacy assessment without a ref type is read as an object
  - an assessment whose risk no longer exists is listed by both, with the same total
"""
import json
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectsManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.isms_model import IsmsRisk, IsmsRiskAssessment
from cmdb.models.object_group_model import CmdbObjectGroup
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.interface.rest_api.routes.isms_routes.isms_report_constants import (
    OBJECT_GROUP_TYPE_LABEL,
    UNKNOWN_OBJECT_GROUP_LABEL,
    UNKNOWN_OBJECT_LABEL,
)

from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

REPORTS_URL: str = '/isms/reports'
REF_KEY: str = 'object_id_ref_type'

TYPE_ID: int = 99551
TYPE_LABEL: str = 'Assessed Server'
OBJECT_ID: int = 99552
GROUP_ID: int = 99553
GROUP_NAME: str = 'Assessed Group'
RISK_ID: int = 99554
DELETED_OBJECT_ID: int = 99558
DELETED_GROUP_ID: int = 99559
DELETED_RISK_ID: int = 99560

RA_OBJECT: int = 99561
RA_DELETED_OBJECT: int = 99562
RA_GROUP: int = 99563
RA_DELETED_GROUP: int = 99564
RA_LEGACY: int = 99565
RA_ORPHAN_RISK: int = 99566
ALL_RA_IDS: list[int] = [RA_OBJECT, RA_DELETED_OBJECT, RA_GROUP, RA_DELETED_GROUP, RA_LEGACY, RA_ORPHAN_RISK]

# report -> (its object column, its object-type column)
REPORT_COLUMNS: dict[str, tuple[str, str]] = {
    'risk_assessments': ('assigned_object', 'assigned_object_type'),
    'risk_treatment_plan': ('object', 'object_type'),
}
REPORTS: list[str] = list(REPORT_COLUMNS)


def _assessment(public_id: int, object_id: int, ref_type: str | None, risk_id: int = RISK_ID) -> dict[str, Any]:
    """A stored assessment of an object or a group; ref_type None leaves the key out, as a legacy document"""
    doc: dict[str, Any] = {'public_id': public_id, 'risk_id': risk_id, 'object_id': object_id}

    if ref_type is not None:
        doc[REF_KEY] = ref_type

    return doc


@pytest.fixture(autouse=True)
def _isms_licensed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Licenses the ISMS feature so the gated report routes are reachable"""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.ISMS)


@pytest.fixture(name='seeded', autouse=True)
def fixture_seeded(database_manager: MongoDatabaseManager, database_name: str):
    """A type with one object, a group, a risk, and one assessment per case; removed again afterwards"""
    seeds: dict[str, list[dict[str, Any]]] = {
        CmdbType.COLLECTION: [{**make_type_doc(TYPE_ID, 'isms-assessed-server'), 'label': TYPE_LABEL}],
        CmdbObject.COLLECTION: [{'public_id': OBJECT_ID, 'type_id': TYPE_ID, 'active': True, 'author_id': 1,
                                 'version': '1.0.0', 'creation_time': datetime.now(timezone.utc), 'fields': []}],
        CmdbObjectGroup.COLLECTION: [{'public_id': GROUP_ID, 'name': GROUP_NAME}],
        IsmsRisk.COLLECTION: [{'public_id': RISK_ID, 'name': 'Assessed risk'}],
        IsmsRiskAssessment.COLLECTION: [
            _assessment(RA_OBJECT, OBJECT_ID, 'OBJECT'),
            _assessment(RA_DELETED_OBJECT, DELETED_OBJECT_ID, 'OBJECT'),
            _assessment(RA_GROUP, GROUP_ID, 'OBJECT_GROUP'),
            _assessment(RA_DELETED_GROUP, DELETED_GROUP_ID, 'OBJECT_GROUP'),
            _assessment(RA_LEGACY, OBJECT_ID, None),
            _assessment(RA_ORPHAN_RISK, OBJECT_ID, 'OBJECT', risk_id=DELETED_RISK_ID),
        ],
    }

    def _purge() -> None:
        for collection, docs in seeds.items():
            database_manager.get_collection(collection, database_name).delete_many(
                {'public_id': {'$in': [doc['public_id'] for doc in docs]}},
            )

    _purge()
    for collection, docs in seeds.items():
        database_manager.get_collection(collection, database_name).insert_many([dict(doc) for doc in docs])

    yield

    _purge()


@pytest.fixture(name='summary_line')
def fixture_summary_line(rest_api, database_manager: MongoDatabaseManager) -> str:
    """The seeded object's summary line, as the reports must show it"""
    with rest_api.application.test_request_context():
        return ObjectsManager(database_manager).get_summary_lines_lookup([OBJECT_ID], with_type=False)[OBJECT_ID]


def _rows(rest_api, report: str, report_filter: dict[str, Any] | None = None) -> tuple[dict[int, Any], int]:
    """Every seeded assessment's row - keyed by the order the filter's public_id addresses - and the total"""
    response = rest_api.get(f'{REPORTS_URL}/{report}', query_string={
        'limit': 0, 'sort': 'public_id', 'order': 1,
        'filter': json.dumps(report_filter or {'public_id': {'$in': ALL_RA_IDS}}),
    })
    assert response.status_code == HTTPStatus.OK, response.get_json()
    body = response.get_json()

    return dict(zip(ALL_RA_IDS, body['results'])), body['total']


@pytest.mark.parametrize('report', REPORTS)
class TestTheAssessedObjectColumns:
    """The same rows, the same names, in both reports"""

    def test_no_row_carries_the_ref_type(self, rest_api, report: str) -> None:
        """The discriminator is internal to both reports now"""
        rows, _ = _rows(rest_api, report)

        assert rows and all(REF_KEY not in row for row in rows.values())

    def test_an_object_is_named_by_its_summary_line(self, rest_api, report: str, summary_line: str) -> None:
        """And typed by its type's label"""
        object_key, type_key = REPORT_COLUMNS[report]
        row = _rows(rest_api, report)[0][RA_OBJECT]

        assert (row[object_key], row[type_key]) == (summary_line, TYPE_LABEL)

    def test_a_deleted_object_is_unknown_not_blank(self, rest_api, report: str) -> None:
        """It used to come back with no object key at all"""
        object_key, type_key = REPORT_COLUMNS[report]
        row = _rows(rest_api, report)[0][RA_DELETED_OBJECT]

        assert row[object_key] == UNKNOWN_OBJECT_LABEL
        assert type_key not in row

    def test_a_group_is_named_and_typed_as_a_group(self, rest_api, report: str) -> None:
        """The type column says which kind it is"""
        object_key, type_key = REPORT_COLUMNS[report]
        row = _rows(rest_api, report)[0][RA_GROUP]

        assert (row[object_key], row[type_key]) == (GROUP_NAME, OBJECT_GROUP_TYPE_LABEL)

    def test_a_deleted_group_is_unknown_not_blank(self, rest_api, report: str) -> None:
        """Still typed as a group"""
        object_key, type_key = REPORT_COLUMNS[report]
        row = _rows(rest_api, report)[0][RA_DELETED_GROUP]

        assert (row[object_key], row[type_key]) == (UNKNOWN_OBJECT_GROUP_LABEL, OBJECT_GROUP_TYPE_LABEL)

    def test_a_legacy_assessment_is_read_as_an_object(self, rest_api, report: str, summary_line: str) -> None:
        """No ref type: the projection and the resolver agree it is an object, so it is named"""
        object_key, _ = REPORT_COLUMNS[report]

        assert _rows(rest_api, report)[0][RA_LEGACY][object_key] == summary_line

    def test_an_assessment_of_a_deleted_risk_is_listed(self, rest_api, report: str, summary_line: str) -> None:
        """Both reports list all six, so the totals agree"""
        object_key, _ = REPORT_COLUMNS[report]
        rows, total = _rows(rest_api, report)

        assert total == len(ALL_RA_IDS)
        assert rows[RA_ORPHAN_RISK][object_key] == summary_line

    def test_the_ref_type_can_still_be_filtered_on(self, rest_api, report: str) -> None:
        """Dropped from the rows after the query, so the filter inside it still sees the key"""
        _, total = _rows(rest_api, report, {'public_id': {'$in': ALL_RA_IDS}, REF_KEY: 'OBJECT_GROUP'})

        assert total == 2
