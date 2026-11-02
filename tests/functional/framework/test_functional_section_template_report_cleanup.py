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
Functional test: removing a field from a global section template cleans the consuming types' reports

Through the real REST app: ``PUT /section_templates/`` drops a field from a global template that a type uses, and the
type's report - which selected and filtered on that field - no longer names it, in its columns, its conditions or its
stored query; the field it keeps is kept
"""
import json
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.reports_model.cmdb_report import CmdbReport
from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.models.type_model import CmdbType, SectionType
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/section_templates/'
TEMPLATE_ID: int = 93401
TYPE_ID: int = 93402
REPORT_ID: int = 93403
TEMPLATE_NAME: str = 'func-sectpl-report-cleanup'
KEPT_FIELD: str = 'rc-kept'
REMOVED_FIELD: str = 'rc-removed'
OWN_FIELD: str = 'dg-name'


def _field(name: str) -> dict[str, Any]:
    """A text field definition"""
    return {'type': 'text', 'name': name, 'label': name}


@pytest.fixture(name='stored')
def fixture_stored(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The global template [kept, removed], a type using it and a report on the removed field; removed afterwards"""
    templates = database_manager.get_collection(CmdbSectionTemplate.COLLECTION, database_name)
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    reports = database_manager.get_collection(CmdbReport.COLLECTION, database_name)

    def _purge() -> None:
        templates.delete_many({'public_id': TEMPLATE_ID})
        types.delete_many({'public_id': TYPE_ID})
        reports.delete_many({'public_id': REPORT_ID})

    _purge()
    templates.insert_one({'public_id': TEMPLATE_ID, 'name': TEMPLATE_NAME, 'label': 'Cleanup',
                          'type': SectionType.SECTION.value, 'is_global': True, 'predefined': False,
                          'fields': [_field(KEPT_FIELD), _field(REMOVED_FIELD)]})
    types.insert_one(make_type_doc(
        TYPE_ID, 'func-sectpl-report-type',
        fields=[_field(OWN_FIELD), _field(KEPT_FIELD), _field(REMOVED_FIELD)],
        sections=[{'type': SectionType.SECTION.value, 'name': OWN_FIELD, 'label': 'Own', 'fields': [OWN_FIELD]},
                  {'type': SectionType.SECTION.value, 'name': TEMPLATE_NAME, 'label': 'Cleanup',
                   'fields': [KEPT_FIELD, REMOVED_FIELD]}],
        global_template_ids=[TEMPLATE_NAME],
    ))
    reports.insert_one({
        'public_id': REPORT_ID, 'report_category_id': 1, 'name': 'func-sectpl-report', 'type_id': TYPE_ID,
        'selected_fields': [OWN_FIELD, KEPT_FIELD, REMOVED_FIELD],
        'conditions': {'condition': 'and', 'rules': [
            {'field': KEPT_FIELD, 'operator': '=', 'value': 'keep'},
            {'field': REMOVED_FIELD, 'operator': '=', 'value': 'gone'},
        ]},
        'report_query': {'data': f"{{'fields': {{'$elemMatch': {{'name': '{REMOVED_FIELD}'}}}}}}"},
        'predefined': False, 'mds_mode': 'ROWS',
    })

    yield reports

    _purge()


def test_removing_a_template_field_cleans_the_types_report(rest_api, stored: Any) -> None:
    """The report keeps its own and the kept field, and loses the removed one everywhere"""
    response = rest_api.put(ROUTE_URL, query_string={
        'public_id': str(TEMPLATE_ID), 'name': TEMPLATE_NAME, 'label': 'Cleanup', 'type': SectionType.SECTION.value,
        'is_global': 'true', 'predefined': 'false', 'fields': json.dumps([_field(KEPT_FIELD)]),
    })

    report: dict[str, Any] = stored.find_one({'public_id': REPORT_ID})
    assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
    assert report['selected_fields'] == [OWN_FIELD, KEPT_FIELD]
    assert [rule['field'] for rule in report['conditions']['rules']] == [KEPT_FIELD]
    assert REMOVED_FIELD not in report['report_query']['data']
    assert KEPT_FIELD in report['report_query']['data']
