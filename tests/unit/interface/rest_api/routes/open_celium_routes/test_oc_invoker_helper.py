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
Unit tests for the OpenCelium invoker route helpers

The `opsIncluded` flag and the manager construction, extracted from the routes.

**The flag's rule is pinned in both directions on purpose.** Operations are included by default and
only the literal `false` turns them off; `0`, `no`, `off` and an EMPTY value all mean "include"
today. That is deliberate rather than accidental - `request.args.get(..., type=bool)` answers True
for the string `'false'`, which is the footgun the explicit parse avoids - but whether the other
spellings should also disable operations is discussion-backlog #223. These tests are what makes that
decision visible: they will fail loudly when it is taken, which is the point.
"""
from typing import Any

import pytest

from cmdb.interface.cmdb_app import BaseCmdbApp
from cmdb.interface.rest_api.routes.open_celium_routes.oc_invoker_helper import (
    build_invoker_manager,
    read_ops_included_flag,
)

from cmdb.open_celium.oc_constants import OC_OPS_INCLUDED_PARAM
# -------------------------------------------------------------------------------------------------------------------- #

USER_DATABASE: str = 'db_customer'


def _app() -> BaseCmdbApp:
    """An on-premise BaseCmdbApp with a stub database manager."""
    app = BaseCmdbApp(__name__)
    app.database_manager = 'the-dbm'
    app.cloud_mode = False
    app.local_mode = False

    return app


# -------------------------------------------------------------------------------------------------------------------- #
#                                                the opsIncluded flag                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TestReadOpsIncludedFlag:
    """Whether the invokers are requested with their operations."""

    def test_the_default_includes_operations(self) -> None:
        """
        The frontend sends no query parameters at all

        An invoker without its operations is the cheaper read, not the expected one - the connector
        form needs the operations.
        """
        with _app().test_request_context('/invokers'):
            assert read_ops_included_flag() is True

    def test_the_literal_false_disables_them(self) -> None:
        """The one value that turns the flag off"""
        with _app().test_request_context(f'/invokers?{OC_OPS_INCLUDED_PARAM}=false'):
            assert read_ops_included_flag() is False

    @pytest.mark.parametrize('value', ['False', 'FALSE', 'fAlSe'])
    def test_the_casing_does_not_matter(self, value: str) -> None:
        """A query string is typed by a human or built by a client; the casing is not the signal"""
        with _app().test_request_context(f'/invokers?{OC_OPS_INCLUDED_PARAM}={value}'):
            assert read_ops_included_flag() is False

    def test_true_includes_them(self) -> None:
        """Stating the default explicitly does what it says"""
        with _app().test_request_context(f'/invokers?{OC_OPS_INCLUDED_PARAM}=true'):
            assert read_ops_included_flag() is True

    @pytest.mark.parametrize('value', ['0', 'no', 'off', 'null', 'False!'])
    def test_other_falsy_looking_spellings_still_include_them(self, value: str) -> None:
        """
        Only `false` disables - recorded as behaviour, not asserted as desirable

        Whether these should disable operations too is discussion-backlog #223. Pinning them here is
        what makes that decision visible: the day it is taken, these expectations flip.
        """
        with _app().test_request_context(f'/invokers?{OC_OPS_INCLUDED_PARAM}={value}'):
            assert read_ops_included_flag() is True

    def test_an_empty_value_still_includes_them(self) -> None:
        """
        `?opsIncluded=` means "include" today

        The case most likely to surprise a caller who sent the parameter and left it blank - the
        other half of #223.
        """
        with _app().test_request_context(f'/invokers?{OC_OPS_INCLUDED_PARAM}='):
            assert read_ops_included_flag() is True

    def test_the_string_false_is_not_read_for_truthiness(self) -> None:
        """
        The footgun the explicit parse exists for

        `request.args.get(name, type=bool)` answers True for `'false'`, because `bool('false')` is
        True - so the flag would be impossible to turn off.
        """
        with _app().test_request_context(f'/invokers?{OC_OPS_INCLUDED_PARAM}=false'):
            assert read_ops_included_flag() is not bool('false')


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 the manager factory                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBuildInvokerManager:
    """The construction the three invoker routes used to repeat."""

    def test_it_scopes_the_manager_to_the_users_database(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        The caller's database selects the OpenCelium installation to read from

        Every route test patches this factory out, so its body is asserted here - otherwise the one
        line that reaches OcInvokerManager would be covered by nothing.
        """
        recorded: dict[str, Any] = {}

        class _RecordingManager:
            """Captures how the factory constructs the manager."""

            def __init__(self, dbm: Any, database: str) -> None:
                """Records both arguments."""
                recorded['dbm'] = dbm
                recorded['database'] = database

        monkeypatch.setattr(
            'cmdb.interface.rest_api.routes.open_celium_routes.oc_invoker_helper.OcInvokerManager',
            _RecordingManager,
        )

        request_user = type('_User', (), {'database': USER_DATABASE})()

        with _app().test_request_context():
            manager = build_invoker_manager(request_user)

        assert isinstance(manager, _RecordingManager)
        assert recorded == {'dbm': 'the-dbm', 'database': USER_DATABASE}
