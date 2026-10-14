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
Functional coverage for what a route answers when a narrowed manager fails

``ObjectsManager`` and ``GenericManager`` catch only the failures their calls raise. A database failure - the
``BaseManager*Error`` of the call - is still the manager's own error and the route's 400 with its message. A
programming error is no longer wrapped into that 400 ("Failed to retrieve ... from the database"): it reaches the
route's generic tail and answers 500.

Probed before the change: a TypeError injected under ``ObjectsManager.get_one`` answered ``GET /objects/<id>``
with 400 *Failed to retrieve the Object with ID: ... from the database!*
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any
from unittest.mock import patch

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.objects_manager import ObjectsManager
from cmdb.manager.report_categories_manager import ReportCategoriesManager
from cmdb.models.object_model import CmdbObject
from cmdb.models.reports_model.cmdb_report_category import CmdbReportCategory
from cmdb.models.type_model import CmdbType
from cmdb.errors.manager import BaseManagerGetError, BaseManagerIterationError

from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID: int = 97101
OBJECT_ID: int = 97102
CATEGORY_ID: int = 97103

# route, the manager and delegate under it, and the typed failure that delegate raises
CASES: list[tuple[str, type, str, type[Exception]]] = [
    (f'/objects/{OBJECT_ID}', ObjectsManager, 'get_one', BaseManagerGetError),
    ('/objects/', ObjectsManager, 'iterate_query', BaseManagerIterationError),
    (f'/report_categories/{CATEGORY_ID}', ReportCategoriesManager, 'get_one', BaseManagerGetError),
    ('/report_categories/', ReportCategoriesManager, 'iterate_query', BaseManagerIterationError),
]
CASE_IDS: list[str] = ['object', 'objects', 'report-category', 'report-categories']


@pytest.fixture(autouse=True)
def _seeded(database_manager: MongoDatabaseManager, database_name: str):
    """A type, one object of it and a report category; removed again afterwards"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    categories = database_manager.get_collection(CmdbReportCategory.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': TYPE_ID})
        objects.delete_many({'public_id': OBJECT_ID})
        categories.delete_many({'public_id': CATEGORY_ID})

    _purge()
    types.insert_one(make_type_doc(TYPE_ID, 'manager-error-status'))
    objects.insert_one({'public_id': OBJECT_ID, 'type_id': TYPE_ID, 'active': True, 'author_id': 1,
                        'version': '1.0.0', 'creation_time': datetime.now(timezone.utc), 'fields': []})
    categories.insert_one({'public_id': CATEGORY_ID, 'name': 'manager-error-status', 'predefined': False})

    yield

    _purge()


@pytest.mark.parametrize('url, manager, delegate, typed', CASES, ids=CASE_IDS)
def test_the_route_answers_without_a_failure(rest_api, url: str, manager: type, delegate: str,
                                             typed: type[Exception]) -> None:
    """The control: each route answers 200 as it stands"""
    del manager, delegate, typed

    assert rest_api.get(url).status_code == HTTPStatus.OK


@pytest.mark.parametrize('url, manager, delegate, typed', CASES, ids=CASE_IDS)
def test_a_programming_error_answers_500(rest_api, url: str, manager: type, delegate: str,
                                         typed: type[Exception]) -> None:
    """Not the 400 a failed read gets: the bug is the server's, and is no longer dressed up as a database failure"""
    del typed

    with patch.object(manager, delegate, side_effect=TypeError('a programming error')):
        response = rest_api.get(url)

    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR


@pytest.mark.parametrize('url, manager, delegate, typed', CASES, ids=CASE_IDS)
def test_a_database_failure_still_answers_400(rest_api, url: str, manager: type, delegate: str,
                                              typed: type[Exception]) -> None:
    """The call's own failure is the manager's error, which the route's table answers 400 with its message"""
    with patch.object(manager, delegate, side_effect=typed('the read failed')):
        response = rest_api.get(url)

    body: dict[str, Any] = response.get_json()

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert body['message']
