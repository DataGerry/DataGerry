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
from flask import current_app, request

from cmdb.manager import OcInvokerManager

from cmdb.models.user_model import CmdbUser

from cmdb.open_celium.oc_constants import OC_FLAG_DISABLED_VALUE, OC_OPS_INCLUDED_PARAM
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
    return OcInvokerManager(current_app.database_manager, request_user.database)


def read_ops_included_flag() -> bool:
    """
    Reads the `opsIncluded` flag of the all-invokers route

    Operations are **included by default** - an invoker without them is the cheaper read, not the
    expected one - and **only the literal `false` turns them off** (case-insensitively). Deliberately
    not `request.args.get(..., type=bool)`, which would answer True for the string `'false'`, and
    deliberately not a list of accepted spellings: `0`, `no`, `off` and an EMPTY value all mean
    "include" today, and whether they should is discussion-backlog #223. The rule lives here so that
    decision has one place to land

    Returns:
        bool: True when the operations should be requested with the invokers
    """
    requested = request.args.get(OC_OPS_INCLUDED_PARAM, default='')

    return requested.lower() != OC_FLAG_DISABLED_VALUE
