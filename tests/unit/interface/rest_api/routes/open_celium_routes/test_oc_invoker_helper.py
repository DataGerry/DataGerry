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

**The flag follows the API's one rule for boolean query parameters.** Operations are included by
default; `true` / `false` in any casing set it; any other value - `0`, `no`, `off`, an EMPTY value - is
refused with a 400 rather than guessed at.
"""
from typing import Any

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.interface.cmdb_app import BaseCmdbApp
from cmdb.interface.rest_api.routes.open_celium_routes.oc_invoker_helper import (
    build_invoker_manager,
    read_ops_included_flag,
)

from cmdb.open_celium.oc_constants import OC_OPS_INCLUDED_PARAM
# -------------------------------------------------------------------------------------------------------------------- #

USER_DATABASE: str = 'db_customer'
HTTP_BAD_REQUEST: int = 400


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

    def test_surrounding_whitespace_is_ignored(self) -> None:
        """A padded value is still the value it spells"""
        with _app().test_request_context(f'/invokers?{OC_OPS_INCLUDED_PARAM}=%20false%20'):
            assert read_ops_included_flag() is False

    @pytest.mark.parametrize('value', ['', '0', 'no', 'off', 'null', 'False!', '1', 'yes'])
    def test_any_other_value_is_refused(self, value: str) -> None:
        """
        Refused rather than guessed at - an empty `?opsIncluded=` included

        A caller who sent the parameter meant something; reading `0` or a blank as "include" answered the
        opposite of what they most likely asked for
        """
        with _app().test_request_context(f'/invokers?{OC_OPS_INCLUDED_PARAM}={value}'), \
                pytest.raises(HTTPException) as refused:
            read_ops_included_flag()

        assert refused.value.code == HTTP_BAD_REQUEST
        assert OC_OPS_INCLUDED_PARAM in refused.value.description

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

    @pytest.mark.parametrize('cloud_mode, expected', [(True, USER_DATABASE), (False, None)],
                             ids=['cloud', 'on-premise'])
    def test_it_scopes_the_manager_to_the_users_database(
        self, monkeypatch: pytest.MonkeyPatch, cloud_mode: bool, expected: str | None,
    ) -> None:
        """
        The caller's tenant database in cloud mode; on premise None - the configured database

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

        request_user = type('_User', (), {'database': expected})()

        app = _app()
        app.cloud_mode = cloud_mode

        with app.test_request_context():
            manager = build_invoker_manager(request_user)

        assert isinstance(manager, _RecordingManager)
        assert recorded == {'dbm': 'the-dbm', 'database': expected}
