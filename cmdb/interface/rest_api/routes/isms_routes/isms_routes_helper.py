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
from cmdb.interface.rest_api.routes import routes_helper
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import (
    BULK_ITEM_INVALID_ID_MSG,
    BULK_ITEM_MISSING_ID_MSG,
    BULK_ITEM_NOT_FOUND_MSG,
    BULK_ITEM_UPDATE_FAILED_MSG,
    BulkItemResultKey,
    BulkItemStatus,
    ISMS_BULK_DELETE_DELETED_KEY,
    ISMS_CAP_REACHED_MSG,
    ISMS_BULK_DELETE_IN_USE_KEY,
    IsmsEntityLabel,
    IsmsManagerErrorMessage,
    REQUIRED_RISK_ASSESSMENT_FIELDS,
    UNKNOWN_CONTROL_MEASURES_MSG,
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


class _KeepUnfilledPlaceholders(dict):
    """A format mapping that answers an unknown placeholder with the placeholder itself"""

    def __missing__(self, key: str) -> str:
        """
        Keeps a placeholder this mapping does not fill, for a later formatting pass

        Args:
            key (str): The placeholder's name

        Returns:
            str: The placeholder as written, ``{key}``
        """
        return f'{{{key}}}'


def manager_error_message(label: IsmsEntityLabel, template: IsmsManagerErrorMessage) -> str:
    """
    Fills an ISMS manager-error template with an entity's labels

    Only ``{entity}`` and ``{entities}`` are filled. Every other placeholder - ``{public_id}`` - stays in
    the result, for ``handle_manager_errors`` to fill from the route's argument

    Args:
        label (IsmsEntityLabel): The entity the route serves
        template (IsmsManagerErrorMessage): The operation's message template

    Returns:
        str: The template with the entity's labels filled in
    """
    return template.value.format_map(
        _KeepUnfilledPlaceholders(entity=label.singular, entities=label.plural)
    )


def manager_error_messages(
        label: IsmsEntityLabel,
        templates: dict[type[Exception], IsmsManagerErrorMessage]) -> dict[type[Exception], str]:
    """
    Builds a route's ``handle_manager_errors`` table from its entity and one template per error class

    Args:
        label (IsmsEntityLabel): The entity the route serves
        templates (dict[type[Exception], IsmsManagerErrorMessage]): Error class -> operation template

    Returns:
        dict[type[Exception], str]: Error class -> message, ``{public_id}`` still unfilled
    """
    return {
        error_class: manager_error_message(label, template)
        for error_class, template in templates.items()
    }


def require_created_item(item: dict[str, Any] | None, label: IsmsEntityLabel) -> dict[str, Any]:
    """
    Answers the item an ISMS insert route just created, refusing with a 500 when it cannot be read back

    ``routes_helper.require_created_item`` with the entity's own message
    (``IsmsManagerErrorMessage.GET_CREATED``)

    Args:
        item (dict[str, Any] | None): The read-back of the created item
        label (IsmsEntityLabel): The entity the route serves

    Raises:
        werkzeug.exceptions.InternalServerError: Aborts with 500 when the item was not found

    Returns:
        dict[str, Any]: The created item
    """
    return routes_helper.require_created_item(
        item, manager_error_message(label, IsmsManagerErrorMessage.GET_CREATED),
    )


def abort_if_isms_cap_reached(manager: GenericManager, cap: int, entity_label: str) -> None:
    """
    Refuses the create of an ISMS entry once its collection already holds ``cap`` entries

    The bounded ISMS scales (Likelihoods, Impacts) and the RiskClasses are kept small so the risk matrix
    stays readable. Reaching the cap is a business rule, not an authorisation decision - the caller holds
    the right, the collection is simply full - so the refusal is a 400

    Args:
        manager (GenericManager): Manager of the collection the create would add to
        cap (int): Maximum number of entries the collection may hold
        entity_label (str): Plural entity name used in the message (e.g. "Likelihoods")

    Raises:
        werkzeug.exceptions.BadRequest: Aborts with 400 when the collection already holds ``cap`` entries
    """
    if manager.count_documents() >= cap:
        abort(400, ISMS_CAP_REACHED_MSG.format(cap=cap, entity_label=entity_label))


def _is_item_public_id(value: Any) -> bool:
    """
    Answers whether a bulk item's public_id can address a stored document

    Args:
        value (Any): The item's ``public_id`` as sent

    Returns:
        bool: True for an integer that is not a bool
    """
    return isinstance(value, int) and not isinstance(value, bool)


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

    Each item is addressed by its own ``public_id``, which must be an integer. A bool is refused too:
    ``True == 1`` in Python, so it would pass the existence check against id 1, while MongoDB does not
    match a boolean against the stored integer and the update would write nothing yet report success.

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

    id_key: str = BulkItemResultKey.PUBLIC_ID.value

    # Resolve which requested ids exist in one batched query instead of a per-item existence read
    requested_ids: list[int] = [
        item[id_key] for item in data
        if isinstance(item, dict) and _is_item_public_id(item.get(id_key))
    ]
    existing_ids: set[int] = {
        doc[id_key] for doc in manager.find_all(criteria={id_key: {"$in": requested_ids}})
    } if requested_ids else set()

    results: list[dict[str, Any]] = []

    for item in data:
        public_id = item.get(id_key) if isinstance(item, dict) else None

        if public_id is None:
            results.append(_bulk_item_failure(None, BULK_ITEM_MISSING_ID_MSG))
            continue

        if not _is_item_public_id(public_id):
            results.append(_bulk_item_failure(public_id, BULK_ITEM_INVALID_ID_MSG))
            continue

        if public_id not in existing_ids:
            results.append(_bulk_item_failure(
                public_id, BULK_ITEM_NOT_FOUND_MSG.format(item_label=item_label, public_id=public_id),
            ))
            continue

        try:
            manager.update_item(public_id, model.from_data(item))
            results.append({id_key: public_id, BulkItemResultKey.STATUS.value: BulkItemStatus.SUCCESS.value})
        except Exception as err:
            LOGGER.error("[%s] Failed to update %s ID %s: %s. Type: %s",
                         log_tag, item_label, public_id, err, type(err))
            results.append(_bulk_item_failure(
                public_id, BULK_ITEM_UPDATE_FAILED_MSG.format(item_label=item_label, public_id=public_id),
            ))

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


def get_missing_risk_assessment_fields(data: dict[str, Any]) -> list[str]:
    """
    Reports which of an IsmsRiskAssessment's mandatory fields the payload does not supply

    A field counts as missing when its key is absent, its value is None, or its value is an empty
    string / list / dict - a date sent as ``{}`` is as unusable as no date at all. Every offending
    field is collected instead of stopping at the first, so one response can name them all

    Args:
        data (dict[str, Any]): The IsmsRiskAssessment payload to check

    Returns:
        list[str]: The missing field names in the order of REQUIRED_RISK_ASSESSMENT_FIELDS, empty when
            the payload is complete
    """
    missing_fields: list[str] = []

    for field_name in REQUIRED_RISK_ASSESSMENT_FIELDS:
        value: Any = data.get(field_name)

        if value is None or value == '' or value == [] or value == {}:
            missing_fields.append(field_name)

    return missing_fields


def guard_required_risk_assessment_fields(data: dict[str, Any]) -> None:
    """
    Refuses an IsmsRiskAssessment write whose mandatory fields are not all supplied

    Runs on every write path (create, update and duplicate) before anything is stored, so a partially
    filled assessment can never reach the database. The message lists every missing field at once, so
    the caller can highlight all of them in one go rather than discovering them one request at a time.
    The later lifecycle stages (risk treatment, effectiveness audit) stay optional by design

    Args:
        data (dict[str, Any]): The IsmsRiskAssessment payload to check

    Raises:
        werkzeug.exceptions.BadRequest: Aborts with 400 naming every missing field
    """
    missing_fields: list[str] = get_missing_risk_assessment_fields(data)

    if missing_fields:
        abort(400, f"The RiskAssessment is missing required field(s): {', '.join(missing_fields)}!")


def abort_on_unknown_control_measures(cm_assignment_manager: Any, assignments: list[dict[str, Any]]) -> None:
    """
    Refuses a write whose ControlMeasureAssignments name an IsmsControlMeasure that does not exist

    Args:
        cm_assignment_manager (Any): The ControlMeasureAssignmentManager, anything with its
            ``get_missing_control_measure_ids``
        assignments (list[dict[str, Any]]): The assignment payloads; nothing is queried when none names a measure

    Raises:
        werkzeug.exceptions.BadRequest: Aborts with 400 naming the unknown measure ids, sorted
    """
    missing_control_measures: set[int] = cm_assignment_manager.get_missing_control_measure_ids(assignments)

    if missing_control_measures:
        abort(400, UNKNOWN_CONTROL_MEASURES_MSG.format(unknown=sorted(missing_control_measures)))


def _bulk_item_failure(public_id: Any, message: str) -> dict[str, Any]:
    """
    Builds the per-item entry of a bulk update that did not go through

    Args:
        public_id (Any): The item's id as sent, or None when it carried none
        message (str): Why the item failed

    Returns:
        dict[str, Any]: `{public_id, status: 'failed', message}`
    """
    return {
        BulkItemResultKey.PUBLIC_ID.value: public_id,
        BulkItemResultKey.STATUS.value: BulkItemStatus.FAILED.value,
        BulkItemResultKey.MESSAGE.value: message,
    }
