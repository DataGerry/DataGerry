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
Shared helper logic for the ISMS REST routes
"""
from logging import Logger, getLogger
from typing import Any, Type

from flask import abort

from cmdb.manager.generic_manager import GenericManager

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import (
    ISMS_BULK_DELETE_DELETED_KEY,
    ISMS_BULK_DELETE_IN_USE_KEY,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)


def get_item_or_404(
        manager: GenericManager,
        public_id: int,
        not_found_message: str,
        as_dict: bool = True) -> dict[str, Any] | CmdbDAO:
    """
    Fetches an ISMS item by public_id, aborting with HTTP 404 when it does not exist.

    Collapses the repeated "get the item, and abort 404 if it is missing" preamble shared by the
    ISMS get-single, update and delete routes.

    Args:
        manager (GenericManager): The manager to read the item from
        public_id (int): public_id of the item to fetch
        not_found_message (str): Message for the 404 response when the item is missing
        as_dict (bool): If True return the raw document, otherwise a model instance. Defaults to True

    Raises:
        werkzeug.exceptions.NotFound: Aborts with 404 when no item matches public_id

    Returns:
        dict[str, Any] | CmdbDAO: The existing item as a dict (as_dict=True) or model instance
    """
    item = manager.get_item(public_id, as_dict=as_dict)

    if not item:
        abort(404, not_found_message)

    return item


def update_multiple_items(
        manager: GenericManager,
        model: Type[CmdbDAO],
        data: Any,
        item_label: str,
        log_tag: str) -> list[dict[str, Any]]:
    """
    Updates a list of ISMS items, reporting an independent success/failure result per item.

    Shared by the ISMS ``PUT``/``PATCH`` ``/multiple`` bulk-update routes. The set of existing
    public_ids is resolved in a single batched query rather than one existence read per item, then
    each item is updated on its own so a single failure does not abort the rest.

    Args:
        manager (GenericManager): Manager whose items are updated
        model (Type[CmdbDAO]): Model class used to deserialise each item via ``from_data``
        data (Any): The parsed request body; must be a list of item dicts
        item_label (str): Human-readable entity name used in the result messages (e.g. "RiskClass")
        log_tag (str): Route identifier used as the log prefix

    Raises:
        werkzeug.exceptions.BadRequest: Aborts with 400 when the body is not a list

    Returns:
        list[dict[str, Any]]: Per-item results, each {"public_id", "status", and "message" on failure}
    """
    if not isinstance(data, list):
        abort(400, f"The request body must be a list of {item_label}s!")

    # Resolve which requested ids exist in one batched query instead of a per-item existence read
    requested_ids: list[int] = [
        item["public_id"] for item in data
        if isinstance(item, dict) and item.get("public_id") is not None
    ]
    existing_ids: set[int] = {
        doc["public_id"] for doc in manager.find_all(criteria={"public_id": {"$in": requested_ids}})
    } if requested_ids else set()

    results: list[dict[str, Any]] = []

    for item in data:
        public_id = item.get("public_id") if isinstance(item, dict) else None

        if public_id is None:
            results.append({"public_id": None, "status": "failed", "message": "Missing public_id"})
            continue

        if public_id not in existing_ids:
            results.append({
                "public_id": public_id,
                "status": "failed",
                "message": f"{item_label} ID:{public_id} not found",
            })
            continue

        try:
            manager.update_item(public_id, model.from_data(item))
            results.append({"public_id": public_id, "status": "success"})
        except Exception as err:
            LOGGER.error("[%s] Failed to update %s ID %s: %s. Type: %s",
                         log_tag, item_label, public_id, err, type(err))
            results.append({
                "public_id": public_id,
                "status": "failed",
                "message": f"Failed to update {item_label} ID: {public_id}",
            })

    return results


def bulk_delete_reporting_in_use(
        manager: GenericManager,
        requested_ids: list[int],
        in_use_ids: set[int]) -> dict[str, list[int]]:
    """
    Deletes the unused subset of requested ISMS items and reports which were skipped as in-use

    Shared by the ISMS bulk-delete routes whose single-delete refuses a still-referenced item
    (IsmsControlMeasure, IsmsVulnerability). The caller resolves which requested ids are still in
    use in one batched query per entity; this deletes every OTHER requested id and reports both
    lists. It relies on ``delete_item`` returning True only when a document was actually removed, so
    a non-existent id never lands in the deleted list - no separate existence query is needed

    Args:
        manager (GenericManager): The manager whose items are deleted (delete_item wraps its own
            delete error)
        requested_ids (list[int]): The requested item public_ids
        in_use_ids (set[int]): Subset of requested_ids still referenced elsewhere; never deleted

    Returns:
        dict[str, list[int]]: {'successfully': [deleted ids], 'in_use': [skipped in-use ids]}, both
            sorted ascending
    """
    deleted_ids: list[int] = [
        public_id for public_id in requested_ids
        if public_id not in in_use_ids and manager.delete_item(public_id)
    ]

    return {
        ISMS_BULK_DELETE_DELETED_KEY: sorted(deleted_ids),
        ISMS_BULK_DELETE_IN_USE_KEY: sorted(in_use_ids),
    }
