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
Right-per-route mapping for the /reports and /report_categories routes

This pins WHICH right each of the twelve routes asks for, by patching `user_has_right` at the
api_blueprint module path - the single place `.protect` consults - and recording the argument

It deliberately does NOT repeat the enforcement tests: `TestReportRouteRights` /
`TestReportCategoryRouteRights` (and their `*RightsAreDistinct` siblings) already prove with REAL
users and groups that a user without the right is refused and that a view-only user cannot write.
What those cannot see is a confusion between two WRITE rights - if the delete route asked for EDIT,
a no-rights user would still get 403 and a view-only user would still get 403, so every existing
test would pass. That is the gap this module closes, for the reports the same way
tests/functional/webhook/test_functional_webhook_rights.py does for the webhooks
"""
from typing import Any, Callable
from urllib.parse import urlencode

import pytest

from cmdb.interface.rest_api.routes.report_routes.report_constants import ReportRight
# -------------------------------------------------------------------------------------------------------------------- #

API_BLUEPRINT_PATH: str = 'cmdb.interface.blueprints.api_blueprint.user_has_right'
REPORTS_URL: str = '/reports'
REPORT_CATEGORIES_URL: str = '/report_categories'
PROBE_ID: int = 88501
PROBE_TYPE_ID: int = 88502

CREATE_QUERY: str = urlencode({'name': 'rights-mapping-probe', 'type_id': PROBE_TYPE_ID})

# (label, HTTP method, URL, the right the route must ask for)
GUARDED_ROUTES: list[tuple[str, str, str, str]] = [
    ('create_cmdb_report', 'POST', f'{REPORTS_URL}/?{CREATE_QUERY}', ReportRight.ADD.value),
    ('get_cmdb_report', 'GET', f'{REPORTS_URL}/{PROBE_ID}', ReportRight.VIEW.value),
    ('get_cmdb_reports', 'GET', f'{REPORTS_URL}/', ReportRight.VIEW.value),
    ('count_cmdb_reports_of_type', 'GET', f'{REPORTS_URL}/{PROBE_TYPE_ID}/count_reports_of_type',
     ReportRight.VIEW.value),
    ('run_cmdb_report_query', 'GET', f'{REPORTS_URL}/run/{PROBE_ID}', ReportRight.VIEW.value),
    ('update_cmdb_report', 'PUT', f'{REPORTS_URL}/{PROBE_ID}?{CREATE_QUERY}', ReportRight.EDIT.value),
    ('delete_cmdb_report', 'DELETE', f'{REPORTS_URL}/{PROBE_ID}', ReportRight.DELETE.value),
    ('create_cmdb_report_category', 'POST', f'{REPORT_CATEGORIES_URL}/', ReportRight.ADD.value),
    ('get_cmdb_report_category', 'GET', f'{REPORT_CATEGORIES_URL}/{PROBE_ID}', ReportRight.VIEW.value),
    ('get_cmdb_report_categories', 'GET', f'{REPORT_CATEGORIES_URL}/', ReportRight.VIEW.value),
    ('update_cmdb_report_category', 'PUT', f'{REPORT_CATEGORIES_URL}/{PROBE_ID}', ReportRight.EDIT.value),
    ('delete_cmdb_report_category', 'DELETE', f'{REPORT_CATEGORIES_URL}/{PROBE_ID}', ReportRight.DELETE.value),
]

ROUTE_IDS: list[str] = [route[0] for route in GUARDED_ROUTES]


def _call(rest_api, method: str, url: str):
    """Issues the request with the verb the route is registered for."""
    verb: Callable[..., Any] = getattr(rest_api, method.lower())

    return verb(url)


@pytest.mark.parametrize('label, method, url, expected_right', GUARDED_ROUTES, ids=ROUTE_IDS)
def test_route_asks_for_its_own_report_right(rest_api, monkeypatch, label, method, url, expected_right) -> None:
    """
    Each route asks `.protect` for exactly the right of its operation

    The probe ids name nothing, so every handler that runs answers 404 or 400 - the assertion is on the
    recorded right, not on the response
    """
    del label
    asked_rights: list[str] = []

    def _record(right: str, user: Any = None) -> bool:
        del user
        asked_rights.append(right)

        return True

    monkeypatch.setattr(API_BLUEPRINT_PATH, _record)

    _call(rest_api, method, url)

    assert asked_rights == [expected_right]
