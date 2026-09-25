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
from collections.abc import Sequence
from typing import Any
from logging import Logger, getLogger
from flask import request, abort
from werkzeug.datastructures import FileStorage
from werkzeug.wrappers import Request

from cmdb.manager.query_builder import BuilderParameters
from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.framework.search.list_search import build_list_search_stages
from cmdb.interface.rest_api.responses.response_parameters import (
    BuilderParamKey,
    CollectionParameters,
    ParameterKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The one HTTP method that asks for a response without a payload
HEAD_METHOD: str = 'HEAD'

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


def get_element_from_data_request(element: str, _request: Request) -> dict | None:
    """
    Extracts and JSON-parses a single form field from a multipart request

    Returns None when the field is absent or not valid JSON (both are expected for optional fields),
    so an unexpected error is not silently swallowed.

    Args:
        element (str): The name of the form field to extract
        _request (Request): The Flask request object carrying the form data

    Returns:
        dict | None: The parsed JSON object, or None if the field is missing or not valid JSON
    """
    try:
        return json.loads(_request.form.to_dict()[element])
    except (KeyError, TypeError, json.JSONDecodeError):
        LOGGER.debug("[get_element_from_data_request] Field '%s' is absent or not valid JSON", element)
        return None


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

    return [{'$match': request_filter}]


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
        pipeline.append({'$match': criteria})

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


def normalize_public_id_list(values: list[Any]) -> list[int]:
    """
    Normalises the public_ids of a JSON request body into a list of integers

    The body counterpart of `extract_public_ids`: a bulk operation may send its selection as JSON
    numbers or as strings, and both have to end up as the same positive integers. `isinstance(x, int)`
    alone is not enough - `bool` IS an `int` in Python, so a JSON `true` would silently become
    public_id 1 and address a document the caller never named. Duplicates and ordering are preserved
    for the caller to handle

    Args:
        values (list[Any]): The raw public_ids taken from the request body

    Raises:
        HTTPException: 400 naming the first value that is not a plain positive number

    Returns:
        list[int]: The normalised public_ids, in the order they were given
    """
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
