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
Unit tests for cmdb.interface.rest_api.api_level_enum.ApiLevel

The values are compared with the `api_level` the Service Portal stores for an account, so they are pinned; and
`LOCKED`, numerically the highest, is no level an account can reach - the check refuses it before comparing
"""
from flask import Flask
import pytest

from cmdb.interface import route_utils
from cmdb.interface.rest_api.api_level_enum import ApiLevel
# -------------------------------------------------------------------------------------------------------------------- #

# The values the Service Portal's account records are compared against
PORTAL_VALUES: dict[str, int] = {'NO_API': 0, 'ADMIN': 1, 'SUPER_ADMIN': 2, 'LOCKED': 3}

# An account level above every member
UNREACHABLE_LEVEL: int = 99

_check_api_level = getattr(route_utils, '__check_api_level')


def _cloud_app() -> Flask:
    """An app in cloud mode, where the level is checked"""
    app = Flask(__name__)
    app.cloud_mode = True

    return app


class TestTheValues:
    """The members and their values are the portal's contract"""

    def test_the_values_are_pinned(self) -> None:
        """Renumbering would silently regrade every account"""
        assert {member.name: member.value for member in ApiLevel} == PORTAL_VALUES


class TestLocked:
    """LOCKED is refused, never compared"""

    @pytest.mark.parametrize('account', [
        {'api_level': UNREACHABLE_LEVEL, 'subscriptions': [{'api_level': UNREACHABLE_LEVEL}]},
        {'api_level': ApiLevel.LOCKED.value, 'subscriptions': [{'api_level': ApiLevel.LOCKED.value}]},
    ], ids=['above-every-level', 'equal-to-locked'])
    def test_no_account_reaches_locked(self, account: dict) -> None:
        """Even an account graded above LOCKED's value is refused"""
        with _cloud_app().test_request_context():
            assert _check_api_level(account, ApiLevel.LOCKED) is False

    def test_the_same_account_reaches_every_other_level(self) -> None:
        """The refusal is LOCKED's own, not the account's"""
        account = {'api_level': UNREACHABLE_LEVEL, 'subscriptions': [{'api_level': UNREACHABLE_LEVEL}]}

        with _cloud_app().test_request_context():
            assert all(_check_api_level(account, level) for level in ApiLevel if level != ApiLevel.LOCKED)
