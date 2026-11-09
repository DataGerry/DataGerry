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
from collections import Counter
from logging import Logger, getLogger
from typing import Any, Callable, Iterable, Type

from cerberus import Validator
from flask import abort
from pymongo import UpdateOne

from cmdb.manager.extendable_options_manager import ExtendableOptionsManager
from cmdb.manager.generic_manager import GenericManager
from cmdb.manager.isms_manager.isms_manager_helper import delete_unreferenced_batch
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.database.database_constants import PUBLIC_ID_FIELD
from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.isms_model.isms_risk_assessment_constants import RiskAssessmentKey
from cmdb.models.object_group_model.object_reference_type_enum import ObjectReferenceType
from cmdb.models.user_model import CmdbUser
from cmdb.models.isms_model import IsmsControlMeasureAssignment
from cmdb.models.isms_model.isms_control_measure_assignment_constants import ControlMeasureAssignmentKey
from cmdb.errors.manager import BaseManagerGetError, BaseManagerInitError
from cmdb.errors.manager.extendable_options_manager import ExtendableOptionsManagerGetError
from cmdb.interface.blueprints.schema_error_format import ERRORS_SEPARATOR, flatten_schema_errors
from cmdb.interface.rest_api.routes import routes_helper
from cmdb.security.acl.builder import resolve_denied_type_ids
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import (
    ASSESSED_OBJECT_LOOKUP_FAILED_MSG,
    BULK_ITEM_INVALID_ID_REASON,
    BULK_ITEM_NOT_AN_OBJECT_REASON,
    BULK_ITEM_REASON_SEPARATOR,
    BULK_ITEM_SCHEMA_REASON,
    BULK_DELETE_TOO_MANY_ITEMS_MSG,
    BULK_UPDATE_DUPLICATE_IDS_MSG,
    BULK_UPDATE_INVALID_ITEMS_MSG,
    BULK_UPDATE_NOT_A_LIST_MSG,
    BULK_UPDATE_NOT_FOUND_MSG,
    BULK_UPDATE_TOO_MANY_ITEMS_MSG,
    BULK_UPDATE_UNDO_INCOMPLETE_MSG,
    BulkItemResultKey,
    CONTROL_MEASURE_LOOKUP_FAILED_MSG,
    BulkItemStatus,
    IMPLEMENTATION_STATE_OPTION,
    OPTION_LOOKUP_FAILED_MSG,
    IsmsOptionField,
    ISMS_BULK_DELETE_DELETED_KEY,
    ISMS_CAP_REACHED_MSG,
    ISMS_BULK_DELETE_IN_USE_KEY,
    IsmsEntityLabel,
    IsmsManagerErrorMessage,
    ISMS_NUMBER_DECIMALS,
    MAX_ISMS_BULK_DELETE_ITEMS,
    REQUIRED_RISK_ASSESSMENT_FIELDS,
    UNKNOWN_ASSESSED_OBJECT_GROUPS_MSG,
    UNKNOWN_ASSESSED_OBJECTS_MSG,
    UNKNOWN_CONTROL_MEASURES_MSG,
    UNKNOWN_OPTIONS_MSG,
    UNKNOWN_RISKS_MSG,
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

    A failed count is a failed database call, so it is a 400 as well - answered here, with its own message,
    because the count raises the base ``BaseManagerGetError``: mapping that class in a create route's error table
    would also catch any other step of the route that raises it, and give that step the count's message

    Args:
        manager (GenericManager): Manager of the collection the create would add to
        cap (int): Maximum number of entries the collection may hold
        entity_label (str): Plural entity name used in the messages (e.g. "Likelihoods")

    Raises:
        werkzeug.exceptions.BadRequest: Aborts with 400 when the collection already holds ``cap`` entries, or when
            counting them failed (``IsmsManagerErrorMessage.CAP_CHECK``)
    """
    try:
        entry_count: int = manager.count_documents()
    except BaseManagerGetError as err:
        LOGGER.error("[abort_if_isms_cap_reached] %s: %s", type(err).__name__, err)
        abort(400, IsmsManagerErrorMessage.CAP_CHECK.value.format(entities=entity_label))

    if entry_count >= cap:
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
        schema: dict[str, Any],
        label: IsmsEntityLabel,
        max_items: int,
        check_documents: Callable[[list[tuple[int, dict[str, Any]]]], None] | None = None) -> list[dict[str, Any]]:
    """
    Updates a list of ISMS items all-or-nothing: every item is judged before any is written

    Shared by the ISMS ``PUT``/``PATCH`` ``/multiple`` bulk-update routes. Each item is a whole document
    addressed by its own integer ``public_id`` and judged by the same write schema as the single update.
    The request is refused with one 400 naming every reason when the body is not a list, carries more
    than ``max_items`` items, any item is invalid, an id is sent twice or an id does not exist. Only then
    are the items written, in one ordered bulk write whose part-way failure is undone

    Args:
        manager (GenericManager): Manager whose items are updated
        model (Type[CmdbDAO]): Model class each item is built and serialised with
        data (Any): The parsed request body
        schema (dict[str, Any]): The item write schema, without ``public_id``
        label (IsmsEntityLabel): The entity, for the messages
        max_items (int): The most items one request may carry
        check_documents (Callable[[list[tuple[int, dict[str, Any]]]], None] | None): The entity's own rules over the
            validated ``(public_id, document)`` items, run after every other check and before the write - it aborts to
            refuse. Defaults to None (no further rule)

    Raises:
        werkzeug.exceptions.BadRequest: Aborts with 400 for any of the refusals above

    Returns:
        list[dict[str, Any]]: One ``{public_id, status: 'success'}`` entry per item, in request order
    """
    items: list[Any] = read_bulk_items_or_abort(data, label, max_items)

    if not items:
        return []

    reasons, documents = validate_bulk_items(items, schema)

    if reasons:
        abort(400, BULK_UPDATE_INVALID_ITEMS_MSG.format(
            entities=label.plural, reasons=BULK_ITEM_REASON_SEPARATOR.join(reasons),
        ))

    public_ids: list[int] = [public_id for public_id, _ in documents]
    duplicates: list[int] = duplicate_bulk_ids(public_ids)

    if duplicates:
        abort(400, BULK_UPDATE_DUPLICATE_IDS_MSG.format(entities=label.plural, ids=duplicates))

    stored: dict[int, dict[str, Any]] = {
        doc[PUBLIC_ID_FIELD]: doc for doc in manager.find_all(criteria={PUBLIC_ID_FIELD: {"$in": public_ids}})
    }
    missing: list[int] = sorted(set(public_ids) - set(stored))

    if missing:
        abort(400, BULK_UPDATE_NOT_FOUND_MSG.format(entities=label.plural, ids=missing))

    if check_documents is not None:
        check_documents(documents)

    write_bulk_update(manager, build_bulk_update_operations(model, documents), stored, label)

    return [
        {BulkItemResultKey.PUBLIC_ID.value: public_id, BulkItemResultKey.STATUS.value: BulkItemStatus.SUCCESS.value}
        for public_id in public_ids
    ]


def read_bulk_items_or_abort(data: Any, label: IsmsEntityLabel, max_items: int) -> list[Any]:
    """
    The items of a bulk-update body, refusing a body that is not a list or is longer than allowed

    Args:
        data (Any): The parsed request body
        label (IsmsEntityLabel): The entity, for the messages
        max_items (int): The most items one request may carry

    Raises:
        werkzeug.exceptions.BadRequest: Aborts with 400 for a non-list or an over-long list

    Returns:
        list[Any]: The items as sent
    """
    if not isinstance(data, list):
        abort(400, BULK_UPDATE_NOT_A_LIST_MSG.format(entities=label.plural))

    if len(data) > max_items:
        abort(400, BULK_UPDATE_TOO_MANY_ITEMS_MSG.format(
            max_items=max_items, entities=label.plural, count=len(data),
        ))

    return data


def validate_bulk_items(
        items: list[Any],
        schema: dict[str, Any]) -> tuple[list[str], list[tuple[int, dict[str, Any]]]]:
    """
    Judges every item of a bulk update, collecting each reason instead of stopping at the first

    An item must be an object with an integer ``public_id`` (a bool is refused: ``True == 1`` would address
    id 1), and the rest of it must pass the write schema, whose unknown keys are purged

    Args:
        items (list[Any]): The items as sent
        schema (dict[str, Any]): The item write schema, without ``public_id``

    Returns:
        tuple[list[str], list[tuple[int, dict[str, Any]]]]: The reasons, empty when every item is valid, and
            each valid item's id with its cleaned document
    """
    reasons: list[str] = []
    documents: list[tuple[int, dict[str, Any]]] = []

    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            reasons.append(BULK_ITEM_NOT_AN_OBJECT_REASON.format(index=index))
            continue

        public_id: Any = item.get(PUBLIC_ID_FIELD)

        if not _is_item_public_id(public_id):
            reasons.append(BULK_ITEM_INVALID_ID_REASON.format(index=index))
            continue

        validator = Validator(schema, purge_unknown=True)
        body: dict[str, Any] = {key: value for key, value in item.items() if key != PUBLIC_ID_FIELD}

        if not validator.validate(body):
            reasons.append(BULK_ITEM_SCHEMA_REASON.format(
                index=index, public_id=public_id,
                errors=ERRORS_SEPARATOR.join(flatten_schema_errors(validator.errors)),
            ))
            continue

        documents.append((public_id, validator.document))

    return reasons, documents


def duplicate_bulk_ids(public_ids: list[int]) -> list[int]:
    """
    The ids a bulk update addresses more than once

    Args:
        public_ids (list[int]): The items' ids, in request order

    Returns:
        list[int]: Every repeated id once, ascending; empty when all are distinct
    """
    return sorted(public_id for public_id, count in Counter(public_ids).items() if count > 1)


def build_bulk_update_operations(
        model: Type[CmdbDAO],
        documents: list[tuple[int, dict[str, Any]]]) -> list[UpdateOne]:
    """
    One whole-document update per item, each built through the model like the single update

    The model serialises exactly its own keys, so a key the schema allowed but the model does not store
    cannot reach the document, and an optional key left out is stored as the model's empty value

    Args:
        model (Type[CmdbDAO]): Model class each item is built and serialised with
        documents (list[tuple[int, dict[str, Any]]]): Each item's id and validated document

    Returns:
        list[UpdateOne]: The operations, in request order
    """
    return [
        UpdateOne(
            {PUBLIC_ID_FIELD: public_id},
            {'$set': model.to_json(model.from_data({**document, PUBLIC_ID_FIELD: public_id}))},
        )
        for public_id, document in documents
    ]


def write_bulk_update(
        manager: GenericManager,
        operations: list[UpdateOne],
        stored: dict[int, dict[str, Any]],
        label: IsmsEntityLabel) -> None:
    """
    Writes a bulk update in one ordered bulk write, putting every item back when it fails part-way

    An ordered bulk write stops at its first failure with the earlier operations applied, and which ones
    is not reported reliably - so every item's snapshot is recorded before the write, and on failure the
    ledger replaces each with it; an item the write never reached is replaced by its own unchanged self

    Args:
        manager (GenericManager): Manager whose items are updated
        operations (list[UpdateOne]): The operations, in request order
        stored (dict[int, dict[str, Any]]): Each updated item as stored before the write
        label (IsmsEntityLabel): The entity, for the message when the undo cannot finish
    """
    with routes_helper.undone_on_failure(BULK_UPDATE_UNDO_INCOMPLETE_MSG.format(entities=label.plural)) as ledger:
        for public_id, prior in stored.items():
            ledger.updated(manager, public_id, prior)

        manager.bulk_write(operations)


def extract_bulk_delete_ids(public_ids: str, label: IsmsEntityLabel) -> list[int]:
    """
    Parses an ISMS bulk delete's comma-separated selection, refusing one longer than the batch cap

    Args:
        public_ids (str): The raw path segment, e.g. `'1,2,3'`
        label (IsmsEntityLabel): The entity deleted, for the refusal

    Raises:
        HTTPException: 400 when a value is not a plain positive number, or more than MAX_ISMS_BULK_DELETE_ITEMS
            ids are named

    Returns:
        list[int]: The parsed public_ids, in the order they were given
    """
    requested_ids: list[int] = routes_helper.extract_public_ids(public_ids)

    if len(requested_ids) > MAX_ISMS_BULK_DELETE_ITEMS:
        abort(400, BULK_DELETE_TOO_MANY_ITEMS_MSG.format(
            max_items=MAX_ISMS_BULK_DELETE_ITEMS, entities=label.plural, count=len(requested_ids),
        ))

    return requested_ids


def bulk_delete_reporting_in_use(
        manager: GenericManager,
        requested_ids: list[int],
        referenced_ids: Callable[[list[int]], set[int]]) -> dict[str, list[int]]:
    """
    Deletes the unreferenced subset of requested ISMS items and reports which were skipped as in use

    Shared by the ISMS bulk-delete routes whose single-delete refuses a still-referenced item
    (IsmsControlMeasure, IsmsThreat, IsmsVulnerability). The batch costs a fixed number of queries
    whatever its size (``isms_manager_helper.delete_unreferenced_batch``): one reference query, one read of the
    unreferenced items that exist, one delete, one reference query over what was deleted - an item that gained
    a reference meanwhile is put back and reported in use. A non-existent id is in neither list

    Args:
        manager (GenericManager): The manager whose items are deleted
        requested_ids (list[int]): The requested item public_ids
        referenced_ids (Callable[[list[int]], set[int]]): The manager's batched usage check

    Raises:
        Exception: The manager's 'get' error when the usage check or the read fails, its 'delete' error when the
            delete or the restore fails

    Returns:
        dict[str, list[int]]: {'successfully': [deleted ids], 'in_use': [skipped in-use ids]}, both
            sorted ascending
    """
    deleted_ids, in_use_ids = delete_unreferenced_batch(manager, requested_ids, referenced_ids)

    return {
        ISMS_BULK_DELETE_DELETED_KEY: deleted_ids,
        ISMS_BULK_DELETE_IN_USE_KEY: in_use_ids,
    }


def coerce_isms_number(data: dict[str, Any], key: str, refusal: str, optional: bool = False) -> None:
    """
    Normalises a client-supplied number to a float with ISMS_NUMBER_DECIMALS decimals, in place

    The ISMS forms send a number as a string as often as a number. A value that will not convert - absent when
    required, not numeric, too large for a float - is refused with ``refusal``

    Args:
        data (dict[str, Any]): The request body holding the value
        key (str): The key of the value
        refusal (str): The 400's message
        optional (bool): Whether an absent or None value is left alone. Defaults to False

    Raises:
        HTTPException: 400 when the value is required but absent, or cannot be converted
    """
    value: Any = data.get(key)

    if value is None and optional:
        return

    try:
        data[key] = round(float(value), ISMS_NUMBER_DECIMALS)
    except (TypeError, ValueError, OverflowError):
        abort(400, refusal)


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

    The existence read raises the base ``BaseManagerGetError``, so it is answered here with its own message rather
    than in a route's error table - mapping that class there would also catch any other step of the route that raises
    it, and give that step this read's message. Every route calling this does so before its first write

    Raises:
        werkzeug.exceptions.BadRequest: Aborts with 400 naming the unknown measure ids, sorted, or with
            ``CONTROL_MEASURE_LOOKUP_FAILED_MSG`` when the ControlMeasures could not be read
    """
    try:
        missing_control_measures: set[int] = cm_assignment_manager.get_missing_control_measure_ids(assignments)
    except BaseManagerGetError as err:
        LOGGER.error("[abort_on_unknown_control_measures] %s: %s", type(err).__name__, err, exc_info=True)
        abort(400, CONTROL_MEASURE_LOOKUP_FAILED_MSG)

    if missing_control_measures:
        abort(400, UNKNOWN_CONTROL_MEASURES_MSG.format(unknown=sorted(missing_control_measures)))


def read_assessment_assignments(
        risk_assessment_manager: Any,
        risk_assessment_id: int,
        failure_message: str) -> list[dict[str, Any]]:
    """
    Reads the stored ControlMeasureAssignments of one RiskAssessment, a failed read answering the caller's 400

    The read raises the base ``BaseManagerGetError``, so - like ``abort_on_unknown_control_measures`` - it is
    answered here, with the message the caller names for its own step, instead of in a route's error table

    Args:
        risk_assessment_manager (Any): The RiskAssessmentManager, anything with ``get_many_from_other_collection``
        risk_assessment_id (int): public_id of the RiskAssessment whose assignments are read
        failure_message (str): The 400's message, complete

    Raises:
        werkzeug.exceptions.BadRequest: Aborts with 400 and ``failure_message`` when the read fails, the error logged

    Returns:
        list[dict[str, Any]]: The stored assignments, without ``_id``
    """
    try:
        return risk_assessment_manager.get_many_from_other_collection(
            IsmsControlMeasureAssignment.COLLECTION,
            criteria={ControlMeasureAssignmentKey.RISK_ASSESSMENT_ID.value: risk_assessment_id},
        )
    except BaseManagerGetError as err:
        LOGGER.error("[read_assessment_assignments] %s: %s", type(err).__name__, err, exc_info=True)
        abort(400, failure_message)


def abort_on_unknown_risks(risk_assessment_manager: Any, risk_ids: set[int]) -> None:
    """
    Refuses a RiskAssessment write naming an IsmsRisk that does not exist

    An assessment of a missing Risk shows blank risk columns in both reports and is never reached by the Risk delete's
    cascade, so it is refused before anything is written - one query for all the ids

    Args:
        risk_assessment_manager (Any): The RiskAssessmentManager, anything with its ``get_missing_risk_ids``
        risk_ids (set[int]): The public_ids of the IsmsRisks the write names

    Raises:
        werkzeug.exceptions.BadRequest: Aborts with 400 naming the unknown Risk ids, sorted
        RiskAssessmentManagerRiskReadError: If the Risks could not be read
    """
    missing_risks: set[int] = risk_assessment_manager.get_missing_risk_ids(risk_ids)

    if missing_risks:
        abort(400, UNKNOWN_RISKS_MSG.format(unknown=sorted(missing_risks)))


def abort_on_unknown_options(
        option_field: IsmsOptionField,
        option_ids: Iterable[int | None],
        request_user: CmdbUser) -> None:
    """
    Refuses an ISMS write naming a CmdbExtendableOption that is no option of the list its field draws from

    Every ISMS field holding an option id goes through here (``IMPLEMENTATION_STATE_OPTION``, the three ``source``
    fields, the Risk's category). An option of another list counts as unknown: it would be shown as a value of the
    wrong kind - and every label lookup reads within the field's own list, so it would render blank. A null value
    (nothing chosen) is not judged. One projected read for every id; nothing is read when none is named

    The read raises ``ExtendableOptionsManagerGetError``, answered here with its own message - like
    ``abort_on_unknown_control_measures`` - so no route's error table has to map it. Every route calling this does so
    before its first write

    Args:
        option_field (IsmsOptionField): The field's list and the label its refusals name it by
        option_ids (Iterable[int | None]): The option ids the write names; None entries are skipped
        request_user (CmdbUser): The user issuing the request, whose database the options are read from

    Raises:
        werkzeug.exceptions.BadRequest: Aborts with 400 naming the unknown ids, sorted, or when the options could not
            be read
    """
    named: set[int] = {option_id for option_id in option_ids if option_id is not None}

    if not named:
        return

    extendable_options_manager: ExtendableOptionsManager = ManagerProvider.get_manager(
        ManagerType.EXTENDABLE_OPTIONS, request_user
    )

    try:
        missing: set[int] = extendable_options_manager.get_missing_option_ids(option_field.option_type.value, named)
    except ExtendableOptionsManagerGetError as err:
        LOGGER.error("[abort_on_unknown_options] %s: %s", type(err).__name__, err, exc_info=True)
        abort(400, OPTION_LOOKUP_FAILED_MSG.format(label=option_field.label))

    if missing:
        abort(400, UNKNOWN_OPTIONS_MSG.format(
            label=option_field.label, unknown=sorted(missing), option_type=option_field.option_type.value,
        ))


def abort_on_unknown_implementation_states(state_ids: Iterable[int | None], request_user: CmdbUser) -> None:
    """
    Refuses an ISMS write naming an implementation state that is no option of the IMPLEMENTATION_STATE list

    Shared by the RiskAssessment (its own ``implementation_status`` and its embedded assignments'), the
    ControlMeasureAssignment and the ControlMeasure writes - ``abort_on_unknown_options`` for that one list

    Args:
        state_ids (Iterable[int | None]): The implementation states the write names; None entries are skipped
        request_user (CmdbUser): The user issuing the request, whose database the options are read from

    Raises:
        werkzeug.exceptions.BadRequest: Aborts with 400 naming the unknown ids, sorted, or with
            ``IMPLEMENTATION_STATE_LOOKUP_FAILED_MSG`` when the options could not be read
    """
    abort_on_unknown_options(IMPLEMENTATION_STATE_OPTION, state_ids, request_user)


def assessed_object_changed(data: dict[str, Any], stored: dict[str, Any]) -> bool:
    """
    Whether a RiskAssessment update assesses another object than the stored assessment

    The update judges the assessed object only when it changes - like a person reference, one the stored assessment
    already holds is not judged again, so an assessment whose object was lost to a failed delete clean-up can still be
    saved

    Args:
        data (dict[str, Any]): The update payload
        stored (dict[str, Any]): The stored RiskAssessment

    Returns:
        bool: True when ``object_id_ref_type`` or ``object_id`` differs from the stored one
    """
    return any(
        data.get(key.value) != stored.get(key.value)
        for key in (RiskAssessmentKey.OBJECT_ID_REF_TYPE, RiskAssessmentKey.OBJECT_ID)
    )


def readable_type_exclusions(reference_type: str, request_user: CmdbUser) -> list[int]:
    """
    The CmdbTypes whose objects a RiskAssessment write may not assess: the ones the caller may not READ

    Read only for an OBJECT - a CmdbObjectGroup carries no ACL, so naming one costs no read of the types

    Args:
        reference_type (str): The assessment's ``object_id_ref_type``
        request_user (CmdbUser): The caller

    Raises:
        BaseManagerGetError: If the types could not be read
        BaseManagerInitError: If the types manager could not be built

    Returns:
        list[int]: public_ids of the denied CmdbTypes; empty for an OBJECT_GROUP or when nothing is denied
    """
    if reference_type == ObjectReferenceType.OBJECT_GROUP:
        return []

    return resolve_denied_type_ids(request_user, AccessControlPermission.READ)


def abort_on_unknown_assessed_objects(
        risk_assessment_manager: Any,
        reference_type: str,
        object_ids: set[int],
        request_user: CmdbUser) -> None:
    """
    Refuses a RiskAssessment write assessing a CmdbObject or CmdbObjectGroup that is not there for the caller

    An object that does not exist and an object of a type the caller may not READ get the same 400, so the answer says
    nothing about objects the caller cannot see; a group is judged by its existence alone. One read of the types (for
    an OBJECT) and one projected read for every id, before anything is written. A failed read is answered here with
    its own 400, like ``abort_on_unknown_control_measures``

    Args:
        risk_assessment_manager (Any): The RiskAssessmentManager, anything with its ``get_missing_assessed_ids``
        reference_type (str): The ``object_id_ref_type`` the ids are of
        object_ids (set[int]): The assessed ids; nothing is read when none is named
        request_user (CmdbUser): The caller, whose READ ACL judges an object

    Raises:
        werkzeug.exceptions.BadRequest: Aborts with 400 naming the missing (or hidden) ids, sorted, or with
            ``ASSESSED_OBJECT_LOOKUP_FAILED_MSG`` when a read fails
    """
    if not object_ids:
        return

    try:
        missing: set[int] = risk_assessment_manager.get_missing_assessed_ids(
            ObjectReferenceType(reference_type), object_ids, readable_type_exclusions(reference_type, request_user),
        )
    except (BaseManagerGetError, BaseManagerInitError) as err:
        LOGGER.error("[abort_on_unknown_assessed_objects] %s: %s", type(err).__name__, err, exc_info=True)
        abort(400, ASSESSED_OBJECT_LOOKUP_FAILED_MSG)

    if missing:
        template: str = (UNKNOWN_ASSESSED_OBJECT_GROUPS_MSG if reference_type == ObjectReferenceType.OBJECT_GROUP
                         else UNKNOWN_ASSESSED_OBJECTS_MSG)
        abort(400, template.format(unknown=sorted(missing)))
