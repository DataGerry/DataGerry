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
Helper methods shared by the OpenCelium Scheduler (Automation) REST routes
"""
from logging import Logger, getLogger

from flask import abort, current_app

from cmdb.manager import DgServicePortalManager, CachedUserManager
from cmdb.open_celium import CachedOcIdType

from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)


def assert_scheduler_access(request_user: CmdbUser, scheduler_id: int) -> None:
    """
    In cloud mode, asserts the given Automation (scheduler) belongs to the requesting user

    Checks the user's cache first, then the DataGerry Service Portal. On-premise this is a no-op
    (there is no per-tenant OpenCelium id mapping). Consolidates the cache-first access check the
    scheduler read / execute / update routes each performed inline.

    Args:
        request_user (CmdbUser): The user making the request
        scheduler_id (int): The schedulerId to validate access for

    Raises:
        HTTPException: 400 when the scheduler is not accessible to the requesting user
    """
    if not (current_app.cloud_mode and not current_app.local_mode):
        return

    cached_user_manager = CachedUserManager(current_app.database_manager)
    dg_sp_manager = DgServicePortalManager()

    cached_user = cached_user_manager.get_cached_user(request_user.email)

    if cached_user:
        is_valid = cached_user_manager.oc_id_exists(
            cached_user,
            request_user.database,
            CachedOcIdType.SCHEDULERS,
            scheduler_id,
        )
    else:
        is_valid = dg_sp_manager.check_scheduler_in_sub(
            scheduler_id,
            request_user.email,
            request_user.database,
        )

    if not is_valid:
        abort(400, f"The target Automation with ID:{scheduler_id} was not found!")
