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
Implementation of all API routes for exporting CmdbTypes

Exposes `POST /export/type/` (all types) and `POST /export/type/<ids>` (a comma-separated selection).
Both serialize the types into a downloadable JSON attachment via
`exporter_helper.build_types_json_export_response`, in ascending public_id order so two exports of the
same system diff cleanly. NOTE: type export is JSON-only and lives on its own blueprint, separate from
the object export engine (tracked as discussion-backlog #39).
"""
from logging import Logger, getLogger
from flask import abort, Response
from werkzeug.exceptions import HTTPException

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import TypesManager

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.rest_api.routes.routes_helper import extract_public_ids
from cmdb.interface.rest_api.routes.exporter_routes.exporter_helper import build_types_json_export_response

from cmdb.errors.models.cmdb_type import CmdbTypeToJsonError
from cmdb.errors.manager.types_manager import TypesManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

exporter_type_blueprint = APIBlueprint('exporter_type', __name__)

# -------------------------------------------------------------------------------------------------------------------- #

@exporter_type_blueprint.route('/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@exporter_type_blueprint.protect(auth=True, right='base.export.type.*')
def export_cmdb_types(request_user: CmdbUser) -> Response:
    """
    Exports every CmdbType as a downloadable JSON file

    The whole catalogue is serialized into a formatted JSON attachment, ordered by ascending
    public_id

    NOTE this route also answers a by-ids export whose id list came out EMPTY: `/export/type/` is
    what `/export/type/<public_ids>` collapses to when the caller joins an empty selection into the
    URL (the frontend builds it that way). The two requests are byte-identical, so "export nothing"
    cannot be told apart from "export everything" here - a caller that must not export the whole
    catalogue has to refuse an empty selection before it sends the request

    Args:
        request_user (CmdbUser): The user initiating the export request

    Raises:
        HTTPException: 400 if the types could not be retrieved, 500 if a Type could not be serialized
                       or on an unexpected error

    Returns:
        Response: A Flask response object containing the exported types as a JSON attachment
    """
    try:
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
        types: list[CmdbType] = types_manager.get_all_types(direction=CmdbDAO.DAO_ASCENDING)

        return build_types_json_export_response(types)
    except HTTPException as http_err:
        raise http_err
    except TypesManagerGetError as err:
        LOGGER.error("[export_cmdb_types] TypesManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve the Types to export!")
    except CmdbTypeToJsonError as err:
        # A stored Type that cannot be serialized is a data-integrity problem, not a bad request -
        # and the whole export fails rather than silently shipping a short file
        LOGGER.error("[export_cmdb_types] CmdbTypeToJsonError: %s", err, exc_info=True)
        abort(500, "A Type could not be serialized, so the export was not produced!")
    except Exception as err:
        LOGGER.error("[export_cmdb_types] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while exporting Types!")


@exporter_type_blueprint.route('/<string:public_ids>', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@exporter_type_blueprint.protect(auth=True, right='base.export.type.*')
def export_cmdb_types_by_ids(public_ids: str, request_user: CmdbUser) -> Response:
    """
    Exports the selected CmdbTypes by their public_ids as a downloadable JSON file

    The requested types are serialized into a formatted JSON attachment, ordered by ascending
    public_id. public_ids that do not exist are skipped rather than reported, so a selection of
    unknown ids exports an empty list

    Every id must be a plain positive number (`extract_public_ids`); an EMPTY selection never reaches
    this route at all - the URL then collapses onto the whole-catalogue export, see
    `export_cmdb_types`

    Args:
        public_ids (str): A comma-separated string of CmdbType public_ids to export
        request_user (CmdbUser): The user initiating the export request

    Raises:
        HTTPException: 400 if an id is not a plain positive number or the types could not be
                       retrieved, 500 if a Type could not be serialized or on an unexpected error

    Returns:
        Response: A Flask response object containing the exported types as a JSON attachment
    """
    try:
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        requested_ids: list[int] = extract_public_ids(public_ids)
        types: list[CmdbType] = types_manager.get_types_by(
            sort='public_id',
            direction=CmdbDAO.DAO_ASCENDING,
            public_id={'$in': requested_ids},
        )

        return build_types_json_export_response(types)
    except HTTPException as http_err:
        raise http_err
    except TypesManagerGetError as err:
        LOGGER.error("[export_cmdb_types_by_ids] TypesManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve the Types to export!")
    except CmdbTypeToJsonError as err:
        # A stored Type that cannot be serialized is a data-integrity problem, not a bad request -
        # and the whole export fails rather than silently shipping a short file
        LOGGER.error("[export_cmdb_types_by_ids] CmdbTypeToJsonError: %s", err, exc_info=True)
        abort(500, "A Type could not be serialized, so the export was not produced!")
    except Exception as err:
        LOGGER.error("[export_cmdb_types_by_ids] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while exporting Types by IDs!")
