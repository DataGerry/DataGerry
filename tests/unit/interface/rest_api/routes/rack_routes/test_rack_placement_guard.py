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
Unit tests for rack_placement_guard.hold_rack_placement_lock - the route decorator around a mount write

The lock is the rack's placement lock; the route runs inside it, a lock held through every attempt is a 400 naming
the rack, and the lock is released after a success, an answer the route aborts with and an error alike
"""
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.exceptions import BadRequest, NotFound

from cmdb.manager.manager_provider_model import ManagerType
from cmdb.manager.system_manager.settings_section_lock_constants import SectionLockKey
from cmdb.interface.rest_api.routes.rack_routes.rack_placement_guard import hold_rack_placement_lock
from cmdb.interface.rest_api.routes.rack_routes.rack_route_constants import RackMountRouteError
# -------------------------------------------------------------------------------------------------------------------- #

GUARD_PATH: str = 'cmdb.interface.rest_api.routes.rack_routes.rack_placement_guard'
RACK_ID: int = 3301
USER_ID: int = 12
SECTION: str = 'rack_placement_lock_3301'
ANSWER: str = 'the route answer'


def _user() -> MagicMock:
    """The request user"""
    user = MagicMock()
    user.public_id = USER_ID

    return user


def _settings(claimed: bool = True) -> MagicMock:
    """A SettingsManager whose claim answers ``claimed`` and that never takes over"""
    settings = MagicMock()
    settings.claim_section.return_value = claimed
    settings.claim_section_where.return_value = False

    return settings


def _call(settings: MagicMock, route: Any) -> Any:
    """Calls the decorated route with the rack and the user as Flask would"""
    with patch(f'{GUARD_PATH}.ManagerProvider.get_manager', return_value=settings) as get_manager, \
         patch('cmdb.manager.system_manager.settings_section_lock.sleep'):
        answer: Any = hold_rack_placement_lock(route)(rack_id=RACK_ID, request_user=_user())

    assert get_manager.call_args.args[0] == ManagerType.SETTINGS
    return answer


def test_the_route_runs_inside_the_racks_lock_and_releases_it() -> None:
    """Claimed before the route, released after, the route's answer passed through"""
    settings = _settings()
    seen: list[int] = []

    def route(rack_id: int, request_user: Any) -> str:
        seen.append(settings.delete_section.call_count)
        assert (rack_id, request_user.public_id) == (RACK_ID, USER_ID)
        return ANSWER

    assert _call(settings, route) == ANSWER
    assert seen == [0], 'not released while the route runs'
    assert settings.claim_section.call_args.args[0] == SECTION
    assert settings.claim_section.call_args.args[1][SectionLockKey.USER_ID.value] == USER_ID
    settings.delete_section.assert_called_once()


def test_a_rack_that_stays_busy_is_a_400_and_the_route_never_runs() -> None:
    """Held at every attempt: RACK_BUSY naming the rack; nothing to release"""
    settings = _settings(claimed=False)
    route = MagicMock()

    with pytest.raises(BadRequest) as refused:
        _call(settings, route)

    assert refused.value.description == RackMountRouteError.RACK_BUSY.format(rack_id=RACK_ID)
    route.assert_not_called()
    settings.delete_section.assert_not_called()


@pytest.mark.parametrize('failure', [NotFound('no such rack'), RuntimeError('write failed')], ids=['abort', 'error'])
def test_the_lock_is_released_after_a_refusal_or_an_error(failure: Exception) -> None:
    """The route's own answer stands, and the rack is free again"""
    settings = _settings()

    def route(**_kwargs: Any) -> None:
        raise failure

    with pytest.raises(type(failure)):
        _call(settings, route)

    settings.delete_section.assert_called_once()
