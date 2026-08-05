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
Helper methods shared by the CmdbExtendableOption REST routes
"""
from typing import Any

from cmdb.manager import ExtendableOptionsManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.user_model import CmdbUser
from cmdb.models.extendable_option_model import OptionType

from cmdb.interface.rest_api.routes.framework_routes.cmdb_extendable_options.extendable_options_constants import (
    ExtendableOptionKey,
    ExtendableOptionUsageField,
)
# -------------------------------------------------------------------------------------------------------------------- #


def option_value_exists(
        extendable_options_manager: ExtendableOptionsManager,
        value: str,
        option_type: str,
        exclude_id: int | None = None) -> bool:
    """
    Checks whether a CmdbExtendableOption with the given value already exists for the given OptionType

    Used as the uniqueness guard shared by the create and update routes. On update, ``exclude_id`` is
    the public_id of the option being edited so it does not conflict with itself (a save that keeps the
    value unchanged is allowed).

    Args:
        extendable_options_manager (ExtendableOptionsManager): Manager used to query options
        value (str): The option value to check for
        option_type (str): The OptionType the value belongs to
        exclude_id (int | None): A public_id to exclude from the match (the option being updated).
                                 Defaults to None

    Returns:
        bool: True if a (different) option with the same value + option_type exists, otherwise False
    """
    criteria: dict[str, Any] = {
        ExtendableOptionKey.VALUE: value,
        ExtendableOptionKey.OPTION_TYPE: option_type,
    }

    if exclude_id is not None:
        criteria[ExtendableOptionKey.PUBLIC_ID] = {'$ne': exclude_id}

    return extendable_options_manager.get_one_by(criteria) is not None


def is_extendable_option_used(extendable_option: dict[str, Any], request_user: CmdbUser) -> bool:
    """
    Checks whether a CmdbExtendableOption is still referenced by another resource

    Resolves which collection(s) can reference the option from its ``option_type`` and counts the
    referencing documents (no documents are materialised). Used as the pre-delete guard so an option
    still in use cannot be removed

    Args:
        extendable_option (dict[str, Any]): The CmdbExtendableOption document to check
        request_user (CmdbUser): User requesting the check (manager scoping)

    Returns:
        bool: True if at least one resource references the option, False otherwise
    """
    option_type: str | None = extendable_option.get(ExtendableOptionKey.OPTION_TYPE)
    public_id: int | None = extendable_option.get(ExtendableOptionKey.PUBLIC_ID)

    if option_type == OptionType.THREAT_VULNERABILITY:
        # A THREAT_VULNERABILITY option is referenced by threats AND vulnerabilities (both via 'source')
        threat_manager = ManagerProvider.get_manager(ManagerType.THREAT, request_user)
        vulnerability_manager = ManagerProvider.get_manager(ManagerType.VULNERABILITY, request_user)

        return (
            threat_manager.count_documents({ExtendableOptionUsageField.SOURCE: public_id}) > 0
            or vulnerability_manager.count_documents({ExtendableOptionUsageField.SOURCE: public_id}) > 0
        )

    if option_type == OptionType.OBJECT_GROUP:
        object_groups_manager = ManagerProvider.get_manager(ManagerType.OBJECT_GROUP, request_user)

        return object_groups_manager.count_documents({ExtendableOptionUsageField.CATEGORIES: public_id}) > 0

    if option_type == OptionType.CONTROL_MEASURE:
        control_measure_manager = ManagerProvider.get_manager(ManagerType.CONTROL_MEASURE, request_user)

        return control_measure_manager.count_documents({ExtendableOptionUsageField.SOURCE: public_id}) > 0

    if option_type == OptionType.IMPLEMENTATION_STATE:
        control_measure_manager = ManagerProvider.get_manager(ManagerType.CONTROL_MEASURE, request_user)
        risk_assessment_manager = ManagerProvider.get_manager(ManagerType.RISK_ASSESSMENT, request_user)
        c_m_assignment_manager = ManagerProvider.get_manager(ManagerType.CONTROL_MEASURE_ASSIGNMENT, request_user)

        return (
            control_measure_manager.count_documents(
                {ExtendableOptionUsageField.IMPLEMENTATION_STATE: public_id}
            ) > 0
            or risk_assessment_manager.count_documents(
                {ExtendableOptionUsageField.IMPLEMENTATION_STATUS: public_id}
            ) > 0
            or c_m_assignment_manager.count_documents(
                {ExtendableOptionUsageField.IMPLEMENTATION_STATUS: public_id}
            ) > 0
        )

    if option_type == OptionType.RISK:
        risk_manager = ManagerProvider.get_manager(ManagerType.RISK, request_user)

        return risk_manager.count_documents({ExtendableOptionUsageField.CATEGORY_ID: public_id}) > 0

    # Unrecognised option_type -> treat as not used
    return False
