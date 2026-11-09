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
The route decorator that holds a rack's placement lock around a mount write

Applied to the two routes that decide where a mount sits (``POST /racks/<rack_id>/mounts/`` and
``PATCH /racks/<rack_id>/mounts/<mount_id>``), below ``protect`` and above ``handle_route_errors``: the lock is
taken once the caller is known to hold the rack right, and the whole handler - the rack read (its height), the
overlap check and the write - runs inside it. A rack whose lock stays held through every attempt answers 400
"""
import functools
from collections.abc import Callable
from typing import Any

from flask import abort

from cmdb.manager import SettingsManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.user_model import CmdbUser
from cmdb.manager.system_manager.settings_section_lock import (
    SectionLockSpec,
    acquire_section_lock,
    release_section_lock,
)
from cmdb.framework.rack.placement_lock import rack_placement_lock_spec
from cmdb.errors.manager.settings_section_lock import SettingsSectionLockHeldError
from cmdb.interface.blueprints.api_blueprint_constants import REQUEST_USER_KWARG
from cmdb.interface.rest_api.routes.rack_routes.rack_route_constants import RackMountRouteError
# -------------------------------------------------------------------------------------------------------------------- #

#: The route parameter naming the rack
RACK_ID_KWARG: str = 'rack_id'


def hold_rack_placement_lock(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Runs a mount-writing route inside the placement lock of the rack its URL names

    Args:
        func (Callable[..., Any]): The route function; called with ``rack_id`` and ``request_user``

    Returns:
        Callable[..., Any]: The wrapped route

    Raises:
        HTTPException: 400 (``RACK_BUSY``) when another request held the rack's lock at every attempt
    """
    @functools.wraps(func)
    def _locked(*args: Any, **kwargs: Any) -> Any:
        request_user: CmdbUser = kwargs[REQUEST_USER_KWARG]
        spec: SectionLockSpec = rack_placement_lock_spec(kwargs[RACK_ID_KWARG])
        settings_manager: SettingsManager = ManagerProvider.get_manager(ManagerType.SETTINGS, request_user)

        try:
            token: str = acquire_section_lock(settings_manager, spec, request_user.public_id)
        except SettingsSectionLockHeldError:
            abort(400, RackMountRouteError.RACK_BUSY.format(rack_id=kwargs[RACK_ID_KWARG]))

        try:
            return func(*args, **kwargs)
        finally:
            release_section_lock(settings_manager, spec, token)

    return _locked
