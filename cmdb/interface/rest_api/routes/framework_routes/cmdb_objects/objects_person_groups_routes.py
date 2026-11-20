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
The ``/objects/<public_id>/person_groups`` routes - a person's groups, read and changed from the person's side

Membership is stored on the groups (``objects_person_groups_helper``): the read answers the readable groups holding the
person, the change writes the groups it joins and leaves - all of them or none. ADMIN level, the object rights, no
licence gate: persons are needed in every edition
"""
from http import HTTPStatus
from typing import Any

from flask import abort
from werkzeug import Response

from cmdb.models.user_model import CmdbUser
from cmdb.models.right_model.right_constants import ObjectRightName
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import (
    handle_manager_errors,
    handle_route_errors,
    insert_request_user,
    verify_api_access,
)
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import DefaultResponse
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_constants import (
    PERSON_GROUPS_CHANGE_SCHEMA,
    PersonGroupsChangeKey,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_person_groups_helper import (
    change_person_groups,
    read_marked_object,
    read_person_groups,
)
from cmdb.interface.rest_api.routes.user_management_routes.person_constants import (
    PERSON_LABEL,
    RECORD_ACCESS_DENIED_MESSAGE,
    RECORD_READ_FAILED_MESSAGE,
    RECORD_UPDATE_FAILED_MESSAGE,
)
from cmdb.errors.manager import BaseManagerGetError, BaseManagerIterationError
from cmdb.errors.manager.objects_manager import ObjectsManagerGetError, ObjectsManagerUpdateError
from cmdb.errors.security import AccessDeniedError
# -------------------------------------------------------------------------------------------------------------------- #

object_person_groups_blueprint = APIBlueprint('object_person_groups', __name__)

# The manager failures of both routes, by what was going on
_READ_FAILURES: dict[type[Exception], str] = {
    ObjectsManagerGetError: RECORD_READ_FAILED_MESSAGE.format(label=PERSON_LABEL),
    BaseManagerGetError: RECORD_READ_FAILED_MESSAGE.format(label=PERSON_LABEL),
    BaseManagerIterationError: RECORD_READ_FAILED_MESSAGE.format(label=PERSON_LABEL),
}
_ACCESS_DENIED: str = RECORD_ACCESS_DENIED_MESSAGE.format(label=PERSON_LABEL)


@object_person_groups_blueprint.route('/<int:public_id>/person_groups', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@object_person_groups_blueprint.protect(auth=True, right=ObjectRightName.VIEW.value)
@handle_route_errors("while reading the PersonGroups of the Person with ID: {public_id}")
@handle_manager_errors(_READ_FAILURES)
def get_person_groups(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET` route answering the groups a person is in - the groups the caller may READ whose members hold it

    Requires the ``base.framework.object.view`` right, ApiLevel.ADMIN and READ on the person's Type

    Args:
        public_id (int): The person's object id
        request_user (CmdbUser): The CmdbUser making the request

    Raises:
        HTTPException: 404 for an id naming no person, 403 for one the caller may not read

    Returns:
        DefaultResponse: The groups as person selections ``[{object_id, type_id, type_label, kind, label, active,
            system_ref}]``, ascending by id
    """
    try:
        read_marked_object(SpecialType.PERSON, public_id, request_user)

        return DefaultResponse(read_person_groups(public_id, request_user)).make_response()
    except AccessDeniedError:
        abort(HTTPStatus.FORBIDDEN, _ACCESS_DENIED)


@object_person_groups_blueprint.route('/<int:public_id>/person_groups', methods=['PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@object_person_groups_blueprint.protect(auth=True, right=ObjectRightName.EDIT.value)
@object_person_groups_blueprint.validate(PERSON_GROUPS_CHANGE_SCHEMA)
@handle_route_errors("while changing the PersonGroups of the Person with ID: {public_id}")
@handle_manager_errors({**_READ_FAILURES, ObjectsManagerUpdateError: RECORD_UPDATE_FAILED_MESSAGE.format(
    label=PERSON_LABEL, public_id='{public_id}')})
def patch_person_groups(public_id: int, data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `PATCH` route letting a person join and leave groups - ``{add: [group ids], remove: [group ids]}``

    Requires the ``base.framework.object.edit`` right, ApiLevel.ADMIN, READ on the person's Type and READ and UPDATE
    on each named group's Type. The groups are written, not the person: each changed group's ``members`` through the
    object update - its rules, the user sync's lock, its edit log and webhook - all of them or none

    Args:
        public_id (int): The person's object id
        data (dict[str, Any]): The groups to join and to leave
        request_user (CmdbUser): The CmdbUser making the request

    Raises:
        HTTPException: 404 for an id naming no person; 400 for a group both added and removed or naming no group
            object, 403 for a person or group the caller may not read or a group it may not update; what the object
            update answers for a group

    Returns:
        DefaultResponse: The person's groups afterwards, as the `GET` answers them
    """
    try:
        read_marked_object(SpecialType.PERSON, public_id, request_user)
        change_person_groups(public_id, set(data.get(PersonGroupsChangeKey.ADD.value) or []),
                             set(data.get(PersonGroupsChangeKey.REMOVE.value) or []), request_user)

        return DefaultResponse(read_person_groups(public_id, request_user)).make_response()
    except AccessDeniedError:
        abort(HTTPStatus.FORBIDDEN, _ACCESS_DENIED)
