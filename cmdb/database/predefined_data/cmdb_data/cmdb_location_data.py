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
This package provides all predefined data for CmdbLocations
"""
# -------------------------------------------------------------------------------------------------------------------- #

def get_root_location_data() -> dict:
    """
    This method holds the correct data for the Root of CmdbLocations
    Returns:
        (dict): Returns valid data for the Root of CmdbLocations
    """
    return {
        "public_id": 1,
        "name": "Root",
        "parent": 0,
        "object_id": 0,
        "type_id": 0,
        "type_label": "Root",
        "type_icon": "fas fa-globe",
        "type_selectable": True,
    }
