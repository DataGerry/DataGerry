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
Implementation of general API route helpers
"""
import json
from contextlib import contextmanager
from collections.abc import Iterable, Iterator, Sequence
from http import HTTPStatus
from typing import Any, NoReturn, TypeVar
from logging import Logger, getLogger
from flask import request, abort
from werkzeug.datastructures import FileStorage
from werkzeug.wrappers import Request

from cmdb.manager.query_builder import BuilderParameters
from cmdb.utils import Builder, find_cause, str_to_bool
from cmdb.errors.database import DocumentDuplicateKeyError
from cmdb.framework.write_ledger import LedgerResidue, WriteLedger
from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.framework.search.list_search import build_list_search_stages
from cmdb.interface.rest_api.responses.response_parameters import (
    BuilderParamKey,
    CollectionParameters,
    ParameterKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

ItemT = TypeVar('ItemT')

# The one HTTP method that asks for a response without a payload
HEAD_METHOD: str = 'HEAD'

# Refusal (HTTP 400) for a write request whose body is present but is not a JSON object
WRITE_PAYLOAD_NOT_AN_OBJECT_MSG: str = (
    "The {entity} write payload must be a JSON object when it is sent as a request body!"
)

# Refusal (HTTP 400) for a write naming public_ids its referenced collection does not hold, formatted with what
# the ids refer to and the sorted unknown ids
UNKNOWN_REFERENCES_MSG: str = "The following {entity_label} ID(s) do not exist: {unknown}!"

# Refusal (HTTP 400) for a selection of public_ids that is not a list - a string would be read digit by digit
PUBLIC_ID_LIST_NOT_A_LIST_MSG: str = "The public_ids have to be sent as a list, not as {kind}!"

# Refusal (HTTP 400) of a boolean query parameter spelled anything but true / false
BOOLEAN_PARAM_INVALID_MSG: str = "The '{param}' parameter must be 'true' or 'false'!"

# -------------------------------------------------------------------------------------------------------------------- #

def get_file_in_request(file_name: str) -> FileStorage:
    """
    Retrieves an uploaded file from the current multipart request by its field name

    Shared by the object-import and media-library routes so the missing-file guard lives in one place.

    Args:
        file_name (str): The name of the file field expected in the request

    Raises:
        HTTPException: 400 if the named file is not present in the request

    Returns:
        FileStorage: The uploaded file object
    """
    # request.files.get returns None (does not raise) for a missing file, so guard explicitly
    uploaded_file = request.files.get(file_name)

    if uploaded_file is None:
        LOGGER.error("[get_file_in_request] File with name: %s was not provided!", file_name)
        abort(400, f"File with name: {file_name} was not provided!")

    return uploaded_file


def get_element_from_data_request(element: str, _request: Request) -> dict[str, Any] | None:
    """
    Extracts and JSON-parses a single form field from a multipart request

    Returns None when the field is absent or not valid JSON (both are expected for optional fields),
    so an unexpected error is not silently swallowed.

    Args:
        element (str): The name of the form field to extract
        _request (Request): The Flask request object carrying the form data

    Returns:
        dict[str, Any] | None: The parsed JSON object, or None if the field is missing or not valid JSON
    """
    try:
        return json.loads(_request.form.to_dict()[element])
    except (KeyError, TypeError, json.JSONDecodeError):
        LOGGER.debug("[get_element_from_data_request] Field '%s' is absent or not valid JSON", element)
        return None


def read_boolean_query_param(name: str, default: bool) -> bool:
    """
    Reads a boolean query parameter by the API's one rule for flags

    Absent, the parameter is ``default``. Present, it must be ``true`` or ``false`` - any casing, surrounding
    whitespace ignored (``str_to_bool``) - and **anything else is refused**, the empty value included: a caller who
    sends ``?flag=`` or ``?flag=0`` meant something, and guessing what would answer the opposite as often as not

    Args:
        name (str): The query parameter's name
        default (bool): The value when the parameter is absent

    Raises:
        HTTPException: 400 naming the parameter and the two accepted spellings

    Returns:
        bool: The flag
    """
    raw_value: str | None = request.args.get(name)

    if raw_value is None:
        return default

    try:
        return str_to_bool(raw_value)
    except ValueError:
        abort(400, BOOLEAN_PARAM_INVALID_MSG.format(param=name))


def fetch_only_active_objects() -> bool:
    """
    Checking if request have cookie parameter for object active state

    Returns:
        bool: True if cookie value is true or True else False
    """
    return request.args.get('onlyActiveObjCookie') in ['True', 'true']


def request_wants_body(current_request: Request | None = None) -> bool:
    """
    Answers whether a request expects a response body

    Every read route that serves `HEAD` alongside `GET` passes this into its response class, which is
    what makes a HEAD answer carry the status and the headers (`X-Total-Count` included) but no
    payload - and, because the payload is then never built, no serialization cost either.

    It exists as one function on purpose: spelled inline the routes each write the question as
    `body=request.method == 'HEAD'` in six different spellings, which is the answer INVERTED (the flag
    means "send a body"), and the mistake was invisible because the flag itself was inert.

    Args:
        current_request (Request | None): The request to judge. Defaults to the active one, which is
            what a route wants; a helper that already receives a request passes it in, so the rule
            still lives in one place

    Returns:
        bool: False for a HEAD request, True for every other method
    """
    return (current_request or request).method != HEAD_METHOD


def read_write_payload(query_params: dict[str, Any], entity_label: str) -> dict[str, Any]:
    """
    Reads a write payload from the request body, falling back to the query string

    **The body wins, key by key.** A client may send the payload either way, and a client that sends
    both - which the Angular report and webhook forms do, building query parameters *and* posting the
    same object as the body - is served from the body: there the values arrive already typed, where the
    query string can only carry text. Merging rather than choosing means neither half can go missing.

    A body is optional. A body that is not a JSON object is refused rather than ignored: it was meant
    as the payload, and silently reading the query string instead would answer 400 'missing parameter'
    for a request whose problem is its body

    Args:
        query_params (dict[str, Any]): The query-string parameters, as the route decorator read them;
            not modified
        entity_label (str): What is being written (e.g. 'Report'), used in the refusal message

    Raises:
        HTTPException: 400 when a request body is present but is not a JSON object

    Returns:
        dict[str, Any]: The merged payload, still raw
    """
    body: Any = request.get_json(silent=True)

    if body is None:
        return dict(query_params)

    if not isinstance(body, dict):
        abort(400, WRITE_PAYLOAD_NOT_AN_OBJECT_MSG.format(entity=entity_label))

    return {**query_params, **body}


def as_pipeline_criteria(request_filter: dict[str, Any] | list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """
    Answers a client's ``?filter=`` as pipeline stages, as a NEW list

    A list route composes the caller's filter with stages of its own - the active-only flag, a
    ``?search=`` term, a "which of these may I pick" rule - and the two filter shapes have to be one
    thing before it can. A plain filter document becomes a single ``$match``; a pipeline is copied.

    **The copy is the point.** A route appending its stages to ``params.filter`` in place leaves
    the same object is handed to ``GetMultiResponse``, which echoes it back as ``parameters.filter`` -
    so the response claimed the caller had sent stages the server injected. An empty filter answers no
    stages at all rather than an empty ``$match``

    Args:
        request_filter (dict[str, Any] | list[dict[str, Any]] | None): The parsed ``?filter=``

    Returns:
        list[dict[str, Any]]: The stages to build on, never the caller's own object
    """
    if isinstance(request_filter, list):
        return list(request_filter)

    if not request_filter:
        return []

    return [Builder.match_(request_filter)]


def build_searchable_builder_params(params: Any, searchable_fields: Sequence[str]) -> BuilderParameters:
    """
    Turns a list route's CollectionParameters into BuilderParameters, with ``?search=`` folded in

    The one place a list route reaches for when its table has a search box. It composes the caller's
    ``?filter=`` with the search stages and hands the rest of the pager through unchanged, so every
    table searches the same way and the set of searchable columns is declared server-side rather than
    hard-coded in eighteen Angular components.

    An absent or blank ``?search=`` adds nothing, so an unsearched listing is exactly what it was

    Args:
        params (Any): The route's CollectionParameters
        searchable_fields (Sequence[str]): The field paths this route declares searchable

    Returns:
        BuilderParameters: Ready for the manager's ``iterate``
    """
    criteria: list[dict[str, Any]] = as_pipeline_criteria(params.filter)
    criteria.extend(build_list_search_stages(params.optional.get(ParameterKey.SEARCH.value), searchable_fields))

    builder_args: dict[str, Any] = CollectionParameters.get_builder_params(params)
    builder_args[BuilderParamKey.CRITERIA.value] = criteria

    return BuilderParameters(**builder_args)


def append_criteria_to_filter(
        request_filter: dict[str, Any] | list[dict[str, Any]] | None,
        criteria: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Appends route-owned criteria to the caller's ``?filter=`` as a further pipeline stage

    The technique the objects route uses for its active-objects filter: a dict filter becomes a single
    '$match' stage and the route's own criteria are appended after it, so the caller's filter narrows
    the result and the route's rules narrow it further. Appending rather than merging means a caller
    can not overwrite one of those rules by naming the same key. Shared by every list route that
    answers a "which of these may I pick" question - the Rack's assignable objects and the
    port-connection picker's unassigned cables

    Args:
        request_filter (dict[str, Any] | list[dict[str, Any]] | None): The parsed ``?filter=``, either
            a criteria dict or an aggregation pipeline
        criteria (dict[str, Any]): The route's own criteria; an empty dict appends nothing

    Returns:
        list[dict[str, Any]]: The pipeline to hand to the query builder
    """
    pipeline: list[dict[str, Any]] = as_pipeline_criteria(request_filter)

    if criteria:
        pipeline.append(Builder.match_(criteria))

    return pipeline


