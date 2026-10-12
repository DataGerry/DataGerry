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
Read-only API routes for person groups

A person group is a CmdbObject of the PERSON_GROUP SpecialType and is created, edited and deleted through
/objects; its members are added and removed through /person_relations. These routes only answer the groups in
the shape the ISMS module reads (see ``person_directory_helper``)
"""
from logging import Logger, getLogger

from werkzeug import Response

from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.user_model import CmdbUser

from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import handle_route_errors, insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.rest_api.routes.user_management_routes.person_directory_helper import (
    answer_person_collection,
    answer_single_person,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

person_group_blueprint = APIBlueprint('person_group', __name__)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@person_group_blueprint.route('/', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@person_group_blueprint.protect(auth=True, right='base.user-management.personGroup.view')
@person_group_blueprint.parse_collection_parameters()
@handle_route_errors("while retrieving PersonGroups")
def get_cmdb_person_groups(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for getting the person groups

    Args:
        params (CollectionParameters): 'limit' and 'page' of the requested page
        request_user (CmdbUser): User requesting this data

    Returns:
        GetMultiResponse: The person groups, sorted by name
    """
    return answer_person_collection(SpecialType.PERSON_GROUP.value, params, request_user)


@person_group_blueprint.route('/<int:public_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@person_group_blueprint.protect(auth=True, right='base.user-management.personGroup.view')
@handle_route_errors("while retrieving the PersonGroup with ID: {public_id}")
def get_cmdb_person_group(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve a single person group

    Args:
        public_id (int): public_id of the person group object
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 404 if no person group carries the public_id

    Returns:
        GetSingleResponse: The requested person group
    """
    return answer_single_person(SpecialType.PERSON_GROUP.value, public_id, request_user)
