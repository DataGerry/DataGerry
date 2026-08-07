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
Implementation of the API route listing the CmdbObjects free to be mounted into a Rack

The picker behind "add an object to this rack". Its own blueprint rather than a further route on the
mount routes: nothing here writes, and the listing is a projection of the objects collection rather than
of the mounts - the mounts only contribute an exclusion list and the rack hint.

Paginated the way every other listing in this codebase is - `?filter=`, `?limit=`, `?page=`, `?sort=`,
`?order=` parsed into CollectionParameters and answered with a GetMultiResponse - so the frontend's
existing table machinery works unchanged. The assignability rules are appended as extra pipeline
stages behind the caller's own filter, so no `?filter=` can widen the result past them

**No object ACL is applied**, which is the feature-wide rule: a rack route checks rack rights and never
object rights. Whether a picker in particular should honour the object READ ACL is discussion-backlog
item #122
"""
from logging import Logger, getLogger
from typing import Any

from flask import request, abort
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager import ObjectsManager, TypesManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.rack_mounts_manager import RackMountsManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.user_model import CmdbUser
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.special_type_model.special_type_enum import SpecialType

from cmdb.errors.manager.objects_manager import ObjectsManagerIterationError
from cmdb.errors.manager.types_manager import TypesManagerGetError
from cmdb.errors.manager.rack_mounts_manager import RackMountsManagerGetError

from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import GetMultiResponse
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.rest_api.routes.routes_helper import fetch_only_active_objects

from cmdb.framework.rack.assignable_objects import (
    append_criteria_to_filter,
    build_assignable_criteria,
)

from cmdb.interface.rest_api.routes.rack_routes.rack_route_constants import RackMountParam, RackRight
from cmdb.interface.rest_api.routes.rack_routes.rack_mount_helper import (
    get_rack_or_abort,
    is_flag_enabled,
    shape_assignable_page,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

rack_assignable_blueprint = APIBlueprint('rack_assignable', __name__)

# -------------------------------------------------------------------------------------------------------------------- #

@rack_assignable_blueprint.route('/<int:rack_id>/assignable_objects/', methods=['GET', 'HEAD'])
@rack_assignable_blueprint.parse_collection_parameters()
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@rack_assignable_blueprint.protect(auth=True, right=RackRight.VIEW.value)
def get_assignable_objects(params: CollectionParameters, rack_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to list the CmdbObjects that can be mounted into a Rack

    Three rules decide it: the object's type must declare a location field (a member is mirrored into the
    location tree, and that field is what records it), an object of a RACK-marked type is never mountable
    (Racks do not nest), and an object already in THIS rack can not be added to it again. All are appended
    behind the caller's own `?filter=`, so a filter can narrow the candidates but never widen them past
    the rules

    An object held by a DIFFERENT rack is offered, with `assigned_rack_id` / `assigned_rack_name` naming
    that rack: mounting it moves it. `?only_unmounted=true` narrows the list to the objects in no rack

    Guarded by the Rack's view right: this is a question, not a change. No object ACL is applied - see
    discussion-backlog item #122

    Args:
        params (CollectionParameters): Filtering, sorting and pagination parameters
        rack_id (int): public_id of the Rack the objects would be mounted into
        request_user (CmdbUser): CmdbUser requesting this data

    Raises:
        HTTPException: 400 when the object is not a Rack or a read fails, 404 when the Rack does not
                       exist, 500 on an unexpected error

    Returns:
        GetMultiResponse: One picker row per assignable CmdbObject of the requested page
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
        rack_mounts_manager: RackMountsManager = ManagerProvider.get_manager(
            ManagerType.RACK_MOUNTS, request_user)

        get_rack_or_abort(objects_manager, types_manager, rack_id)

        # Every mounted object when the caller asked for free ones only, otherwise just this rack's own
        # members - the objects in another rack stay in the list and are offered as a move
        only_unmounted: bool = is_flag_enabled(request.args.get(RackMountParam.ONLY_UNMOUNTED.value))

        excluded_object_ids: list[int] = (
            rack_mounts_manager.get_mounted_object_ids() if only_unmounted
            else rack_mounts_manager.get_member_object_ids(rack_id)
        )

        criteria: dict[str, Any] = build_assignable_criteria(
            types_manager.get_type_ids_with_location_field(),
            types_manager.get_type_ids_of_special_type(SpecialType.RACK),
            excluded_object_ids,
        )

        params.filter = append_criteria_to_filter(params.filter, criteria)

        if fetch_only_active_objects():
            params.filter.append({'$match': {CmdbObjectKey.ACTIVE.value: {'$eq': True}}})

        builder_params = BuilderParameters(**CollectionParameters.get_builder_params(params))

        # The raw aggregation documents, not hydrated CmdbObjects: a picker row is six keys, so building
        # a model instance per candidate only to project it away would be wasted work
        object_docs, total = objects_manager.iterate_query(builder_params)

        return GetMultiResponse(
            shape_assignable_page(objects_manager, types_manager, rack_mounts_manager, object_docs),
            total=total,
            params=params,
            url=request.url,
            body=request.method == 'HEAD',
        ).make_response()
    except HTTPException as http_err:
        raise http_err
    except ObjectsManagerIterationError as err:
        LOGGER.error("[get_assignable_objects] %s", err, exc_info=True)
        abort(400, "Failed to retrieve the objects assignable to the Rack!")
    except RackMountsManagerGetError as err:
        LOGGER.error("[get_assignable_objects] %s", err, exc_info=True)
        abort(400, "Failed to retrieve the objects already mounted in a Rack!")
    except TypesManagerGetError as err:
        LOGGER.error("[get_assignable_objects] %s", err, exc_info=True)
        abort(400, "Failed to retrieve the Rack types!")
    except Exception as err:
        LOGGER.error("[get_assignable_objects] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while listing the objects assignable to the Rack!")
