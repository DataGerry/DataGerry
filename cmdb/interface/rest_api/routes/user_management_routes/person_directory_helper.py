# DATAGERRY - OpenSource Enterprise CMDB
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
The shared body of the read-only GET /persons and GET /person_groups routes

Persons and person groups are CmdbObjects of the PERSON / PERSON_GROUP SpecialTypes. The ISMS module still
reads them through these two routes, in the shape the former ``management.person`` /
``management.personGroup`` documents had (see ``cmdb.framework.person.directory.to_legacy_person``). They are
written like any other object, through /objects
"""
from typing import Any, Callable

from flask import abort, request
from werkzeug import Response

from cmdb.manager import ObjectsManager, TypesManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.user_model import CmdbUser

from cmdb.framework.person.directory import (
    get_member_ids,
    list_person_objects,
    to_legacy_person,
    to_legacy_person_group,
)
from cmdb.security.acl.builder import resolve_denied_type_ids
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.interface.rest_api.responses import GetMultiResponse, GetSingleResponse
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.rest_api.routes.routes_helper import request_wants_body
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = ['answer_person_collection', 'answer_single_person']

_LABEL_KEY: dict[str, str] = {
    SpecialType.PERSON.value: 'display_name',
    SpecialType.PERSON_GROUP.value: 'name',
}


def _legacy_documents(kind: str, request_user: CmdbUser) -> list[dict[str, Any]]:
    """
    Every person or group the caller may read, in the legacy shape, sorted by label

    Args:
        kind (str): 'PERSON' or 'PERSON_GROUP'
        request_user (CmdbUser): The CmdbUser making the request

    Returns:
        list[dict[str, Any]]: The legacy documents
    """
    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
    types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
    denied: list[int] = resolve_denied_type_ids(request_user, AccessControlPermission.READ)

    documents: list[dict[str, Any]] = list_person_objects(objects_manager, types_manager, kind, denied)
    convert: Callable[[dict[str, Any]], dict[str, Any]]

    if kind == SpecialType.PERSON.value:
        groups_of: dict[int, list[int]] = {}

        for group in list_person_objects(objects_manager, types_manager, SpecialType.PERSON_GROUP.value, denied):
            for member_id in get_member_ids(group):
                groups_of.setdefault(member_id, []).append(group['public_id'])

        def convert(document: dict[str, Any]) -> dict[str, Any]:
            return to_legacy_person(document, sorted(groups_of.get(document['public_id'], [])))
    else:
        convert = to_legacy_person_group

    label_key: str = _LABEL_KEY[kind]

    return sorted(
        (convert(document) for document in documents),
        key=lambda legacy: (str(legacy[label_key]).casefold(), legacy['public_id']),
    )


def answer_person_collection(kind: str, params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    Answers GET /persons or GET /person_groups: one page of the legacy documents

    Sorted by label; 'limit' and 'page' are honoured, a filter is not (the ISMS module reads the full list)

    Args:
        kind (str): 'PERSON' or 'PERSON_GROUP'
        params (CollectionParameters): The parsed collection parameters
        request_user (CmdbUser): The CmdbUser making the request

    Returns:
        Response: A GetMultiResponse
    """
    documents: list[dict[str, Any]] = _legacy_documents(kind, request_user)
    page: list[dict[str, Any]] = documents[params.skip:params.skip + params.limit] if params.limit else documents

    return GetMultiResponse(page, len(documents), params, request.url, request_wants_body()).make_response()


def answer_single_person(kind: str, public_id: int, request_user: CmdbUser) -> Response:
    """
    Answers GET /persons/<id> or GET /person_groups/<id> in the legacy shape

    Args:
        kind (str): 'PERSON' or 'PERSON_GROUP'
        public_id (int): public_id of the person or group object
        request_user (CmdbUser): The CmdbUser making the request

    Raises:
        HTTPException: 404 when no readable object of that kind carries the public_id

    Returns:
        Response: A GetSingleResponse
    """
    for document in _legacy_documents(kind, request_user):
        if document['public_id'] == public_id:
            return GetSingleResponse(document, body=request_wants_body()).make_response()

    abort(404, f"No {kind.lower().replace('_', ' ')} with ID:{public_id} was found!")
