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
Constants of the DataGerry Assistant (special) REST routes

The assistant seeds an empty installation with starter CmdbTypes and their CmdbCategories, so running it asks for
the rights to create both (``ASSISTANT_RIGHTS``), and offering it (``GET /special/intro``) asks the same of the caller.
It runs once per installation: ``ASSISTANT_SETTINGS_SECTION`` is the settings section its first run claims
"""
from cmdb.models.type_model.type_constants import TypeRight
from cmdb.interface.rest_api.routes.framework_routes.cmdb_categories.categories_constants import CategoryRight
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'ASSISTANT_RIGHTS',
    'ASSISTANT_SETTINGS_SECTION',
    'AssistantMarkerKey',
    'PROFILE_SEPARATOR',
    'PROFILE_SELECTION_PARAM',
    'NO_PROFILES_MESSAGE',
    'UNKNOWN_PROFILES_MESSAGE',
    'FRAMEWORK_DATA_EXISTS_MESSAGE',
    'ASSISTANT_ALREADY_RAN_MESSAGE',
    'ASSISTANT_RESIDUE_MESSAGE',
    'ASSISTANT_READ_FAILED_MESSAGE',
]

# The rights running the assistant needs: it creates CmdbTypes and CmdbCategories
ASSISTANT_RIGHTS: tuple[str, ...] = (TypeRight.ADD.value, CategoryRight.ADD.value)

# The settings section the first run of the assistant claims - its existence means "the assistant has run here"
ASSISTANT_SETTINGS_SECTION: str = 'datagerry_assistant'


class AssistantMarkerKey:
    """Keys of the marker section"""
    CLAIMED_BY = 'claimed_by'
    CLAIMED_AT = 'claimed_at'


# The query parameter carrying the selected profiles, and what separates them (a frontend contract)
PROFILE_SELECTION_PARAM: str = 'data'
PROFILE_SEPARATOR: str = '#'

NO_PROFILES_MESSAGE: str = "No profiles were provided!"
UNKNOWN_PROFILES_MESSAGE: str = "Unknown profile(s): {names}!"
FRAMEWORK_DATA_EXISTS_MESSAGE: str = (
    "There are objects, types, or categories in the database which prevents this action!"
)
ASSISTANT_ALREADY_RAN_MESSAGE: str = "The DataGerry Assistant has already run on this installation!"
ASSISTANT_RESIDUE_MESSAGE: str = (
    "The initial Profiles could not be created, and their undo left these behind: {residue}"
)
ASSISTANT_READ_FAILED_MESSAGE: str = "Failed to check whether the DataGerry Assistant can run!"
