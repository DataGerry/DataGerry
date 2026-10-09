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
Functional tests for the report type ACL: a report is as visible as the objects of its type

Seeded with ``tests/utils/location_acl_seed`` (a VISIBLE type and a HIDDEN one only the admin group may read), with
the seed's editor group given the four report rights - a report user without READ on HIDDEN. A report has exactly
one type (its query is AND-ed with that ``type_id``), so every route decides once. Pinned, for that reader:

  - running a HIDDEN report is a 403, with and without ``?preview=true`` - not a silently empty table - and the
    hidden values never reach the body; a VISIBLE report runs as before
  - a HIDDEN report's definition is a 403 by id and absent from the list (and its total)
  - creating a report over HIDDEN, updating a VISIBLE report onto HIDDEN, and updating or deleting a HIDDEN
    report are each a 403 and write nothing
  - the admin, whom the HIDDEN type grants, still sees, runs and changes everything
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.location_model.location_constants import RootLocationDefault
from cmdb.models.reports_model.cmdb_report import CmdbReport
from cmdb.models.reports_model.cmdb_report_category import CmdbReportCategory
from cmdb.interface.rest_api.routes.report_routes.report_constants import (
    REPORT_TARGET_TYPE_ACCESS_DENIED_MSG,
    REPORT_TYPE_ACCESS_DENIED_MSG,
    ReportRight,
)
from tests.utils import location_acl_seed as seed
# -------------------------------------------------------------------------------------------------------------------- #

CATEGORY_ID: int = 89811
HIDDEN_REPORT_ID: int = 89812
VISIBLE_REPORT_ID: int = 89813
ALL_REPORT_IDS: list[int] = [HIDDEN_REPORT_ID, VISIBLE_REPORT_ID]
CREATED_NAME: str = 'type-acl-created'
EMPTY_CONDITIONS: dict[str, Any] = {'condition': 'and', 'rules': []}


def _stored_query(type_id: int) -> str:
    """A compiled report query the way the builder stores it: every object of the type that names the field"""
    return str({'$and': [
        {'fields': {'$elemMatch': {'name': seed.NAME_FIELD, 'value': {'$exists': True}}}},
        {'type_id': type_id},
    ]})


def _report(public_id: int, type_id: int) -> dict[str, Any]:
    """A stored report over one of the seed's types"""
    return {
        'public_id': public_id, 'report_category_id': CATEGORY_ID, 'name': f'type-acl-{public_id}',
        'type_id': type_id, 'selected_fields': [seed.NAME_FIELD], 'conditions': EMPTY_CONDITIONS,
        'report_query': {'data': _stored_query(type_id)}, 'predefined': False, 'mds_mode': 'ROWS',
    }


def _write_body(type_id: int, name: str = CREATED_NAME) -> dict[str, Any]:
    """A create / update body naming a type"""
    return {
        'report_category_id': CATEGORY_ID, 'name': name, 'type_id': type_id,
        'selected_fields': [seed.NAME_FIELD], 'conditions': EMPTY_CONDITIONS, 'mds_mode': 'ROWS',
    }


@pytest.fixture(name='reports', autouse=True)
def fixture_reports(database_manager: MongoDatabaseManager, database_name: str):
    """The location ACL seed, its editor given the report rights, a category, a HIDDEN and a VISIBLE report"""
    seed.seed(database_manager, database_name, RootLocationDefault.PUBLIC_ID)
    report_rights: list[str] = [right.value for right in ReportRight]
    database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name).update_one(
        {'public_id': seed.EDITOR_GROUP_ID}, {'$push': {'rights': {'$each': report_rights}}},
    )
    categories = database_manager.get_collection(CmdbReportCategory.COLLECTION, database_name)
    categories.delete_many({'public_id': CATEGORY_ID})
    categories.insert_one({'public_id': CATEGORY_ID, 'name': 'type-acl', 'predefined': False})
    reports = database_manager.get_collection(CmdbReport.COLLECTION, database_name)
    reports.delete_many({'$or': [{'public_id': {'$in': ALL_REPORT_IDS}}, {'name': CREATED_NAME}]})
    reports.insert_many([
        _report(HIDDEN_REPORT_ID, seed.HIDDEN_TYPE_ID), _report(VISIBLE_REPORT_ID, seed.VISIBLE_TYPE_ID),
    ])
    yield reports
    reports.delete_many({'$or': [{'public_id': {'$in': ALL_REPORT_IDS}}, {'name': CREATED_NAME}]})
    categories.delete_many({'public_id': CATEGORY_ID})
    seed.purge(database_manager, database_name)


def _reader() -> dict[str, Any]:
    """The request kwargs that send it as the report user"""
    return {'user': seed.location_editor()}


def _denied(response: Any, public_id: int) -> None:
    """A 403 naming the report, without its type's values"""
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert response.get_json()['message'] == REPORT_TYPE_ACCESS_DENIED_MSG.format(public_id=public_id)
    assert seed.HIDDEN_VALUE not in response.get_data(as_text=True)


