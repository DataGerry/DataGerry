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
The ``/access/field_classes`` routes: field classes of the access rules - create, read, list, update, delete, usage

Reads ask ``base.access.view`` at the ADMIN level, writes ``base.access.fieldclass.edit`` at SUPER_ADMIN
(the tenant's setup; the cloud API key cannot write). Nothing decides access from field classes yet: the type ACL
still does
"""
from typing import Any

from werkzeug import Response

from cmdb.manager import FieldClassesManager, ScopeRolesManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.user_model import CmdbUser
from cmdb.models.access_model import CmdbFieldClass, CmdbScopeRole, FieldClassKey
from cmdb.framework.access_rules import AccessRuleMessage, field_class_in_use
from cmdb.interface.rest_api.routes.access_routes.field_protection_helper import fields_carrying_class
from cmdb.interface.rest_api.routes.access_routes.access_payloads import (
    field_class_create_payload,
    field_class_update_payload,
)
from cmdb.models.access_model import HistoryKind
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.rest_api.routes.access_routes.access_history_helper import (
    ChangeContext,
    query_comment,
    take_comment,
)
from cmdb.interface.route_utils import handle_route_errors, insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import GetSingleResponse
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.rest_api.routes.routes_helper import abort_on_problems, request_wants_body
from cmdb.interface.rest_api.routes.access_routes.access_route_constants import (
    FIELD_CLASS_CREATE_SCHEMA,
    FIELD_CLASS_SEARCHABLE_FIELDS,
    FIELD_CLASS_UPDATE_SCHEMA,
    AccessRightName,
    AccessUsageKey,
)
from cmdb.interface.rest_api.routes.access_routes.access_routes_helper import (
    as_model_json,
    create_response,
    delete_response,
    list_response,
    load_or_404,
    update_response,
)
# -------------------------------------------------------------------------------------------------------------------- #

field_classes_blueprint = APIBlueprint('field_classes', __name__)

# What the 404 calls the document
LABEL: str = 'Field class'


def _manager(request_user: CmdbUser) -> FieldClassesManager:
    """
    The field classes of the caller's database

    Args:
        request_user (CmdbUser): The caller

    Returns:
        FieldClassesManager: The manager
    """
    return ManagerProvider.get_manager(ManagerType.FIELD_CLASSES, request_user)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

@field_classes_blueprint.route('', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.SUPER_ADMIN)
@field_classes_blueprint.protect(auth=True, right=AccessRightName.FIELD_CLASS_EDIT.value)
@field_classes_blueprint.validate(FIELD_CLASS_CREATE_SCHEMA)
@handle_route_errors("while creating a field class")
def create_field_class(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route storing a new field class

    Args:
        data (dict[str, Any]): The validated body
        request_user (CmdbUser): The caller

    Raises:
        HTTPException: 400 for a body failing the schema or the write rules

    Returns:
        InsertSingleResponse: 201 with the stored field class and its public_id
    """
    change: ChangeContext = ChangeContext(request_user, HistoryKind.FIELD_CLASS, take_comment(data))
    manager: FieldClassesManager = _manager(request_user)
    payload: dict[str, Any] = field_class_create_payload(manager, data)

    return create_response(manager, CmdbFieldClass, payload, AccessRuleMessage.FIELD_CLASS_NAME_TAKEN.value.format(
        name=payload[FieldClassKey.NAME.value]), change)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@field_classes_blueprint.route('', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@field_classes_blueprint.protect(auth=True, right=AccessRightName.VIEW.value)
@field_classes_blueprint.parse_collection_parameters()
@handle_route_errors("while retrieving the field classes")
def get_field_classes(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for one page of the field classes - ``?filter=``, ``?search=``, ``?sort=``, paging

    Args:
        params (CollectionParameters): The collection parameters
        request_user (CmdbUser): The caller

    Returns:
        GetMultiResponse: The page and its total
    """
    return list_response(_manager(request_user), CmdbFieldClass, params, FIELD_CLASS_SEARCHABLE_FIELDS)


@field_classes_blueprint.route('/<int:public_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@field_classes_blueprint.protect(auth=True, right=AccessRightName.VIEW.value)
@handle_route_errors("while retrieving the field class with ID: {public_id}")
def get_field_class(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for one field class

    Args:
        public_id (int): The field class's public_id
        request_user (CmdbUser): The caller

    Raises:
        HTTPException: 404 when it does not exist

    Returns:
        GetSingleResponse: The field class as stored
    """
    stored: dict[str, Any] = load_or_404(_manager(request_user), public_id, LABEL)

    return GetSingleResponse(stored, body=request_wants_body()).make_response()


@field_classes_blueprint.route('/<int:public_id>/usage', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@field_classes_blueprint.protect(auth=True, right=AccessRightName.VIEW.value)
@handle_route_errors("while retrieving the usage of the field class with ID: {public_id}")
def get_field_class_usage(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for what holds a field class - the scope roles granting it and the fields carrying it
    (phase 12) - so a screen can tell before a delete

    Args:
        public_id (int): The field class's public_id
        request_user (CmdbUser): The caller

    Raises:
        HTTPException: 404 when it does not exist

    Returns:
        GetSingleResponse: ``{scope_roles: [documents as stored], fields: [{source, source_id, name}]}``; empty lists
            when nothing holds it
    """
    stored: dict[str, Any] = load_or_404(_manager(request_user), public_id, LABEL)
    roles: ScopeRolesManager = ManagerProvider.get_manager(ManagerType.SCOPE_ROLES, request_user)
    granting: list[dict[str, Any]] = roles.roles_granting_class(stored[FieldClassKey.NAME.value])
    holders: list[dict[str, Any]] = as_model_json(CmdbScopeRole, granting)

    return GetSingleResponse({AccessUsageKey.SCOPE_ROLES.value: holders,
                              AccessUsageKey.FIELDS.value: fields_carrying_class(
                                  request_user, stored[FieldClassKey.NAME.value])},
                             body=request_wants_body()).make_response()

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@field_classes_blueprint.route('/<int:public_id>', methods=['PUT'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.SUPER_ADMIN)
@field_classes_blueprint.protect(auth=True, right=AccessRightName.FIELD_CLASS_EDIT.value)
@field_classes_blueprint.validate(FIELD_CLASS_UPDATE_SCHEMA)
@handle_route_errors("while updating the field class with ID: {public_id}")
def update_field_class(public_id: int, data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `PUT` route updating a field class: what the body sends replaces the stored value, what it leaves out is kept

    Args:
        public_id (int): The field class's public_id
        data (dict[str, Any]): The validated body
        request_user (CmdbUser): The caller

    Raises:
        HTTPException: 404 when it does not exist; 400 for a body failing the schema or the write rules

    Returns:
        UpdateSingleResponse: 202 with the field class as stored
    """
    change: ChangeContext = ChangeContext(request_user, HistoryKind.FIELD_CLASS, take_comment(data))
    manager: FieldClassesManager = _manager(request_user)
    stored: dict[str, Any] = load_or_404(manager, public_id, LABEL)
    payload: dict[str, Any] = field_class_update_payload(stored, data)

    taken: str = AccessRuleMessage.FIELD_CLASS_NAME_TAKEN.value.format(name=payload[FieldClassKey.NAME.value])

    return update_response(manager, CmdbFieldClass, public_id, payload, taken, change, stored)

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@field_classes_blueprint.route('/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.SUPER_ADMIN)
@field_classes_blueprint.protect(auth=True, right=AccessRightName.FIELD_CLASS_EDIT.value)
@handle_route_errors("while deleting the field class with ID: {public_id}")
def delete_field_class(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route deleting a field class

    Args:
        public_id (int): The field class's public_id
        request_user (CmdbUser): The caller

    Raises:
        HTTPException: 404 when it does not exist; 400 while a scope role grants it or a field carries it (``/usage``
            names who)

    Returns:
        DeleteSingleResponse: 202 with the field class as it was stored
    """
    change: ChangeContext = ChangeContext(request_user, HistoryKind.FIELD_CLASS, query_comment())
    manager: FieldClassesManager = _manager(request_user)
    stored: dict[str, Any] = load_or_404(manager, public_id, LABEL)
    roles: ScopeRolesManager = ManagerProvider.get_manager(ManagerType.SCOPE_ROLES, request_user)
    carrying: list[dict[str, Any]] = fields_carrying_class(request_user, stored[FieldClassKey.NAME.value])
    abort_on_problems([field_class_in_use(roles, stored), AccessRuleMessage.FIELD_CLASS_ON_FIELDS.value.format(
        name=stored[FieldClassKey.NAME.value], count=len(carrying)) if carrying else None])

    return delete_response(manager, stored, change)
