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
Functional regression for the report cleanup of PUT /objects/clean/<type_id>

When a CmdbType's objects still carry fields the type no longer declares, the clean route drops
those fields from every object and from every report of the type. This pins the multi-field case:
a single report referencing *several* removed fields must have *all* of them stripped from its
selected_fields and conditions in one clean run - guarding the earlier last-write-wins bug, where
each removed field reloaded the report from its original document so only the last field survived
the cleanup. The persisted report_query.data string format is left unchanged.
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.type_model import CmdbType
from cmdb.models.object_model import CmdbObject
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.reports_model.cmdb_report import CmdbReport
from cmdb.models.reports_model.report_constants import (
    ReportConditionKey,
    ReportConditionLogic,
    ReportQueryOperator,
)
from cmdb.interface.rest_api.routes.report_routes.report_constants import ReportKey, ReportQueryKey
from cmdb.interface.rest_api.routes.report_routes.report_helper import collect_condition_field_names
# -------------------------------------------------------------------------------------------------------------------- #

CLEAN_ROUTE_URL: str = '/objects/clean'

CLEAN_TYPE_ID: int = 8830
CLEAN_OBJECT_ID: int = 8831
CLEAN_REPORT_ID: int = 8832

# The type declares only KEEP_FIELD; the seeded object additionally carries two stale fields the
# type no longer declares, so both become "removed" fields the clean route must strip from reports
KEEP_FIELD: str = 'keep-field'
STALE_FIELD_A: str = 'stale-field-a'
STALE_FIELD_B: str = 'stale-field-b'

SEED_AUTHOR_ID: int = 1
SEED_VERSION: str = '1.0.0'
SEED_VALUE: str = 'x'


def _type_doc() -> dict[str, Any]:
    """Builds a CmdbType doc declaring only KEEP_FIELD, for direct DB insertion."""
    return {
        'public_id': CLEAN_TYPE_ID,
        'name': f'clean-type-{CLEAN_TYPE_ID}',
        'label': 'Clean Type',
        'author_id': SEED_AUTHOR_ID,
        'active': True,
        'fields': [{'type': 'text', 'name': KEEP_FIELD, 'label': 'Keep'}],
        'render_meta': {
            'icon': 'fa-cube',
            'sections': [{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [KEEP_FIELD]}],
            'summary': {'fields': [KEEP_FIELD]},
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': SEED_VERSION,
        'creation_time': datetime.now(timezone.utc),
    }


def _object_doc() -> dict[str, Any]:
    """Builds a CmdbObject doc carrying KEEP_FIELD plus two stale fields the type no longer declares."""
    return {
        'public_id': CLEAN_OBJECT_ID,
        'type_id': CLEAN_TYPE_ID,
        'active': True,
        'author_id': SEED_AUTHOR_ID,
        'version': SEED_VERSION,
        'fields': [
            {'type': 'text', 'name': KEEP_FIELD, 'value': SEED_VALUE},
            {'type': 'text', 'name': STALE_FIELD_A, 'value': SEED_VALUE},
            {'type': 'text', 'name': STALE_FIELD_B, 'value': SEED_VALUE},
        ],
        'creation_time': datetime.now(timezone.utc),
    }


def _conditions_referencing(field_names: list[str]) -> dict[str, Any]:
    """Builds an AND condition group with one equality leaf rule per given field name."""
    return {
        ReportConditionKey.CONDITION: ReportConditionLogic.AND,
        ReportConditionKey.RULES: [
            {
                ReportConditionKey.FIELD: name,
                ReportConditionKey.OPERATOR: ReportQueryOperator.EQ,
                ReportConditionKey.VALUE: SEED_VALUE,
            }
            for name in field_names
        ],
    }


def _report_doc() -> dict[str, Any]:
    """Builds a CmdbReport doc whose selected_fields and conditions reference both stale fields."""
    referenced = [KEEP_FIELD, STALE_FIELD_A, STALE_FIELD_B]
    return {
        CmdbObjectKey.PUBLIC_ID: CLEAN_REPORT_ID,
        ReportKey.REPORT_CATEGORY_ID: 1,
        ReportKey.NAME: 'clean-report',
        ReportKey.TYPE_ID: CLEAN_TYPE_ID,
        ReportKey.SELECTED_FIELDS: list(referenced),
        ReportKey.CONDITIONS: _conditions_referencing(referenced),
        ReportKey.REPORT_QUERY: {ReportQueryKey.DATA: '{}'},
        ReportKey.PREDEFINED: False,
        ReportKey.MDS_MODE: 'ROWS',
    }


@pytest.fixture(autouse=True)
def _seed_type_object_report(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the type, the stale-field object and the multi-field report; removes all three after."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    reports = database_manager.get_collection(CmdbReport.COLLECTION, database_name)

    types.insert_one(_type_doc())
    objects.insert_one(_object_doc())
    reports.insert_one(_report_doc())
    yield
    types.delete_one({'public_id': CLEAN_TYPE_ID})
    objects.delete_one({'public_id': CLEAN_OBJECT_ID})
    reports.delete_one({'public_id': CLEAN_REPORT_ID})


class TestCleanObjectsReportCleanup:
    """PUT /objects/clean/<type_id> strips every removed field from the type's reports in one run."""

    def test_clean_strips_all_removed_fields_from_report(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A report referencing two removed fields has both cleared - not just the last one."""
        response = rest_api.put(f'{CLEAN_ROUTE_URL}/{CLEAN_TYPE_ID}')

        assert response.status_code == HTTPStatus.ACCEPTED

        reports = database_manager.get_collection(CmdbReport.COLLECTION, database_name)
        report_after = reports.find_one({'public_id': CLEAN_REPORT_ID})

        # Both stale fields are gone from selected_fields; the still-declared field remains
        assert report_after[ReportKey.SELECTED_FIELDS] == [KEEP_FIELD]

        # Both stale fields are gone from the conditions tree; the still-declared field remains
        referenced = collect_condition_field_names(report_after[ReportKey.CONDITIONS])
        assert STALE_FIELD_A not in referenced
        assert STALE_FIELD_B not in referenced
        assert KEEP_FIELD in referenced

        # The query is rebuilt from the cleaned conditions and kept in the same stored string shape
        rebuilt_query: str = report_after[ReportKey.REPORT_QUERY][ReportQueryKey.DATA]
        assert isinstance(rebuilt_query, str)
        assert STALE_FIELD_A not in rebuilt_query
        assert STALE_FIELD_B not in rebuilt_query

    def test_clean_removes_stale_fields_from_object(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The same run also drops the stale fields from the object, leaving only declared fields."""
        response = rest_api.put(f'{CLEAN_ROUTE_URL}/{CLEAN_TYPE_ID}')

        assert response.status_code == HTTPStatus.ACCEPTED

        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        object_after = objects.find_one({'public_id': CLEAN_OBJECT_ID})
        field_names = [field['name'] for field in object_after['fields']]

        assert STALE_FIELD_A not in field_names
        assert STALE_FIELD_B not in field_names
        assert KEEP_FIELD in field_names
