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
What the access rule routes share: reading a document through its model or answering 404, the list read, and the
create / update / delete that turn a lost uniqueness race into the same 400 as the pre-check
"""
from typing import Any

from flask import abort, request
from werkzeug import Response

from cmdb.manager.generic_manager import GenericManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.framework.results import IterationResult
from cmdb.framework.access_engine import forget_grants
from cmdb.interface.rest_api.responses import (
    DeleteSingleResponse,
    GetMultiResponse,
    InsertSingleResponse,
    UpdateSingleResponse,
)
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.rest_api.routes.routes_helper import (
    abort_if_duplicate,
    build_searchable_builder_params,
    pin_public_id,
    request_wants_body,
    update_item_from_payload,
)
from cmdb.interface.rest_api.routes.access_routes.access_route_constants import AccessRouteMessage
# -------------------------------------------------------------------------------------------------------------------- #


def as_model_json(model: type[CmdbDAO], documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Answers stored documents the way the model writes them - every key, in the model's order - as the list, create
    and update answers do

    Args:
        model (type[CmdbDAO]): The documents' model
        documents (list[dict[str, Any]]): The documents as stored

    Returns:
        list[dict[str, Any]]: The documents through the model
    """
    return [model.to_json(model.from_data(document)) for document in documents]


def load_or_404(manager: GenericManager, public_id: int, label: str) -> dict[str, Any]:
    """
    Reads a stored document through its model, answering 404 when there is none

    Args:
        manager (GenericManager): The manager of the document's collection
        public_id (int): The document's public_id
        label (str): What the document is, for the message

    Raises:
        HTTPException: 404 when no document carries the id
        Exception: The manager's 'get' error when the read fails

    Returns:
        dict[str, Any]: The document as its model writes it
    """
    document: dict[str, Any] | None = manager.get_item(public_id, as_dict=True)

    if document is None:
        abort(404, AccessRouteMessage.NOT_FOUND.value.format(label=label, public_id=public_id))

    return as_model_json(manager.model, [document])[0]


def list_response(manager: GenericManager, model: type[CmdbDAO], params: CollectionParameters,
                  searchable: tuple[str, ...], condition: dict[str, Any] | None = None) -> Response:
    """
    Answers one page of a collection, through the client's filter, search, sort and paging

    Args:
        manager (GenericManager): The manager of the collection
        model (type[CmdbDAO]): Its model
        params (CollectionParameters): The request's collection parameters
        searchable (tuple[str, ...]): The columns ``?search=`` looks in
        condition (dict[str, Any] | None): A server-side condition put ahead of the client's filter, or None

    Raises:
        Exception: The manager's 'iterate' error when the read fails

    Returns:
        Response: The page, its total and the paging links
    """
    builder_params: BuilderParameters = build_searchable_builder_params(params, searchable)

    if condition is not None:
        builder_params.add_criteria(condition)

    result: IterationResult[CmdbDAO] = manager.iterate_items(builder_params)

    return GetMultiResponse([model.to_json(item) for item in result.results], result.total, params, request.url,
                            request_wants_body()).make_response()


def create_response(manager: GenericManager, model: type[CmdbDAO], payload: dict[str, Any],
                    duplicate_message: str) -> Response:
    """
    Stores a new document and answers it as stored; a unique index refusing it is the pre-check's 400

    Args:
        manager (GenericManager): The manager of the collection
        model (type[CmdbDAO]): Its model
        payload (dict[str, Any]): The judged document, without a public_id
        duplicate_message (str): What a lost uniqueness race says

    Raises:
        HTTPException: 400 when a unique index refused the document
        Exception: The manager's 'insert' error for any other failure

    Returns:
        Response: 201 with the stored document and its new id
    """
    try:
        public_id: int = manager.insert_item(payload)
    except manager.exceptions['insert'] as err:
        abort_if_duplicate(err, duplicate_message)

    # The request's access grants are stale now
    forget_grants()
    stored: dict[str, Any] = model.to_json(model.from_data({**payload, CmdbDAO.PUBLIC_ID_KEY: public_id}))

    return InsertSingleResponse(stored, public_id).make_response()


def update_response(manager: GenericManager, model: type[CmdbDAO], public_id: int, payload: dict[str, Any],
                    duplicate_message: str) -> Response:
    """
    Writes a judged update and answers the document as stored; a unique index refusing it is the pre-check's 400

    Args:
        manager (GenericManager): The manager of the collection
        model (type[CmdbDAO]): Its model
        public_id (int): The document the URL names
        payload (dict[str, Any]): The judged document, completed from the stored one
        duplicate_message (str): What a lost uniqueness race says

    Raises:
        HTTPException: 400 when a unique index refused the document
        Exception: The manager's 'update' error for any other failure

    Returns:
        Response: 202 with the stored document
    """
    try:
        stored: dict[str, Any] = update_item_from_payload(manager, public_id, model, pin_public_id(payload, public_id))
    except manager.exceptions['update'] as err:
        abort_if_duplicate(err, duplicate_message)

    forget_grants()

    return UpdateSingleResponse(stored).make_response()


def delete_response(manager: GenericManager, stored: dict[str, Any]) -> Response:
    """
    Deletes a document the caller read and judged, and answers it as it was stored

    Args:
        manager (GenericManager): The manager of the collection
        stored (dict[str, Any]): The document as stored (``load_or_404``)

    Raises:
        Exception: The manager's 'delete' error when the delete fails

    Returns:
        Response: 202 with the deleted document
    """
    manager.delete_item(stored[CmdbDAO.PUBLIC_ID_KEY])
    forget_grants()

    return DeleteSingleResponse(stored).make_response()
