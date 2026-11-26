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
Unit tests for access_payloads.abort_if_beyond_own_reach

Pure: the grants read and the reach rule are patched. Pinned: no own group reached - nothing read; an own group
reached beyond the caller - 403 with the rule's text; an administrator (group 1) is exempt and reads nothing, so they
can always re-grant themselves
"""
from http import HTTPStatus
from unittest.mock import MagicMock

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.models.user_model import CmdbUser
from cmdb.interface.rest_api.routes.access_routes import access_payloads
from cmdb.interface.rest_api.routes.access_routes.access_payloads import abort_if_beyond_own_reach
# -------------------------------------------------------------------------------------------------------------------- #

OWN_GROUP_ID: int = 21
OTHER_GROUP_ID: int = 22
ROLE_ID: int = 31
ROLE: dict[str, object] = {'types': [5], 'operations': ['edit']}
PROBLEM: str = 'beyond'


def _user(*group_ids: int) -> CmdbUser:
    """A caller in the given groups"""
    return CmdbUser(public_id=41, user_name='reach', active=True, group_ids=list(group_ids))


@pytest.fixture(name='reads')
def fixture_reads(monkeypatch: pytest.MonkeyPatch) -> tuple[MagicMock, MagicMock]:
    """The grants read and the rule, the rule answering a problem"""
    load, rule = MagicMock(return_value='grants'), MagicMock(return_value=PROBLEM)
    monkeypatch.setattr(access_payloads, 'load_grants', load)
    monkeypatch.setattr(access_payloads, 'own_reach_problem', rule)

    return load, rule


def test_an_own_group_reached_beyond_is_a_403(reads: tuple[MagicMock, MagicMock]) -> None:
    """The rule's text, the caller's grants read once"""
    load, rule = reads
    caller = _user(OWN_GROUP_ID)

    with pytest.raises(HTTPException) as raised:
        abort_if_beyond_own_reach(caller, ROLE_ID, ROLE, [OWN_GROUP_ID])

    assert (raised.value.code, raised.value.description) == (HTTPStatus.FORBIDDEN, PROBLEM)
    load.assert_called_once_with(caller)
    rule.assert_called_once_with('grants', ROLE_ID, ROLE, [OWN_GROUP_ID], [OWN_GROUP_ID])


def test_another_group_reads_nothing(reads: tuple[MagicMock, MagicMock]) -> None:
    """Not the caller's group"""
    load, rule = reads

    abort_if_beyond_own_reach(_user(OWN_GROUP_ID), ROLE_ID, ROLE, [OTHER_GROUP_ID])

    load.assert_not_called()
    rule.assert_not_called()


def test_an_administrator_is_exempt_even_for_the_own_group(reads: tuple[MagicMock, MagicMock]) -> None:
    """Group 1 among the caller's groups: nothing read, nothing refused - the way back to a hidden Type"""
    load, rule = reads

    abort_if_beyond_own_reach(_user(OWN_GROUP_ID, 1), ROLE_ID, ROLE, [OWN_GROUP_ID, 1])

    load.assert_not_called()
    rule.assert_not_called()
