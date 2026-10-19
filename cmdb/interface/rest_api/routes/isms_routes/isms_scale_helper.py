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
The writes of the two ISMS scales, IsmsImpact and IsmsLikelihood

Both scales hold one rule the routes cannot enforce alone: a calculation_basis is used by one entry of the
scale only. The route's read (``*_calculation_basis_exists``) answers the ordinary case; the unique index on
calculation_basis is what holds under concurrency, and its refusal reaches the route as the manager's write
error - which these helpers answer with the same 400 (``abort_if_duplicate``). Everything else the write raised
is re-raised for the route's error table.

**Every scale write is all-or-nothing.** A create, update or delete of an entry is followed by writes elsewhere -
the RiskAssessments using a changed calculation_basis, every ImpactCategory's description of an Impact, and the
RiskMatrix rebuilt from the scales - with no transaction around them. The route runs them all in one
``undone_on_failure`` ledger (``scale_write_ledger``) and every helper here records its write in it: a failure
anywhere takes back what was already written, and an undo that cannot finish answers the 500 naming what is left
"""
from contextlib import AbstractContextManager
from typing import Any

from cmdb.framework.write_ledger import WriteLedger
from cmdb.manager.generic_manager import GenericManager

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.isms_model.isms_impact_constants import ImpactKey
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import (
    CALCULATION_BASIS_NOT_A_NUMBER_MSG,
    CALCULATION_BASIS_TAKEN_MSG,
    SCALE_WRITE_UNDO_INCOMPLETE_MSG,
    IsmsEntityLabel,
    IsmsWriteAction,
)
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_helper import coerce_isms_number
from cmdb.interface.rest_api.routes.routes_helper import (
    abort_if_duplicate,
    undone_on_failure,
    update_item_from_payload,
)
# -------------------------------------------------------------------------------------------------------------------- #

# The key of a scale entry's weight - IsmsLikelihood's documents name it alike (LikelihoodKey)
CALCULATION_BASIS_KEY: str = ImpactKey.CALCULATION_BASIS.value


def coerce_calculation_basis(data: dict[str, Any]) -> None:
    """
    Normalises a scale entry's calculation_basis to a 2-decimal float in place

    Args:
        data (dict[str, Any]): The request body of an IsmsImpact or IsmsLikelihood write

    Raises:
        HTTPException: 400 when the calculation_basis is missing or cannot be converted
    """
    coerce_isms_number(data, CALCULATION_BASIS_KEY, CALCULATION_BASIS_NOT_A_NUMBER_MSG)


def scale_write_ledger(action: IsmsWriteAction, label: IsmsEntityLabel) -> AbstractContextManager[WriteLedger]:
    """
    The ledger a scale or category write route runs all of its writes in, undone together when one fails

    Args:
        action (IsmsWriteAction): What the route does, as the undo's 500 names it
        label (IsmsEntityLabel): The entity written

    Returns:
        AbstractContextManager[WriteLedger]: ``undone_on_failure`` with the route's residue message
    """
    return undone_on_failure(SCALE_WRITE_UNDO_INCOMPLETE_MSG.format(action=action.value, entity=label.singular))


def insert_scale_entry(
        manager: GenericManager,
        data: dict[str, Any],
        label: IsmsEntityLabel,
        ledger: WriteLedger) -> int:
    """
    Inserts a scale entry and records it in the ledger, answering a calculation_basis the unique index refused
    with the route's 400

    Args:
        manager (GenericManager): The scale's manager
        data (dict[str, Any]): The validated, coerced entry
        label (IsmsEntityLabel): The scale's entity, for the refusal
        ledger (WriteLedger): The route's ledger

    Raises:
        HTTPException: 400 when another entry holds the calculation_basis
        Exception: The manager's 'insert' error for any other failure of the write

    Returns:
        int: The public_id of the new entry
    """
    insert_error: type[Exception] = manager.exceptions['insert']

    try:
        public_id: int = manager.insert_item(data)
    except insert_error as err:
        abort_if_duplicate(err, CALCULATION_BASIS_TAKEN_MSG.format(entity=label.singular))

    ledger.inserted(manager, public_id)

    return public_id


def update_scale_entry(
        manager: GenericManager,
        model_class: type[CmdbDAO],
        public_id: int,
        data: dict[str, Any],
        basis_changed: bool,
        label: IsmsEntityLabel,
        ledger: WriteLedger) -> dict[str, Any]:
    """
    Updates a scale entry - with the RiskAssessments using it when its calculation_basis changed - in the ledger

    A changed calculation_basis runs ``update_with_follow_up``, which records both of its writes; an unchanged one
    is a plain update, recorded with the entry's stored document

    Args:
        manager (GenericManager): The scale's manager (ImpactManager or LikelihoodManager)
        model_class (type[CmdbDAO]): The scale's model
        public_id (int): The entry's public_id
        data (dict[str, Any]): The validated, coerced, identity-pinned entry
        basis_changed (bool): Whether the calculation_basis differs from the stored one
        label (IsmsEntityLabel): The scale's entity, for the refusal
        ledger (WriteLedger): The route's ledger

    Raises:
        HTTPException: 400 when another entry holds the calculation_basis
        Exception: The manager's 'get' or 'update' error for any other failure

    Returns:
        dict[str, Any]: The entry as stored
    """
    update_error: type[Exception] = manager.exceptions['update']

    try:
        if basis_changed:
            return manager.update_with_follow_up(public_id, data, ledger)

        prior: dict[str, Any] | None = manager.get_item(public_id, as_dict=True)

        if prior is not None:
            ledger.updated(manager, public_id, prior)

        return update_item_from_payload(manager, public_id, model_class, data)
    except update_error as err:
        abort_if_duplicate(err, CALCULATION_BASIS_TAKEN_MSG.format(entity=label.singular))
