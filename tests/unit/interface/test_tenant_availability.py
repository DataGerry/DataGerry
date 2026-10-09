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
Unit tests for cmdb.interface.tenant_availability

`abort_if_tenant_unavailable` answers 503 for a tenant in the app's `unavailable_tenants` and lets every
other tenant - and a request bound to no tenant - through. The three call sites are pinned in their own
modules' tests (route_utils, auth_helper cloud login)
"""
from http import HTTPStatus

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.interface.cmdb_app import BaseCmdbApp
from cmdb.interface.tenant_availability import abort_if_tenant_unavailable
from cmdb.interface.tenant_availability_constants import TENANT_UNAVAILABLE_RESPONSE_MESSAGE
# -------------------------------------------------------------------------------------------------------------------- #

UNAVAILABLE_TENANT: str = 'tenant_failed_update'
HEALTHY_TENANT: str = 'tenant_up_to_date'


def _app(unavailable: frozenset[str]) -> BaseCmdbApp:
    """Builds the app with the given unavailable tenants."""
    app = BaseCmdbApp(__name__)
    app.unavailable_tenants = unavailable

    return app


def test_an_unavailable_tenant_is_answered_503() -> None:
    """The fenced-off tenant gets the 503 and its message"""
    with _app(frozenset({UNAVAILABLE_TENANT})).app_context():
        with pytest.raises(HTTPException) as exc_info:
            abort_if_tenant_unavailable(UNAVAILABLE_TENANT)

    assert exc_info.value.code == HTTPStatus.SERVICE_UNAVAILABLE
    assert exc_info.value.description == TENANT_UNAVAILABLE_RESPONSE_MESSAGE


@pytest.mark.parametrize('database', [HEALTHY_TENANT, None, ''], ids=['other-tenant', 'none', 'empty'])
def test_anything_else_passes(database: str | None) -> None:
    """Another tenant, or no tenant at all, is never refused"""
    with _app(frozenset({UNAVAILABLE_TENANT})).app_context():
        assert abort_if_tenant_unavailable(database) is None


def test_a_fresh_app_fences_off_nothing() -> None:
    """The default is an empty set: every tenant passes"""
    app = BaseCmdbApp(__name__)

    with app.app_context():
        assert app.unavailable_tenants == frozenset()
        assert abort_if_tenant_unavailable(UNAVAILABLE_TENANT) is None
