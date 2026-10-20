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
Integration tests for the rows a report run reads, against a real MongoDB

The run reads a stored report query through ``ObjectsManager.iterate_results(params, user, READ)``; the DocAPI report
table reads the same query through ``iterate(params, user, READ)``. Pinned with a query that names a readable and a
denied type (a corrupted or hand-written one - the builder pins one type):

  - the run's read returns only the objects of the readable type, so a stored query cannot widen the result
  - it returns exactly the rows the DocAPI table reads for the same query
  - the preview cap is applied after the ACL stage: the page is filled with readable objects
  - the report list (``ReportsManager.iterate_items(params, user, READ)``) leaves out a report over the denied type,
    from the page and the total
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectsManager, ReportsManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.models.object_model import CmdbObject
from cmdb.models.reports_model.cmdb_report import CmdbReport
from cmdb.models.reports_model.report_query import eval_stored_report_query
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.security.acl.permission import AccessControlPermission
# -------------------------------------------------------------------------------------------------------------------- #

GROUP_ID: int = 1
OTHER_GROUP_ID: int = 2

READABLE_TYPE_ID: int = 98101
DENIED_TYPE_ID: int = 98102
READABLE_OBJECT_IDS: list[int] = [98111, 98112, 98113]
DENIED_OBJECT_IDS: list[int] = [98121, 98122]
ALL_OBJECT_IDS: list[int] = READABLE_OBJECT_IDS + DENIED_OBJECT_IDS
PREVIEW_LIMIT: int = 2

READER: CmdbUser = CmdbUser(public_id=1, user_name='report-run-reader', active=True, group_id=GROUP_ID)

# A stored query naming both types - what the run would read without the ACL
STORED_QUERY: str = str({'$or': [{'type_id': READABLE_TYPE_ID}, {'type_id': DENIED_TYPE_ID}]})


def _type(public_id: int, granted_group: int) -> dict[str, Any]:
    """A type whose activated ACL grants READ to one group"""
    return {
        'public_id': public_id, 'name': f'report-run-{public_id}', 'active': True, 'fields': [],
        'acl': {'activated': True, 'groups': {'includes': {str(granted_group): ['READ']}}},
    }


def _object(public_id: int, type_id: int) -> dict[str, Any]:
    """An active object of a type"""
    return {'public_id': public_id, 'type_id': type_id, 'active': True, 'fields': [], 'author_id': 1}


@pytest.fixture(autouse=True)
def _app_context(rest_api):
    """The REST app's context: the ACL stage reaches the types through ManagerProvider"""
    with rest_api.application.app_context():
        yield


@pytest.fixture(name='seeded', autouse=True)
def fixture_seeded(database_manager: MongoDatabaseManager, database_name: str):
    """A readable and a denied type with their objects, purged before and after"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': {'$in': [READABLE_TYPE_ID, DENIED_TYPE_ID]}})
        objects.delete_many({'public_id': {'$in': ALL_OBJECT_IDS}})

    _purge()
    types.insert_many([_type(READABLE_TYPE_ID, GROUP_ID), _type(DENIED_TYPE_ID, OTHER_GROUP_ID)])
    objects.insert_many(
        [_object(public_id, READABLE_TYPE_ID) for public_id in READABLE_OBJECT_IDS]
        + [_object(public_id, DENIED_TYPE_ID) for public_id in DENIED_OBJECT_IDS]
    )
    yield
    _purge()


def _params(limit: int = 0) -> BuilderParameters:
    """The run's builder parameters for the stored query"""
    return BuilderParameters(criteria=eval_stored_report_query(STORED_QUERY), limit=limit, sort='public_id', order=1)


def test_the_run_reads_only_readable_objects(database_manager: MongoDatabaseManager) -> None:
    """The stored query names both types; the ACL stage keeps the readable one"""
    rows = ObjectsManager(database_manager).iterate_results(_params(), READER, AccessControlPermission.READ)

    assert sorted(row.public_id for row in rows) == READABLE_OBJECT_IDS


def test_without_the_acl_the_same_query_reads_both_types(database_manager: MongoDatabaseManager) -> None:
    """The baseline the route used to answer"""
    rows = ObjectsManager(database_manager).iterate_results(_params())

    assert sorted(row.public_id for row in rows) == sorted(ALL_OBJECT_IDS)


def test_the_run_and_the_docapi_table_read_the_same_rows(database_manager: MongoDatabaseManager) -> None:
    """iterate_results (the run) and iterate (the DocAPI report table), both through the caller's READ ACL"""
    objects_manager = ObjectsManager(database_manager)

    run_rows = objects_manager.iterate_results(_params(), READER, AccessControlPermission.READ)
    table_rows = objects_manager.iterate(_params(), READER, AccessControlPermission.READ).results

    assert [row.public_id for row in run_rows] == [row.public_id for row in table_rows]


def test_the_preview_cap_is_filled_with_readable_objects(database_manager: MongoDatabaseManager) -> None:
    """The ACL stage runs before $limit"""
    rows = ObjectsManager(database_manager).iterate_results(
        _params(PREVIEW_LIMIT), READER, AccessControlPermission.READ,
    )

    assert [row.public_id for row in rows] == READABLE_OBJECT_IDS[:PREVIEW_LIMIT]


READABLE_REPORT_ID: int = 98131
DENIED_REPORT_ID: int = 98132


@pytest.fixture(name='reports')
def fixture_reports(database_manager: MongoDatabaseManager, database_name: str):
    """One report over each type, purged before and after"""
    reports = database_manager.get_collection(CmdbReport.COLLECTION, database_name)
    ids: list[int] = [READABLE_REPORT_ID, DENIED_REPORT_ID]
    reports.delete_many({'public_id': {'$in': ids}})
    reports.insert_many([
        {'public_id': READABLE_REPORT_ID, 'report_category_id': 1, 'name': 'readable', 'type_id': READABLE_TYPE_ID,
         'selected_fields': [], 'conditions': {}, 'report_query': {'data': '{}'}, 'predefined': False,
         'mds_mode': 'ROWS'},
        {'public_id': DENIED_REPORT_ID, 'report_category_id': 1, 'name': 'denied', 'type_id': DENIED_TYPE_ID,
         'selected_fields': [], 'conditions': {}, 'report_query': {'data': '{}'}, 'predefined': False,
         'mds_mode': 'ROWS'},
    ])
    yield
    reports.delete_many({'public_id': {'$in': ids}})


@pytest.mark.usefixtures('reports')
def test_the_report_list_leaves_out_a_report_over_a_denied_type(database_manager: MongoDatabaseManager) -> None:
    """Page and total, through the same ACL stage on the report's own type_id"""
    params = BuilderParameters(criteria={'public_id': {'$in': [READABLE_REPORT_ID, DENIED_REPORT_ID]}})

    result = ReportsManager(database_manager).iterate_items(params, READER, AccessControlPermission.READ)

    assert [report.public_id for report in result.results] == [READABLE_REPORT_ID]
    assert result.total == 1
