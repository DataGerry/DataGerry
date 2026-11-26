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
The ``/access/field_rules`` routes: the Field Rules - create, read, list, update, delete, and the check of a rule
before it is stored

Reads ask ``base.access.view`` at the ADMIN level, writes and the check ``base.access.fieldrule.edit`` at SUPER_ADMIN.
A rule is judged on every write (``field_rule_helper.judged_rule``) - every problem in one 400
"""
from typing import Any

from werkzeug import Response

from cmdb.manager import FieldRulesManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.user_model import CmdbUser
from cmdb.models.access_model import CmdbFieldRule, FieldRuleKey
from cmdb.framework.field_rules import FieldRuleMessage
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
from cmdb.interface.rest_api.routes.routes_helper import read_id_query_param, request_wants_body
from cmdb.interface.rest_api.routes.access_routes.access_route_constants import (
    FIELD_RULE_CHECK_SCHEMA,
    FIELD_RULE_CREATE_SCHEMA,
    FIELD_RULE_QUERY_GROUP_ID,
    FIELD_RULE_SEARCHABLE_FIELDS,
    FIELD_RULE_UPDATE_SCHEMA,
    AccessRightName,
)
from cmdb.interface.rest_api.routes.access_routes.access_routes_helper import (
    create_response,
    delete_response,
    list_response,
    load_or_404,
    update_response,
)
from cmdb.interface.rest_api.routes.access_routes.field_rule_helper import (
    judged_rule,
    rule_create_payload,
    rule_reach,
    rule_update_payload,
    rules_of_group,
)
# -------------------------------------------------------------------------------------------------------------------- #

field_rules_blueprint = APIBlueprint('field_rules', __name__)

# What the 404 calls the document
LABEL: str = 'Field Rule'


def _manager(request_user: CmdbUser) -> FieldRulesManager:
    """
    The Field Rules of the caller's database

    Args:
        request_user (CmdbUser): The caller

    Returns:
        FieldRulesManager: The manager
    """
    return ManagerProvider.get_manager(ManagerType.FIELD_RULES, request_user)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

@field_rules_blueprint.route('', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.SUPER_ADMIN)
@field_rules_blueprint.protect(auth=True, right=AccessRightName.FIELD_RULE_EDIT.value)
@field_rules_blueprint.validate(FIELD_RULE_CREATE_SCHEMA)
@handle_route_errors("while creating a Field Rule")
def create_field_rule(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route storing a new Field Rule

    Args:
        data (dict[str, Any]): The validated body
        request_user (CmdbUser): The caller

    Raises:
        HTTPException: 400 for a body failing the schema or the rule's judging

    Returns:
        InsertSingleResponse: 201 with the stored rule (its ``set`` cast) and its public_id
    """
    change: ChangeContext = ChangeContext(request_user, HistoryKind.FIELD_RULE, take_comment(data))
    payload: dict[str, Any] = rule_create_payload(request_user, data)

    return create_response(_manager(request_user), CmdbFieldRule, payload,
                           FieldRuleMessage.NAME_TAKEN.value.format(name=payload[FieldRuleKey.NAME.value]), change)


