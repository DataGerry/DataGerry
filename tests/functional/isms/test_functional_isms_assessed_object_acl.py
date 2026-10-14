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
Functional coverage for the type ACL on an assessed object's name, on every ISMS surface that shows it

A reader holding the ISMS view rights, but no READ on the type of an assessed object, still sees the assessment -
the ISMS rights are theirs - but not the object's summary line nor its type label:

  - both risk reports blank the object column and leave the type column out, while a deleted object stays
    'Unknown object'
  - ``?filter=`` on the type label cannot find the hidden row: the label is never joined for that reader
  - the RiskAssessment list leaves the object's naming None, the ControlMeasureAssignment list leaves it blank
  - an administrator still sees every name
"""
import json
from datetime import datetime, timezone
from functools import partial
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID
from cmdb.models.isms_model import IsmsControlMeasureAssignment, IsmsRisk, IsmsRiskAssessment
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.interface.rest_api.routes.isms_routes.isms_report_constants import (
    HIDDEN_OBJECT_LABEL,
    UNKNOWN_OBJECT_LABEL,
)
# -------------------------------------------------------------------------------------------------------------------- #

REPORTS_URL: str = '/isms/reports'
RISK_ASSESSMENTS_URL: str = '/isms/risk_assessments/'
ASSIGNMENTS_URL: str = '/isms/control_measure_assignments/'

OPEN_TYPE_ID: int = 98851
HIDDEN_TYPE_ID: int = 98852
OPEN_LABEL: str = 'Open Acl Type'
HIDDEN_LABEL: str = 'Secret Acl Type'
OPEN_OBJECT_ID: int = 98853
HIDDEN_OBJECT_ID: int = 98854
DELETED_OBJECT_ID: int = 98855
OPEN_NAME: str = 'open-server'
HIDDEN_NAME: str = 'secret-server'
RISK_ID: int = 98856
RA_OPEN: int = 98861
RA_HIDDEN: int = 98862
RA_DELETED: int = 98863
ALL_RA_IDS: list[int] = [RA_OPEN, RA_HIDDEN, RA_DELETED]
CMA_OPEN: int = 98871
CMA_HIDDEN: int = 98872
CONTROL_MEASURE_ID: int = 98873

READER_GROUP_ID: int = 98881
READER_ID: int = 98882
READER_NAME: str = 'isms-assessed-object-reader'
READER_RIGHTS: list[str] = [
    'base.isms.report.view', 'base.isms.riskAssessment.view', 'base.isms.controlMeasureAssignment.view',
]

ADMIN_ALL: dict[str, list[str]] = {str(ADMIN_GROUP_ID): ['CREATE', 'READ', 'UPDATE', 'DELETE']}
HIDDEN_ACL: dict[str, Any] = {'activated': True, 'groups': {'includes': ADMIN_ALL}}
OPEN_ACL: dict[str, Any] = {'activated': False, 'groups': {'includes': None}}
NAME_FIELD: str = 'name'

# report -> (its object column, its object-type column)
REPORT_COLUMNS: dict[str, tuple[str, str]] = {
    'risk_assessments': ('assigned_object', 'assigned_object_type'),
    'risk_treatment_plan': ('object', 'object_type'),
}
REPORTS: list[str] = list(REPORT_COLUMNS)


def _type(public_id: int, label: str, acl: dict[str, Any]) -> dict[str, Any]:
    """A CmdbType summarised by its one text field, with the given ACL"""
    return {
        'public_id': public_id, 'name': f'isms-acl-{public_id}', 'label': label, 'author_id': 1, 'active': True,
        'creation_time': datetime.now(timezone.utc), 'version': '1.0.0', 'acl': acl,
        'fields': [{'type': 'text', 'name': NAME_FIELD, 'label': 'Name'}],
        'render_meta': {'icon': 'fa-cube', 'summary': {'fields': [NAME_FIELD]}, 'sections': [
            {'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [NAME_FIELD]}]},
    }


def _object(public_id: int, type_id: int, name: str) -> dict[str, Any]:
    """A CmdbObject carrying its summary name"""
    return {'public_id': public_id, 'type_id': type_id, 'active': True, 'author_id': 1, 'version': '1.0.0',
            'creation_time': datetime.now(timezone.utc),
            'fields': [{'type': 'text', 'name': NAME_FIELD, 'value': name}]}


SEEDS: dict[str, list[dict[str, Any]]] = {
    CmdbType.COLLECTION: [_type(OPEN_TYPE_ID, OPEN_LABEL, OPEN_ACL), _type(HIDDEN_TYPE_ID, HIDDEN_LABEL, HIDDEN_ACL)],
    CmdbObject.COLLECTION: [_object(OPEN_OBJECT_ID, OPEN_TYPE_ID, OPEN_NAME),
                            _object(HIDDEN_OBJECT_ID, HIDDEN_TYPE_ID, HIDDEN_NAME)],
    IsmsRisk.COLLECTION: [{'public_id': RISK_ID, 'name': 'Acl risk'}],
    IsmsRiskAssessment.COLLECTION: [
        {'public_id': ra_id, 'risk_id': RISK_ID, 'object_id': object_id, 'object_id_ref_type': 'OBJECT'}
        for ra_id, object_id in ((RA_OPEN, OPEN_OBJECT_ID), (RA_HIDDEN, HIDDEN_OBJECT_ID),
                                 (RA_DELETED, DELETED_OBJECT_ID))
    ],
    IsmsControlMeasureAssignment.COLLECTION: [
        {'public_id': cma_id, 'control_measure_id': CONTROL_MEASURE_ID, 'risk_assessment_id': ra_id}
        for cma_id, ra_id in ((CMA_OPEN, RA_OPEN), (CMA_HIDDEN, RA_HIDDEN))
    ],
    CmdbUserGroup.COLLECTION: [
        {'public_id': READER_GROUP_ID, 'name': READER_NAME, 'label': READER_NAME, 'rights': READER_RIGHTS},
    ],
    CmdbUser.COLLECTION: [{'public_id': READER_ID, 'user_name': READER_NAME, 'active': True,
                           'group_id': READER_GROUP_ID, 'registration_time': datetime.now(timezone.utc)}],
}


@pytest.fixture(autouse=True)
def _isms_licensed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Licenses the ISMS feature so the gated routes are reachable"""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.ISMS)


