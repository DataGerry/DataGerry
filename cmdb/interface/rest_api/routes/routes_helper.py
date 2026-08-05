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
Implementation of general API route helpers
"""
from logging import Logger, getLogger
from flask import request, abort

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import LocationsManager

from cmdb.models.user_model.cmdb_user import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

def fetch_only_active_objects() -> bool:
    """
    Checking if request have cookie parameter for object active state

    Returns:
        bool: True if cookie value is true or True else False
    """
    return request.args.get('onlyActiveObjCookie') in ['True', 'true']


def extract_public_ids(public_ids: str) -> list[int]:
    """TODO: document"""
    extracted_ids: list[int] = []

    for v in public_ids.split(","):
        try:
            extracted_ids.append(int(v))
        except (ValueError, TypeError):
            abort(400, f"Invalid value detected for public_id: {v} !")

    return extracted_ids


def object_has_location(request_user: CmdbUser, public_id: int) -> bool:
    """TODO: document"""
    locations_manager: LocationsManager = ManagerProvider.get_manager(ManagerType.LOCATIONS, request_user)

    return locations_manager.get_location_for_object(public_id) is not None
