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
Helper functions for the DataGerry Assistant (special) REST routes
"""
from cmdb.manager import CategoriesManager, ObjectsManager
from cmdb.manager.types_manager import TypesManager

from cmdb.models.user_model import CmdbUser
from cmdb.framework.datagerry_assistant.profile_name import ProfileName
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.interface.rest_api.routes.cmdb_license.license_guard import feature_locked
# -------------------------------------------------------------------------------------------------------------------- #

# The license feature a profile needs before the assistant may seed it. A profile absent from this map
# is always available. RACK is mapped to IPAM as an INTERIM decision - the Rack View is not part of
# IPAM and is expected to get a LicenseFeature of its own (see SpecialType.get_license_gated_types)
PROFILE_LICENSE_FEATURES: dict[str, LicenseFeature] = {
    ProfileName.RACK.value: LicenseFeature.IPAM,
}


def drop_locked_profiles(profiles: list[str], request_user: CmdbUser) -> list[str]:
    """
    Removes the requested profiles whose license feature is not unlocked

    The assistant writes its CmdbTypes straight through the managers, so it never passes the route
    guards that gate a licensed feature. Filtering here keeps the license decision in the interface
    layer (the assistant itself stays licensing-agnostic) and keeps the seeding of the remaining
    profiles working: a locked profile is skipped rather than failing the whole run, which matters
    because the assistant only ever runs once, against an empty database.

    A skipped profile leaves its type slots empty, exactly as if the user had not selected it. On a
    licensed instance, and in cloud / local mode, nothing is filtered

    Args:
        profiles (list[str]): The ProfileName values selected in the assistant
        request_user (CmdbUser): The user performing the request

    Returns:
        list[str]: The selected profiles that may be seeded, in the order they were given
    """
    return [
        profile for profile in profiles
        if profile not in PROFILE_LICENSE_FEATURES
        or not feature_locked(PROFILE_LICENSE_FEATURES[profile], request_user)
    ]


def has_framework_data(
        categories_manager: CategoriesManager,
        types_manager: TypesManager,
        objects_manager: ObjectsManager) -> bool:
    """
    Checks whether any framework data (categories, types, or objects) already exists

    The collections are counted in order and the check returns as soon as one of them is non-empty,
    so a populated database is detected without counting every collection. Used by the DataGerry
    Assistant to decide whether to offer the intro and to guard the initial profile creation.

    Args:
        categories_manager (CategoriesManager): Manager used to count CmdbCategories
        types_manager (TypesManager): Manager used to count CmdbTypes
        objects_manager (ObjectsManager): Manager used to count CmdbObjects

    Returns:
        bool: True if at least one category, type, or object exists, otherwise False
    """
    if categories_manager.count_documents() > 0:
        return True

    if types_manager.count_documents() > 0:
        return True

    return objects_manager.count_documents() > 0