@pytest.fixture(autouse=True)
def _seeded(database_manager: MongoDatabaseManager, database_name: str):
    """The two types, their objects, the assessments and assignments, and the reader; removed again afterwards"""
    collection = partial(database_manager.get_collection, db_name=database_name)

    def _purge() -> None:
        for name, docs in SEEDS.items():
            collection(name).delete_many({'public_id': {'$in': [doc['public_id'] for doc in docs]}})

    _purge()
    for name, docs in SEEDS.items():
        collection(name).insert_many([dict(doc) for doc in docs])

    yield

    _purge()


@pytest.fixture(name='reader')
def fixture_reader() -> CmdbUser:
    """The seeded reader: the ISMS view rights, no READ on the hidden type"""
    return CmdbUser(public_id=READER_ID, user_name=READER_NAME, active=True, group_id=READER_GROUP_ID)


def _report(rest_api, report: str, report_filter: dict[str, Any] | None = None,
            **kwargs: Any) -> tuple[dict[int, dict[str, Any]], int]:
    """The report's rows of the seeded assessments keyed by id - in public_id order - and the total"""
    response = rest_api.get(f'{REPORTS_URL}/{report}', query_string={
        'limit': 0, 'sort': 'public_id', 'order': 1,
        'filter': json.dumps(report_filter or {'public_id': {'$in': ALL_RA_IDS}}),
    }, **kwargs)
    assert response.status_code == HTTPStatus.OK, response.get_json()
    body = response.get_json()

    return dict(zip(ALL_RA_IDS, body['results'])), body['total']


def _listed(rest_api, url: str, ids: list[int], **kwargs: Any) -> dict[int, dict[str, Any]]:
    """The list route's entries of the given ids, keyed by public_id"""
    response = rest_api.get(url, query_string={'limit': 0, 'filter': json.dumps({'public_id': {'$in': ids}})},
                            **kwargs)
    assert response.status_code == HTTPStatus.OK, response.get_json()

    return {entry['public_id']: entry for entry in response.get_json()['results']}