def pin_public_id(data: dict[str, Any], public_id: int) -> dict[str, Any]:
    """
    Pins a write payload's identity to the public_id the URL names

    Every update route addresses its document by the URL's public_id, but the validated body may
    carry a ``public_id`` of its own - the request schemas declare the key, and a model's ``to_json``
    writes whatever it was built with, so an unpinned route hands the manager a document whose id is
    the CLIENT's. The manager updates by the URL id and ``$set``s the body wholesale, which moves the
    stored document to the client's id: the row silently changes identity, or collides with the
    document already living there

    Pinning also removes the opposite failure. ``public_id`` is optional in the schemas, so a body
    without one is valid - and ``CmdbDAO.__init__`` calls ``int(public_id)``, which raises on None and
    surfaced as a 500. After pinning there is always an id to build the model from

    Args:
        data (dict[str, Any]): The validated request body; mutated in place
        public_id (int): public_id from the URL - the only identity a write route may act on

    Returns:
        dict[str, Any]: The same dict, so the call can wrap the argument at the call site
    """
    data[CmdbDAO.PUBLIC_ID_KEY] = public_id

    return data


def update_item_from_payload(
        manager: Any,
        public_id: int,
        model_class: type[Any],
        data: dict[str, Any],
    ) -> dict[str, Any]:
    """
    Builds the model an update writes, writes it, and answers the document that was stored

    ``GenericManager.update_item`` stores ``model_class.to_json(model)`` wholesale, so the model the
    write is built from IS the stored document: answering with its serialisation costs no extra query
    and cannot disagree with the next read. Answering with the request body instead reports a payload
    that left out an optional key - or sent it as ``null`` - as if it had been stored that way, while the
    model stored its empty value

    Args:
        manager (Any): The GenericManager of the model's collection
        public_id (int): public_id of the document to update, taken from the URL
        model_class (type[Any]): The model class the document is built with
        data (dict[str, Any]): The validated, identity-pinned request body

    Returns:
        dict[str, Any]: The document as stored, for the update response
    """
    model: Any = model_class.from_data(data)

    manager.update_item(public_id, model)

    return model_class.to_json(model)


