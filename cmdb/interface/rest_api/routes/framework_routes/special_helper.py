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
from cmdb.framework.datagerry_assistant.profile_assistant import special_types_created_by
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.interface.rest_api.routes.cmdb_license.license_guard import feature_locked
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_helper import (
    special_type_license_feature,
)
# -------------------------------------------------------------------------------------------------------------------- #


def profile_license_feature(profile: str) -> LicenseFeature | None:
    """
    Reports which LicenseFeature a profile needs before the assistant may seed it

    **Derived, not listed.** The answer is read off what the profile actually creates
    (`special_types_created_by`) and mapped through the same `special_type_license_feature` the type
    routes use, so the assistant and `POST /types/` cannot disagree about whether a SpecialType is
    licensed.

    This replaced a hand-maintained profile -> feature map, which had exactly one entry - the RACK
    profile, which is gated behind IPAM only as an interim borrowing - while the IPAM profile itself,
    which creates the SpecialTypes the licence actually owns, was missing from it. A map keyed by
    PROFILE cannot stay in step with a guard keyed by SPECIAL TYPE: a profile is a bundle, and what it
    needs depends on what it builds.

    Args:
        profile (str): A ProfileName value, as selected in the assistant

    Returns:
        LicenseFeature | None: The feature the profile requires, or None when it needs none
    """
    return special_type_license_feature(*special_types_created_by(profile))


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
        if not _is_locked(profile, request_user)
    ]


def _is_locked(profile: str, request_user: CmdbUser) -> bool:
    """
    Whether one profile may not be seeded right now

    Args:
        profile (str): A ProfileName value
        request_user (CmdbUser): The user performing the request

    Returns:
        bool: True when the profile needs a feature the active license does not unlock
    """
    required_feature: LicenseFeature | None = profile_license_feature(profile)

    return required_feature is not None and feature_locked(required_feature, request_user)


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
