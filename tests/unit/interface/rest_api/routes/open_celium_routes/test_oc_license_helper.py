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
Unit tests for the OpenCelium license route helpers

The usage paging and the manager construction, extracted from the two routes.

**The paging rule is pinned in both directions on purpose.** An unreadable `?page=` / `?size=`
answers the DEFAULT rather than a 400 - `type=int` is deliberate (a bare `int()` used to crash into a
generic 500), but it means `?page=abc` reads as page 0 as though the caller had asked for it, and a
negative or enormous value passes straight through to OpenCelium. Whether that should be refused
instead is discussion-backlog #226, to be decided with #223; these tests are what makes the decision
visible - they will fail loudly the day it is taken.
"""
from typing import Any

import pytest

from cmdb.interface.cmdb_app import BaseCmdbApp
from cmdb.interface.rest_api.routes.open_celium_routes.oc_license_helper import (
    build_license_manager,
    read_usage_paging,
)

from cmdb.open_celium.oc_constants import (
    OC_DEFAULT_USAGE_PAGE,
    OC_DEFAULT_USAGE_SIZE,
    OC_PAGE_PARAM,
    OC_SIZE_PARAM,
)
# -------------------------------------------------------------------------------------------------------------------- #

USER_DATABASE: str = 'db_customer'

DEFAULT_PAGING: tuple[int, int] = (OC_DEFAULT_USAGE_PAGE, OC_DEFAULT_USAGE_SIZE)


def _app() -> BaseCmdbApp:
    """An on-premise BaseCmdbApp with a stub database manager."""
    app = BaseCmdbApp(__name__)
    app.database_manager = 'the-dbm'
    app.cloud_mode = False
    app.local_mode = False

    return app


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  the usage paging                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestReadUsagePaging:
    """What the usage report is paged by."""

    def test_the_defaults_are_the_ones_the_frontend_asks_for(self) -> None:
        """
        No query parameters at all reads as page 0, size 5

        The frontend always sends both, so this is the API-only path - and the defaults are the same
        constants the manager defaults to, rather than a second pair of literals.
        """
        with _app().test_request_context('/licenses/info'):
            assert read_usage_paging() == DEFAULT_PAGING

    def test_it_reads_both_parameters(self) -> None:
        """Explicit values are answered as sent"""
        with _app().test_request_context(f'/licenses/info?{OC_PAGE_PARAM}=3&{OC_SIZE_PARAM}=25'):
            assert read_usage_paging() == (3, 25)

    def test_each_parameter_defaults_on_its_own(self) -> None:
        """One of the two sent is not a reason to drop the other"""
        with _app().test_request_context(f'/licenses/info?{OC_SIZE_PARAM}=25'):
            assert read_usage_paging() == (OC_DEFAULT_USAGE_PAGE, 25)

        with _app().test_request_context(f'/licenses/info?{OC_PAGE_PARAM}=3'):
            assert read_usage_paging() == (3, OC_DEFAULT_USAGE_SIZE)

    @pytest.mark.parametrize('value', ['abc', '1.5', '', ' ', '2,3'])
    def test_an_unreadable_value_silently_defaults(self, value: str) -> None:
        """
        A value that is not a whole number reads as the default, not as a 400

        Recorded as behaviour, not asserted as desirable: the caller asked for something and is
        answered something else without being told. Discussion-backlog #226.
        """
        with _app().test_request_context(f'/licenses/info?{OC_PAGE_PARAM}={value}'):
            assert read_usage_paging() == DEFAULT_PAGING

    def test_a_negative_page_passes_through(self) -> None:
        """
        Nothing here clamps - OpenCelium decides what exists

        Deliberate for a proxy, and the other half of #226: DataGerry's own pager refuses these,
        this one forwards them.
        """
        with _app().test_request_context(f'/licenses/info?{OC_PAGE_PARAM}=-1&{OC_SIZE_PARAM}=-10'):
            assert read_usage_paging() == (-1, -10)

    def test_a_zero_size_passes_through(self) -> None:
        """`?size=0` is forwarded as asked, not read as "unset" - 0 is falsy, not absent"""
        with _app().test_request_context(f'/licenses/info?{OC_SIZE_PARAM}=0'):
            assert read_usage_paging() == (OC_DEFAULT_USAGE_PAGE, 0)

    def test_an_enormous_size_passes_through(self) -> None:
        """No upper bound either; the page size a tenant may ask OpenCelium for is not capped here"""
        with _app().test_request_context(f'/licenses/info?{OC_SIZE_PARAM}=1000000'):
            assert read_usage_paging() == (OC_DEFAULT_USAGE_PAGE, 1_000_000)

    def test_a_repeated_parameter_reads_the_first(self) -> None:
        """Werkzeug's own rule for a repeated key, recorded so a change in it would be noticed"""
        with _app().test_request_context(f'/licenses/info?{OC_PAGE_PARAM}=1&{OC_PAGE_PARAM}=2'):
            assert read_usage_paging() == (1, OC_DEFAULT_USAGE_SIZE)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 the manager factory                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBuildLicenseManager:
    """The construction the two license routes used to repeat."""

    def test_it_scopes_the_manager_to_the_users_database(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        The caller's database selects the OpenCelium installation to ask

        Both route tests patch this factory out, so its body is asserted here - otherwise the one
        line that reaches OcLicenseManager would be covered by nothing.
        """
        recorded: dict[str, Any] = {}

        class _RecordingManager:
            """Captures how the factory constructs the manager."""

            def __init__(self, dbm: Any, database: str) -> None:
                """Records both arguments."""
                recorded['dbm'] = dbm
                recorded['database'] = database

        monkeypatch.setattr(
            'cmdb.interface.rest_api.routes.open_celium_routes.oc_license_helper.OcLicenseManager',
            _RecordingManager,
        )

        request_user = type('_User', (), {'database': USER_DATABASE})()

        with _app().test_request_context():
            manager = build_license_manager(request_user)

        assert isinstance(manager, _RecordingManager)
        assert recorded == {'dbm': 'the-dbm', 'database': USER_DATABASE}