def extract_public_ids(public_ids: str) -> list[int]:
    """
    Parses a comma-separated public_id path segment into a list of integers

    Shared by every route that addresses a set of documents through the URL (bulk delete, export by
    ids) so they all read a selection the same way - which matters most for the delete routes, where
    a mis-read id deletes the wrong document

    Each value must be a plain, positive, ASCII decimal number. `int()` alone is too permissive for a
    URL segment: it strips surrounding whitespace, accepts a leading sign, ignores PEP-515 underscores
    (`5_3001` would silently mean `53001`) and converts non-ASCII digits, so a selection could be
    read as ids the caller never wrote. Duplicates and ordering are preserved for the caller to handle

    Args:
        public_ids (str): The raw path segment, e.g. `'1,2,3'`

    Raises:
        HTTPException: 400 naming the first value that is not a plain positive number

    Returns:
        list[int]: The parsed public_ids, in the order they were given
    """
    extracted_ids: list[int] = []

    for value in public_ids.split(","):
        # isascii() matters: '٥'.isdigit() is True and int() would happily turn it into 5
        if not (value.isascii() and value.isdigit()) or int(value) < 1:
            abort(400, f"Invalid value detected for public_id: {value} !")

        extracted_ids.append(int(value))

    return extracted_ids


def normalize_public_id_list(values: Any) -> list[int]:
    """
    Normalises the public_ids of a JSON request body into a list of integers

    The body counterpart of `extract_public_ids`: a bulk operation may send its selection as JSON
    numbers or as strings, and both have to end up as the same positive integers. `isinstance(x, int)`
    alone is not enough - `bool` IS an `int` in Python, so a JSON `true` would silently become
    public_id 1 and address a document the caller never named. The selection itself has to be a list
    too: a string is iterable, and "12" would otherwise address the ids 1 and 2. Duplicates and ordering
    are preserved for the caller to handle

    Args:
        values (Any): The raw public_ids taken from the request body, expected to be a list

    Raises:
        HTTPException: 400 when the selection is not a list, or naming the first value that is not a
            plain positive number

    Returns:
        list[int]: The normalised public_ids, in the order they were given
    """
    if not isinstance(values, list):
        abort(400, PUBLIC_ID_LIST_NOT_A_LIST_MSG.format(kind=type(values).__name__))

    normalized_ids: list[int] = []

    for value in values:
        if isinstance(value, bool):
            abort(400, f"Invalid value detected for public_id: {value} !")

        if not isinstance(value, int) and not (isinstance(value, str) and value.isascii() and value.isdigit()):
            abort(400, f"Invalid value detected for public_id: {value} !")

        candidate = int(value)

        if candidate < 1:
            abort(400, f"Invalid value detected for public_id: {value} !")

        normalized_ids.append(candidate)

    return normalized_ids


