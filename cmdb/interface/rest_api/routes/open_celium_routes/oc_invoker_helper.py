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
Helper functions for the OpenCelium invoker REST routes

An invoker is the OpenCelium plugin that knows how to talk to a given system, and DataGerry itself is
registered as one - which is what a business template is filtered by (see
`oc_template_helper.datagerry_invoker_name`). The routes only read them.

Two jobs live here: the manager construction the three routes repeated, and the one query flag the
list route accepts - kept out of the route so the flag's rule is stated once and testable without a
request context.
"""
from flask import current_app

from cmdb.manager.manager_provider_model import ManagerProvider
from cmdb.manager import OcInvokerManager

from cmdb.models.user_model import CmdbUser

from cmdb.open_celium.oc_constants import OC_OPS_INCLUDED_PARAM
from cmdb.interface.rest_api.routes.routes_helper import read_boolean_query_param
# -------------------------------------------------------------------------------------------------------------------- #


def build_invoker_manager(request_user: CmdbUser) -> OcInvokerManager:
    """
    Builds the OcInvokerManager for the requesting user

    Every invoker route needs the same two arguments - the process-wide database manager and the
    caller's database, which is what selects the OpenCelium installation to read from - so the
    construction lives here instead of three times in the route module

    Args:
        request_user (CmdbUser): The user making the request; its database scopes the manager

    Returns:
        OcInvokerManager: The manager to talk to OpenCelium with
    """
    return OcInvokerManager(current_app.database_manager, ManagerProvider.tenant_database(request_user))


def read_ops_included_flag() -> bool:
    """
    Reads the `opsIncluded` flag of the all-invokers route

    Operations are **included by default** - an invoker without them is the cheaper read, not the
    expected one. The flag follows the API's one rule for boolean query parameters
    (``routes_helper.read_boolean_query_param``): ``true`` / ``false`` in any casing, and anything else -
    ``0``, ``no``, ``off``, an empty value - is refused rather than guessed at

    Raises:
        HTTPException: 400 when the flag is present but neither ``true`` nor ``false``

    Returns:
        bool: True when the operations should be requested with the invokers
    """
    return read_boolean_query_param(OC_OPS_INCLUDED_PARAM, default=True)