@pytest.mark.parametrize('report', REPORTS)
class TestTheReportsAsTheReader:
    """The hidden row is kept, its object blank and its type left out - the open and deleted rows unchanged"""

    def test_the_hidden_object_is_blank_and_untyped(self, rest_api, reader: CmdbUser, report: str) -> None:
        """Neither the summary line nor the type label reaches a reader without READ on the type"""
        object_key, type_key = REPORT_COLUMNS[report]
        row = _report(rest_api, report, user=reader)[0][RA_HIDDEN]

        assert row[object_key] == HIDDEN_OBJECT_LABEL
        assert type_key not in row

    def test_the_open_and_the_deleted_rows_are_unchanged(self, rest_api, reader: CmdbUser, report: str) -> None:
        """A readable object is named and typed; a deleted one is still 'Unknown object', not blank"""
        object_key, type_key = REPORT_COLUMNS[report]
        rows, total = _report(rest_api, report, user=reader)

        assert total == len(ALL_RA_IDS)
        assert OPEN_NAME in rows[RA_OPEN][object_key]
        assert rows[RA_OPEN][type_key] == OPEN_LABEL
        assert rows[RA_DELETED][object_key] == UNKNOWN_OBJECT_LABEL

    def test_a_filter_on_the_hidden_type_label_finds_nothing(self, rest_api, reader: CmdbUser, report: str) -> None:
        """The label is never joined for the reader, so ?filter= cannot use it as an oracle"""
        _, type_key = REPORT_COLUMNS[report]
        _, total = _report(rest_api, report, {'public_id': {'$in': ALL_RA_IDS}, type_key: HIDDEN_LABEL},
                           user=reader)

        assert total == 0

    def test_the_administrator_still_sees_the_names(self, rest_api, report: str) -> None:
        """The ACL is the administrators' own: their rows - and their filter - are unchanged"""
        object_key, type_key = REPORT_COLUMNS[report]
        row = _report(rest_api, report)[0][RA_HIDDEN]
        _, total = _report(rest_api, report, {'public_id': {'$in': ALL_RA_IDS}, type_key: HIDDEN_LABEL})

        assert HIDDEN_NAME in row[object_key]
        assert row[type_key] == HIDDEN_LABEL
        assert total == 1


class TestTheListsAsTheReader:
    """The RiskAssessment and ControlMeasureAssignment lists name the hidden object for no one but its readers"""

    def test_the_risk_assessment_naming_of_a_hidden_object_is_none(self, rest_api, reader: CmdbUser) -> None:
        """The open assessment is still named"""
        listed = _listed(rest_api, RISK_ASSESSMENTS_URL, ALL_RA_IDS, user=reader)

        assert listed[RA_HIDDEN]['naming']['object_id_name'] is None
        assert OPEN_NAME in listed[RA_OPEN]['naming']['object_id_name']

    def test_the_assignment_summary_of_a_hidden_object_is_blank(self, rest_api, reader: CmdbUser) -> None:
        """Neither the summary line nor the type label - the open assignment keeps both"""
        listed = _listed(rest_api, ASSIGNMENTS_URL, [CMA_OPEN, CMA_HIDDEN], user=reader)
        hidden_summary: str = listed[CMA_HIDDEN]['naming']['cma_summary']

        assert hidden_summary.endswith('@ ')
        assert HIDDEN_NAME not in hidden_summary and HIDDEN_LABEL not in hidden_summary
        assert OPEN_NAME in listed[CMA_OPEN]['naming']['cma_summary']
        assert OPEN_LABEL in listed[CMA_OPEN]['naming']['cma_summary']

    def test_the_administrator_still_sees_the_names(self, rest_api) -> None:
        """Both lists name the hidden object for a reader of its type"""
        assessments = _listed(rest_api, RISK_ASSESSMENTS_URL, ALL_RA_IDS)
        assignments = _listed(rest_api, ASSIGNMENTS_URL, [CMA_HIDDEN])

        assert HIDDEN_NAME in assessments[RA_HIDDEN]['naming']['object_id_name']
        assert HIDDEN_NAME in assignments[CMA_HIDDEN]['naming']['cma_summary']
        assert HIDDEN_LABEL in assignments[CMA_HIDDEN]['naming']['cma_summary']