def require_created_item(item: ItemT | None, not_readable_message: str) -> ItemT:
    """
    Answers the item an insert route just created, refusing with a 500 when it cannot be read back

    The insert has just reported the new public_id, so a read that finds nothing is not a missing
    resource the caller asked for - it is the server failing to see its own write. That is a 500, not
    the 404 a lookup of a caller-supplied id would answer. The read-back may be a raw document or a
    model instance; either is answered as it came

    Args:
        item (ItemT | None): The read-back of the created item
        not_readable_message (str): The message of the 500

    Raises:
        werkzeug.exceptions.InternalServerError: Aborts with 500 when the item was not found

    Returns:
        ItemT: The created item
    """
    if not item:
        abort(HTTPStatus.INTERNAL_SERVER_ERROR, not_readable_message)

    return item


def abort_if_duplicate(err: Exception, duplicate_message: str) -> NoReturn:
    """
    Answers a write refused by a unique index with the route's readable 400, and re-raises anything else

    A write route pre-checks its uniqueness rule with a read, but only the unique index holds under
    concurrency - so the manager error of the write is where a lost race shows up. It is ALSO where an
    outage or any other failure of the write shows up, which is why the cause is looked for rather than
    assumed: only a ``DocumentDuplicateKeyError`` somewhere in the chain is the caller's clash, and
    everything else is re-raised for the route's generic tail to answer as the server error it is

    Call it from the ``except`` of the write alone, so nothing but that write's error reaches it

    Args:
        err (Exception): The manager error the write raised
        duplicate_message (str): What the 400 says, the same text the route's pre-check answers

    Raises:
        werkzeug.exceptions.BadRequest: Aborts with 400 when the write violated a unique index
        Exception: ``err`` itself, unchanged, when it did not
    """
    if find_cause(err, DocumentDuplicateKeyError) is not None:
        abort(HTTPStatus.BAD_REQUEST, duplicate_message)

    raise err


