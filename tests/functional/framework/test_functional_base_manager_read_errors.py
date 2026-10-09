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
Functional coverage of how a list route answers a failed read now that BaseManager wraps only database errors

BaseManager's iteration catches only what the database layer raises - the time-limit error, an aggregation failure,
a failed read of the denied types - and passes each on once. These pin that the routes still answer each of them as
before: the time budget as the shared 503, the rest as the route's own 400
"""
from http import HTTPStatus

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.errors.database import DocumentAggregationError, DocumentQueryTimeLimitError
from cmdb.errors.manager import BaseManagerGetError
from cmdb.manager import base_manager
# -------------------------------------------------------------------------------------------------------------------- #

CATEGORIES_URL: str = '/categories/?limit=10'
OBJECTS_URL: str = '/objects/?limit=10'
TIME_LIMIT_MS: int = 10000
CATEGORIES_FAILED_MSG: str = 'Could not retrieve Categories from database!'
OBJECTS_FAILED_MSG: str = 'Failed to retrieve Objects from the database!'


def _fail_every_aggregation(monkeypatch: pytest.MonkeyPatch, failure: Exception) -> None:
    """The database layer's time-limited aggregation raises the given error"""
    def _raise(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr(MongoDatabaseManager, 'aggregate_within_time_limit', _raise)


def test_a_query_past_its_time_budget_still_answers_503(rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
    """Wrapped once by BaseManager, once by the domain manager: the route still finds the cause"""
    _fail_every_aggregation(monkeypatch, DocumentQueryTimeLimitError('slow', TIME_LIMIT_MS))

    response = rest_api.get(CATEGORIES_URL)

    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE


def test_a_failed_aggregation_still_answers_the_routes_400(rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
    """A database failure is still the manager's iteration error, which the route answers itself"""
    _fail_every_aggregation(monkeypatch, DocumentAggregationError('down'))

    response = rest_api.get(CATEGORIES_URL)

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.get_json()['message'] == CATEGORIES_FAILED_MSG


def test_a_failed_read_of_the_denied_types_still_answers_the_routes_400(
        rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
    """The access-control read is a database read too: wrapped as the iteration error, not let through"""
    def _unreadable(*_args, **_kwargs):
        raise BaseManagerGetError('types unreadable')

    monkeypatch.setattr(base_manager, 'resolve_denied_type_ids', _unreadable)

    response = rest_api.get(OBJECTS_URL)

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.get_json()['message'] == OBJECTS_FAILED_MSG