@field_rules_blueprint.route('/check', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.SUPER_ADMIN)
@field_rules_blueprint.protect(auth=True, right=AccessRightName.FIELD_RULE_EDIT.value)
@field_rules_blueprint.validate(FIELD_RULE_CHECK_SCHEMA)
@handle_route_errors("while checking a Field Rule")
def check_field_rule(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route judging a Field Rule like a save, storing nothing, and answering what it reaches. The name is
    not judged; ``public_id`` names the stored rule an edit is checked as, so it does not overlap itself

    Args:
        data (dict[str, Any]): The rule as it would be stored, and the optional ``public_id``
        request_user (CmdbUser): The caller

    Raises:
        HTTPException: 400 naming every problem

    Returns:
        GetSingleResponse: ``{rule, types: [{type_id, objects}], objects}``
    """
    rule: dict[str, Any] = dict(data)
    take_comment(rule)
    own_id: int | None = rule.pop(FieldRuleKey.PUBLIC_ID.value, None)

    return GetSingleResponse(rule_reach(request_user, judged_rule(request_user, rule, own_id)),
                             body=True).make_response()

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@field_rules_blueprint.route('', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@field_rules_blueprint.protect(auth=True, right=AccessRightName.VIEW.value)
@field_rules_blueprint.parse_collection_parameters()
@handle_route_errors("while retrieving the Field Rules")
def get_field_rules(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for one page of the Field Rules - ``?filter=``, ``?search=``, ``?sort=``, paging, and
    ``?group_id=`` for the rules the user group's own changes can trigger

    Args:
        params (CollectionParameters): The collection parameters
        request_user (CmdbUser): The caller

    Raises:
        HTTPException: 400 for a group_id that is no id, 404 for an unknown user group

    Returns:
        GetMultiResponse: The page and its total
    """
    group_id: int | None = read_id_query_param(FIELD_RULE_QUERY_GROUP_ID)
    condition: dict[str, Any] | None = None

    if group_id is not None:
        condition = {FieldRuleKey.PUBLIC_ID.value: {'$in': rules_of_group(request_user, group_id)}}

    return list_response(_manager(request_user), CmdbFieldRule, params, FIELD_RULE_SEARCHABLE_FIELDS, condition)


@field_rules_blueprint.route('/<int:public_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@field_rules_blueprint.protect(auth=True, right=AccessRightName.VIEW.value)
@handle_route_errors("while retrieving the Field Rule with ID: {public_id}")
def get_field_rule(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for one Field Rule

    Args:
        public_id (int): The rule's public_id
        request_user (CmdbUser): The caller

    Raises:
        HTTPException: 404 when it does not exist

    Returns:
        GetSingleResponse: The rule as stored
    """
    stored: dict[str, Any] = load_or_404(_manager(request_user), public_id, LABEL)

    return GetSingleResponse(stored, body=request_wants_body()).make_response()

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@field_rules_blueprint.route('/<int:public_id>', methods=['PUT'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.SUPER_ADMIN)
@field_rules_blueprint.protect(auth=True, right=AccessRightName.FIELD_RULE_EDIT.value)
@field_rules_blueprint.validate(FIELD_RULE_UPDATE_SCHEMA)
@handle_route_errors("while updating the Field Rule with ID: {public_id}")
def update_field_rule(public_id: int, data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `PUT` route updating a Field Rule: what the body sends replaces the stored value, what it leaves out is kept;
    the rule as it would be stored is judged

    Args:
        public_id (int): The rule's public_id
        data (dict[str, Any]): The validated body
        request_user (CmdbUser): The caller

    Raises:
        HTTPException: 404 when it does not exist; 400 for a renaming body or a rule failing its judging

    Returns:
        UpdateSingleResponse: 202 with the rule as stored
    """
    change: ChangeContext = ChangeContext(request_user, HistoryKind.FIELD_RULE, take_comment(data))
    manager: FieldRulesManager = _manager(request_user)
    stored: dict[str, Any] = load_or_404(manager, public_id, LABEL)
    payload: dict[str, Any] = rule_update_payload(request_user, stored, data)

    return update_response(manager, CmdbFieldRule, public_id, payload,
                           FieldRuleMessage.NAME_TAKEN.value.format(name=payload[FieldRuleKey.NAME.value]), change,
                           stored)

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@field_rules_blueprint.route('/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.SUPER_ADMIN)
@field_rules_blueprint.protect(auth=True, right=AccessRightName.FIELD_RULE_EDIT.value)
@handle_route_errors("while deleting the Field Rule with ID: {public_id}")
def delete_field_rule(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route deleting a Field Rule - nothing references one

    Args:
        public_id (int): The rule's public_id
        request_user (CmdbUser): The caller

    Raises:
        HTTPException: 404 when it does not exist

    Returns:
        DeleteSingleResponse: 202 with the rule as it was stored
    """
    change: ChangeContext = ChangeContext(request_user, HistoryKind.FIELD_RULE, query_comment())
    manager: FieldRulesManager = _manager(request_user)

    return delete_response(manager, load_or_404(manager, public_id, LABEL), change)