def abort_if_taken(
        manager: Any,
        criteria: dict[str, Any],
        taken_message: str,
        exclude_id: int | None = None) -> None:
    """
    Refuses a write whose unique value another stored document already holds

    The readable half of a uniqueness rule that a unique index enforces: the index is what holds under
    concurrency (its refusal is answered by ``abort_if_duplicate``), this read is what makes the ordinary
    case say which value clashed. The value is compared as sent - exactly what the index compares - so the
    check refuses precisely what the index would, and a stored near-twin (another case, surrounding blanks)
    never blocks a write of its own

    Args:
        manager (Any): The manager of the collection, anything with BaseManager's ``get_one_by``
        criteria (dict[str, Any]): The unique value(s) the write would store, e.g. ``{'name': 'Admins'}``
        taken_message (str): What the 400 says; the same text the write's duplicate refusal answers
        exclude_id (int | None): public_id of the document being updated, which may keep its own value.
            Defaults to None (a create)

    Raises:
        werkzeug.exceptions.BadRequest: Aborts with 400 when another document holds the value
    """
    existing: dict[str, Any] | None = manager.get_one_by(criteria)

    if not existing or (exclude_id is not None and existing.get(CmdbDAO.PUBLIC_ID_KEY) == exclude_id):
        return

    abort(HTTPStatus.BAD_REQUEST, taken_message)


def abort_on_unknown_references(
        manager: Any,
        public_ids: Iterable[int] | None,
        entity_label: str) -> None:
    """
    Refuses the request when a referenced public_id does not exist

    One projected ``$in`` query for the whole selection (``GenericManager.find_existing_public_ids``), so a
    payload naming many references costs one read, and an empty or missing selection costs none

    Args:
        manager (Any): The manager owning the referenced collection, anything with GenericManager's
            ``find_existing_public_ids``
        public_ids (Iterable[int] | None): The referenced public_ids; nothing is checked for an empty
            or missing selection
        entity_label (str): What the ids refer to, used in the error message (e.g. 'PersonGroup')

    Raises:
        werkzeug.exceptions.BadRequest: Aborts with 400 naming every id that does not exist, sorted
    """
    referenced: list[int] = list(public_ids or [])

    if not referenced:
        return

    unknown: list[int] = sorted(set(referenced) - manager.find_existing_public_ids(referenced))

    if unknown:
        abort(HTTPStatus.BAD_REQUEST, UNKNOWN_REFERENCES_MSG.format(entity_label=entity_label, unknown=unknown))


def undo_or_abort(ledger: WriteLedger, residue_message: str) -> None:
    """
    Undoes a failed request's writes, refusing with a 500 that names whatever could not be undone

    Call it from the ``except`` of the write phase and re-raise the original error afterwards: a clean undo
    returns, so the request fails with the error it actually hit (its own 400 or 500) and nothing it wrote is
    left behind. An undo that could not finish is a different outcome - rows nobody asked for are stored, which
    the caller cannot fix by editing their request - so it is a 500 naming every one of them

    Args:
        ledger (WriteLedger): The writes the request made
        residue_message (str): The 500's message, a template with a ``{residue}`` placeholder

    Raises:
        werkzeug.exceptions.InternalServerError: Aborts with 500 when the undo left anything behind
    """
    residue: list[LedgerResidue] = ledger.undo()

    if residue:
        LOGGER.error("[undo_or_abort] The undo left %s write(s) in effect: %s", len(residue), residue)
        abort(HTTPStatus.INTERNAL_SERVER_ERROR,
              residue_message.format(residue=[item.to_json() for item in residue]))


@contextmanager
def undone_on_failure(residue_message: str) -> Iterator[WriteLedger]:
    """
    A fresh WriteLedger for a block of writes, undone when the block fails

    ``with undone_on_failure(MESSAGE) as ledger:`` - record every write of the block in ``ledger``. When the block
    raises, the writes are undone (``undo_or_abort``) and the original error is re-raised unchanged, so the request
    fails with the error it actually hit and the route's own error mapping answers it; an undo that could not
    finish answers the 500 naming what is left instead

    Args:
        residue_message (str): The 500's message when the undo cannot finish, with a ``{residue}`` placeholder

    Yields:
        WriteLedger: The ledger to record the block's writes in
    """
    ledger = WriteLedger()

    try:
        yield ledger
    except Exception:
        undo_or_abort(ledger, residue_message)
        raise
