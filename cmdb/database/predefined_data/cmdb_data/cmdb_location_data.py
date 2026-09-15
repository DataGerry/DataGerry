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
This module provides the predefined root document for CmdbLocations
"""
from typing import Any

from cmdb.models.location_model.location_constants import LocationKey, RootLocationDefault
# -------------------------------------------------------------------------------------------------------------------- #

def get_root_location_data() -> dict[str, Any]:
    """
    Returns the document for the Root of the CmdbLocations tree

    The root is the implicit parent of every top-level location and is inserted at setup.

    Returns:
        dict[str, Any]: Valid data for the Root CmdbLocation
    """
    return {
        LocationKey.PUBLIC_ID: RootLocationDefault.PUBLIC_ID,
        LocationKey.NAME: RootLocationDefault.NAME,
        LocationKey.PARENT: RootLocationDefault.NO_PARENT,
        LocationKey.OBJECT_ID: RootLocationDefault.NO_OBJECT,
        LocationKey.TYPE_ID: RootLocationDefault.NO_TYPE,
        LocationKey.TYPE_LABEL: RootLocationDefault.NAME,
        LocationKey.TYPE_ICON: RootLocationDefault.ICON,
        LocationKey.TYPE_SELECTABLE: RootLocationDefault.SELECTABLE,
    }
