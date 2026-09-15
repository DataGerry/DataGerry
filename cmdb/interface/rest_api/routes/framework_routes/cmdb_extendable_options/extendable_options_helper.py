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
from cmdb.models.extendable_option_model import ExtendableOptionKey

from cmdb.framework.extendable_options import is_option_referenced
# -------------------------------------------------------------------------------------------------------------------- #


def option_value_exists(
        extendable_options_manager: ExtendableOptionsManager,
        value: str,
        option_type: str,
        exclude_id: int | None = None) -> bool:
    """
    Checks whether a CmdbExtendableOption with the given value already exists for the given OptionType

    The uniqueness guard shared by the create and update routes, and the one that produces a readable
    400. It is not the guarantee: being a read followed by a write it cannot stop two concurrent
    requests, which is what the unique (option_type, value) index on the collection is for. On update,
    ``exclude_id`` is the public_id of the option being edited so it does not conflict with itself (a
    save that keeps the value unchanged is allowed).

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

    Which collections can reference the option is resolved from its ``option_type`` through the
    shared reference map in ``cmdb.framework.extendable_options`` - the same map the de-duplication
    updater re-points references with, so the two can never disagree about where an option is used.
    No documents are materialised. Used as the pre-delete guard so an option still in use cannot be
    removed

    Args:
        extendable_option (dict[str, Any]): The CmdbExtendableOption document to check
        request_user (CmdbUser): User requesting the check (manager scoping)

    Returns:
        bool: True if at least one resource references the option, False otherwise
    """
    extendable_options_manager: ExtendableOptionsManager = ManagerProvider.get_manager(
                                                                ManagerType.EXTENDABLE_OPTIONS,
                                                                request_user
                                                            )

    return is_option_referenced(
        extendable_options_manager.dbm,
        extendable_options_manager.db_name,
        extendable_option.get(ExtendableOptionKey.OPTION_TYPE),
        extendable_option.get(ExtendableOptionKey.PUBLIC_ID),
    )