class TestRunningAReport:
    """GET /reports/run/<id>"""

    @pytest.mark.parametrize('query', ['', '?preview=true'], ids=['full', 'preview'])
    def test_a_hidden_report_is_a_403(self, rest_api, query: str) -> None:
        """Decided once, from the report's type - not a silently empty table"""
        _denied(rest_api.get(f'/reports/run/{HIDDEN_REPORT_ID}{query}', **_reader()), HIDDEN_REPORT_ID)

    def test_a_visible_report_runs_as_before(self, rest_api) -> None:
        """Its object comes back"""
        response = rest_api.get(f'/reports/run/{VISIBLE_REPORT_ID}', **_reader())

        assert response.status_code == HTTPStatus.OK
        assert seed.VISIBLE_ID in {row['public_id'] for row in response.get_json()}

    def test_the_admin_runs_the_hidden_report(self, rest_api) -> None:
        """The HIDDEN type grants the admin group"""
        response = rest_api.get(f'/reports/run/{HIDDEN_REPORT_ID}')

        assert response.status_code == HTTPStatus.OK
        assert seed.HIDDEN_ID in {row['public_id'] for row in response.get_json()}


class TestReadingADefinition:
    """GET /reports/<id> and GET /reports/"""

    def test_a_hidden_definition_is_a_403(self, rest_api) -> None:
        """It names the type's fields and the values its conditions filter on"""
        _denied(rest_api.get(f'/reports/{HIDDEN_REPORT_ID}', **_reader()), HIDDEN_REPORT_ID)

    def test_a_visible_definition_reads(self, rest_api) -> None:
        """Unchanged"""
        assert rest_api.get(f'/reports/{VISIBLE_REPORT_ID}', **_reader()).status_code == HTTPStatus.OK

    def test_the_list_leaves_hidden_reports_out(self, rest_api) -> None:
        """Neither listed nor counted"""
        response = rest_api.get('/reports/?limit=0', **_reader())
        listed: set[int] = {report['public_id'] for report in response.get_json()['results']}
        admin_rows: list[dict[str, Any]] = rest_api.get('/reports/?limit=0').get_json()['results']
        admin_listed: set[int] = {report['public_id'] for report in admin_rows}

        assert VISIBLE_REPORT_ID in listed
        assert HIDDEN_REPORT_ID not in listed
        assert HIDDEN_REPORT_ID in admin_listed
        assert response.get_json()['total'] == len(response.get_json()['results'])


class TestWritingAReport:
    """POST, PUT and DELETE"""

    def test_creating_over_a_hidden_type_is_a_403(self, rest_api, reports) -> None:
        """Nothing is inserted"""
        response = rest_api.post('/reports/', json=_write_body(seed.HIDDEN_TYPE_ID), **_reader())

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.get_json()['message'] == REPORT_TARGET_TYPE_ACCESS_DENIED_MSG.format(
            type_id=seed.HIDDEN_TYPE_ID,
        )
        assert reports.count_documents({'name': CREATED_NAME}) == 0

    def test_creating_over_a_visible_type_works(self, rest_api, reports) -> None:
        """Unchanged"""
        response = rest_api.post('/reports/', json=_write_body(seed.VISIBLE_TYPE_ID), **_reader())

        assert response.status_code == HTTPStatus.OK
        assert reports.count_documents({'name': CREATED_NAME}) == 1

    def test_moving_a_visible_report_onto_a_hidden_type_is_a_403(self, rest_api, reports) -> None:
        """The stored report stays where it was"""
        body = _write_body(seed.HIDDEN_TYPE_ID, name='moved')

        response = rest_api.put(f'/reports/{VISIBLE_REPORT_ID}', json=body, **_reader())

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert reports.find_one({'public_id': VISIBLE_REPORT_ID})['type_id'] == seed.VISIBLE_TYPE_ID

    def test_updating_a_hidden_report_is_a_403(self, rest_api, reports) -> None:
        """Even onto a visible type - a report the caller cannot see is not theirs to rewrite"""
        body = _write_body(seed.VISIBLE_TYPE_ID, name='taken-over')

        _denied(rest_api.put(f'/reports/{HIDDEN_REPORT_ID}', json=body, **_reader()), HIDDEN_REPORT_ID)
        assert reports.find_one({'public_id': HIDDEN_REPORT_ID})['type_id'] == seed.HIDDEN_TYPE_ID

    def test_deleting_a_hidden_report_is_a_403(self, rest_api, reports) -> None:
        """It stays stored"""
        _denied(rest_api.delete(f'/reports/{HIDDEN_REPORT_ID}', **_reader()), HIDDEN_REPORT_ID)
        assert reports.count_documents({'public_id': HIDDEN_REPORT_ID}) == 1

    def test_deleting_a_visible_report_works(self, rest_api, reports) -> None:
        """Unchanged"""
        assert rest_api.delete(f'/reports/{VISIBLE_REPORT_ID}', **_reader()).status_code == HTTPStatus.OK
        assert reports.count_documents({'public_id': VISIBLE_REPORT_ID}) == 0

    def test_the_admin_still_changes_a_hidden_report(self, rest_api, reports) -> None:
        """The type grants the admin group"""
        body = _write_body(seed.HIDDEN_TYPE_ID, name='admin-renamed')

        assert rest_api.put(f'/reports/{HIDDEN_REPORT_ID}', json=body).status_code == HTTPStatus.ACCEPTED
        assert reports.find_one({'public_id': HIDDEN_REPORT_ID})['name'] == 'admin-renamed'
