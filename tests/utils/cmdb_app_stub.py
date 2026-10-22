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
A BaseCmdbApp for unit tests: no database, the deployment mode chosen by the test

A unit test that drives a helper reading ``current_app`` needs an app context and the app's mode flags - never a real
MongoDB. The one builder every unit test uses, so the app a test runs in is built one way:

    - ``database_manager`` defaults to a fresh MagicMock the test can program. ``None`` keeps the app without one (the
      SPA host's shape), so code that wrongly reads ``current_app.database_manager`` fails instead of reading a mock;
      any other value - a sentinel the test compares against - is set as it is
    - ``unavailable_tenants`` are the tenant databases the app fences off (``tenant_availability``), empty by default

Tests whose code reads nothing but ``current_app.cloud_mode`` may keep a plain ``Flask`` app instead
"""
from typing import Any
from unittest.mock import MagicMock

from cmdb.interface.cmdb_app import BaseCmdbApp
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = ['stub_cmdb_app']

# Stands for "no database_manager argument given": None is a value a test may pass
_FRESH_MOCK: Any = object()


def stub_cmdb_app(
        cloud_mode: bool = False,
        local_mode: bool = False,
        *,
        database_manager: Any = _FRESH_MOCK,
        unavailable_tenants: frozenset[str] = frozenset()) -> BaseCmdbApp:
    """
    Builds a BaseCmdbApp for a unit test

    Args:
        cloud_mode (bool): Whether the app runs as the cloud product. Defaults to False (on premise)
        local_mode (bool): Whether the cloud product runs on a developer machine. Defaults to False
        database_manager (Any): The app's database manager. Keyword only. Defaults to a fresh MagicMock; None leaves
            the app without one; any other value is set as given
        unavailable_tenants (frozenset[str]): The tenant databases the app answers 503 for. Keyword only. Defaults to
            none

    Returns:
        BaseCmdbApp: The app; enter ``app.test_request_context()`` or ``app.app_context()`` to use it
    """
    app = BaseCmdbApp(__name__, database_manager=MagicMock() if database_manager is _FRESH_MOCK else database_manager)
    app.cloud_mode = cloud_mode
    app.local_mode = local_mode
    app.unavailable_tenants = unavailable_tenants

    return app
