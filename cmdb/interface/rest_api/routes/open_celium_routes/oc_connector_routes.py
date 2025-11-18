# DataGerry - OpenSource Enterprise CMDB
# Copyright (C) 2025 becon GmbH
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
All API routes for OpenCelium Connectors
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort, request, current_app
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager import OcConnectorManager, DgServicePortalManager

from cmdb.open_celium.oc_constants import OC_INTERNAL_CONNECTOR_NAME
from cmdb.open_celium import map_oc_name, unmap_oc_name

from cmdb.models.user_model import CmdbUser
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import insert_request_user, verify_api_access, handle_oc_errors
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import DefaultResponse

from cmdb.errors.open_celium.connector import (
    OcConnectorCreateError,
    OcConnectorGetError,
    OcConnectorUpdateError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

oc_connectors_blueprint = APIBlueprint('oc_connectors', __name__)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

@oc_connectors_blueprint.route('/connectors', methods=['POST'])
@handle_oc_errors("creating an OpenCelium Connector!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@oc_connectors_blueprint.protect(auth=True, right='base.openCelium.connector.add')
def create_oc_connector(request_user: CmdbUser) -> Response:
    """
    POST route to create an OcConnector in OpenCelium

    Args:
        params (dict[str, Any]): the data of the new OcConnector
        request_user (CmdbUser): User requesting this data

    Returns:
        dict[str, Any]: The created OcConnector
    """
    try:
        oc_connector_manager: OcConnectorManager = OcConnectorManager()
        dg_sp_manager: DgServicePortalManager = DgServicePortalManager()

        params: dict[str, Any] = request.json



        if current_app.cloud_mode and not current_app.local_mode:
            if params['title'] == map_oc_name(request_user.database, OC_INTERNAL_CONNECTOR_NAME):
                abort(400,
                      f"The title:'{OC_INTERNAL_CONNECTOR_NAME}' is reserved for the interal DataGerry connector!"
                     )
            else:
                # Map name of connector
                params['title'] = map_oc_name(request_user.database, params['title'])
        else:
            if params['title'] == OC_INTERNAL_CONNECTOR_NAME:
                abort(400,
                      f"The title:'{OC_INTERNAL_CONNECTOR_NAME}' is reserved for the interal DataGerry connector!"
                     )

        created_oc_connector: dict[str, Any] = oc_connector_manager.create_connector(params)

        # Save the new connectorId in DG ServicePortal
        if current_app.cloud_mode and not current_app.local_mode:
            dg_sp_manager.save_connector_id(
                created_oc_connector['connectorId'],
                request_user.email,
                request_user.database
            )

            created_oc_connector['title'] = unmap_oc_name(created_oc_connector['title'])

        return DefaultResponse(created_oc_connector).make_response()
    except HTTPException as http_err:
        raise http_err
    except OcConnectorCreateError as err:
        LOGGER.error("[create_oc_connector] OcConnectorCreateError: %s", err, exc_info=True)
        abort(500, "Failed to create the OpenCelium Connector!")


@oc_connectors_blueprint.route('/connectors/check', methods=['POST'])
@handle_oc_errors("checking the credentials of the OpenCelium Connector!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@oc_connectors_blueprint.protect(auth=True, right='base.openCelium.connector.add')
def check_oc_connector(request_user: CmdbUser) -> Response:
    """
    POST route validate credentials of the Invoker of the Connector

    Args:
        params (dict[str, Any]): the data of the new OcConnector
        request_user (CmdbUser): User requesting this data

    Returns:
        dict[str, Any]: The created OcConnector
    """
    oc_connector_manager: OcConnectorManager = OcConnectorManager()

    params: dict[str, Any] = request.json

    check_is_success: bool = oc_connector_manager.check_connector(params)

    return DefaultResponse(check_is_success).make_response()


@oc_connectors_blueprint.route('/connectors/with_pw', methods=['POST'])
@handle_oc_errors("checking the master password!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@oc_connectors_blueprint.protect(auth=True, right='base.openCelium.connector.view')
def check_oc_connector_master_pw(request_user: CmdbUser) -> Response:
    """
    **POST** route to check the master password for connectors. If connectorId is provided
    then it returns the connector with credentials

    Args:
        request_user (CmdbUser): User requesting this data

    Returns:
        dict[str, Any] | bool: True if password correct or the Connector with credentials

    Example params:
        {
            "password": password,
            "connectorId": 123 (Optional)
        }
    """
    try:
        oc_connector_manager: OcConnectorManager = OcConnectorManager()
        dg_sp_manager: DgServicePortalManager = DgServicePortalManager()

        params: dict[str, Any] = request.json

        # LOGGER.debug(f"master_pw: {params['password']}")
        pw_valid: bool = False

        if current_app.cloud_mode and not current_app.local_mode:
            pw_valid = dg_sp_manager.check_master_pw(params['password'], request_user.email, request_user.database)
        else:
            pw_valid = oc_connector_manager.check_master_pw(params['password'])

        if not pw_valid:
            abort(403, "Invalid master password!")

        result: dict[str, Any] | bool = True

        if params.get('connectorId'):
            if current_app.cloud_mode and not current_app.local_mode:
                is_valid_connector: bool = dg_sp_manager.check_connector_in_sub(
                    params['connectorId'],
                    request_user.email,
                    request_user.database
                )

                if not is_valid_connector:
                    abort(400, f"The target Connector with ID:{params['connectorId']} was not found!")

                result: dict[str, Any] = oc_connector_manager.get_connector(
                                                params['connectorId'],
                                                oc_connector_manager.get_master_pw()
                                            )

                if result:
                    result['title'] = unmap_oc_name(result['title'])
            else:
                result: dict[str, Any] = oc_connector_manager.get_connector(
                                                                params['connectorId'],
                                                                params['password']
                                                            )

        # LOGGER.debug(f"master pw result: {result}")

        return DefaultResponse(result).make_response()
    except HTTPException as http_err:
        raise http_err
    except OcConnectorGetError as err:
        LOGGER.error("[check_oc_connector_master_pw] %s: %s.", type(err).__name__, err, exc_info=True)
        abort(500, "Failed to check the master password!")

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@oc_connectors_blueprint.route('/connectors/<int:connector_id>', methods=['GET', 'HEAD'])
@handle_oc_errors("retrieving the OpenCelium Connector!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@oc_connectors_blueprint.protect(auth=True, right='base.openCelium.connector.view')
def get_oc_connector(request_user: CmdbUser, connector_id: int) -> Response:
    """
    GET/HEAD route to retrive an OcConnector with the given connector_id

    Args:
        request_user (CmdbUser): User requesting this data
        connector_id (int): connectorId of the OcConnector

    Returns:
        dict[str, Any]: The OcConnector from OpenCelium
    """
    try:
        oc_connector_manager: OcConnectorManager = OcConnectorManager()
        dg_sp_manager: DgServicePortalManager = DgServicePortalManager()

        if current_app.cloud_mode and not current_app.local_mode:
            is_valid_connector: bool = dg_sp_manager.check_connector_in_sub(
                connector_id,
                request_user.email,
                request_user.database
            )

            if not is_valid_connector:
                abort(400, f"The target Connector with ID:{connector_id} was not found!")

        connector: dict[str, Any] = oc_connector_manager.get_connector(connector_id)

        # LOGGER.debug(f"connector: {connector}")

        if current_app.cloud_mode and not current_app.local_mode:
            connector['title'] = unmap_oc_name(connector['title'])

        return DefaultResponse(connector).make_response()
    except HTTPException as http_err:
        raise http_err
    except OcConnectorGetError as err:
        LOGGER.error("[get_oc_connector] OcConnectorGetError: %s.", err, exc_info=True)
        abort(500, f"Failed to retrieve OpenCelium Connector with ID:{connector_id}!")


@oc_connectors_blueprint.route('/connectors', methods=['GET', 'HEAD'])
@handle_oc_errors("retrieving OpenCelium Connectors!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@oc_connectors_blueprint.protect(auth=True, right='base.openCelium.connector.view')
def get_all_oc_connectors(request_user: CmdbUser) -> Response:
    """
    **GET**/**HEAD** route for getting multiple OcConnectors

    Args:
        request_user (CmdbUser): User requesting this data

    Returns:
        list[dict[str, Any]]: All OcConnectors from OpenCelium
    """
    try:
        oc_connector_manager: OcConnectorManager = OcConnectorManager()
        dg_sp_manager: DgServicePortalManager = DgServicePortalManager()

        connectors: list[dict[str, Any]] = None

        if current_app.cloud_mode and not current_app.local_mode:
            connector_ids: list[int] = dg_sp_manager.get_connector_ids(request_user.email, request_user.database)
            connectors = oc_connector_manager.get_connectors_by_ids(connector_ids)

            for a_connector in connectors:
                a_connector['title'] = unmap_oc_name(a_connector['title'])
        else:
            connectors: list[dict[str, Any]] = oc_connector_manager.get_all_connectors()

        # LOGGER.debug(f"all connectors: {connectors}")

        return DefaultResponse(connectors).make_response()
    except OcConnectorGetError as err:
        LOGGER.error("[get_all_oc_connectors] %s: %s.", type(err).__name__, err, exc_info=True)
        abort(500, "Failed to retrieve OpenCelium Connectors!")


@oc_connectors_blueprint.route('/connectors/exists/<string:title>', methods=['GET', 'HEAD'])
@handle_oc_errors("retrieving the OpenCelium Connector!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@oc_connectors_blueprint.protect(auth=True, right='base.openCelium.connector.view')
def check_oc_connector_exists(request_user: CmdbUser, title: str) -> Response:
    """
    GET/HEAD route to check if a connector with the given title exists

    Args:
        request_user (CmdbUser): User requesting this data
        title (str): title of the connector

    Returns:
        bool: True if the connector exists, else False
    """
    try:
        oc_connector_manager: OcConnectorManager = OcConnectorManager()

        if current_app.cloud_mode and not current_app.local_mode:
            title = map_oc_name(request_user.database, title)

        connector_exists: bool = oc_connector_manager.connector_exists(title)

        return DefaultResponse(connector_exists).make_response()
    except OcConnectorGetError as err:
        LOGGER.error("[get_oc_connector] OcConnectorGetError: %s.", err, exc_info=True)
        abort(500, f"Failed to check if Connector with title:{title} exists!")

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@oc_connectors_blueprint.route('/connectors/<int:connector_id>', methods=['PUT'])
@handle_oc_errors("updating an OpenCelium Connector!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@oc_connectors_blueprint.protect(auth=True, right='base.openCelium.connector.edit')
def update_oc_connector(request_user: CmdbUser, connector_id: int) -> Response:
    """
    **PUT** route to update an OcConnector

    Args:
        params (dict[str, Any]): new data of the OcConnector
        request_user (CmdbUser): User requesting this data
        connector_id (int): the connectorId of the OcConnector

    Returns:
        dict[str, Any]: The updated OcConnector
    """
    try:
        oc_connector_manager: OcConnectorManager = OcConnectorManager()
        dg_sp_manager: DgServicePortalManager = DgServicePortalManager()

        if current_app.cloud_mode and not current_app.local_mode:
            is_valid_connector: bool = dg_sp_manager.check_connector_in_sub(
                connector_id,
                request_user.email,
                request_user.database
            )

            if not is_valid_connector:
                abort(400, f"The target Connection with ID:{connector_id} was not found!")

        params: dict[str, Any] = request.json

        if current_app.cloud_mode and not current_app.local_mode:
            params['title'] = map_oc_name(request_user.database, params['title'])

        updated_oc_connector: dict[str, Any] = oc_connector_manager.update_connector(params, connector_id)

        if current_app.cloud_mode and not current_app.local_mode:
            updated_oc_connector['title'] = unmap_oc_name(updated_oc_connector['title'])

        return DefaultResponse(updated_oc_connector).make_response()
    except HTTPException as http_err:
        raise http_err
    except OcConnectorUpdateError as err:
        LOGGER.error("[update_oc_connector] %s: %s", type(err), err, exc_info=True)
        abort(400, f"Failed to update the OpenCelium Connector with ID: {connector_id}!")

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@oc_connectors_blueprint.route('/connectors/<int:connector_id>', methods=['DELETE'])
@handle_oc_errors("deleting the OpenCelium Connector!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@oc_connectors_blueprint.protect(auth=True, right='base.openCelium.connector.delete')
def delete_oc_connector(request_user: CmdbUser, connector_id: int) -> Response:
    """
    HTTP `DELETE` route to delete an OcConnector

    Args:
        request_user (CmdbUser): User requesting this data
        connector_id (int): the connectorId of the OcConnector

    Returns:
        bool: True if deletion was a success else False
    """
    try:
        oc_connector_manager: OcConnectorManager = OcConnectorManager()
        dg_sp_manager: DgServicePortalManager = DgServicePortalManager()

        if current_app.cloud_mode and not current_app.local_mode:
            is_valid_connector: bool = dg_sp_manager.check_connector_in_sub(
                connector_id,
                request_user.email,
                request_user.database
            )

            if not is_valid_connector:
                abort(400, f"The target Connection with ID:{connector_id} was not found!")

        deleted_oc_connector: bool = oc_connector_manager.delete_connector(connector_id)

        return DefaultResponse(deleted_oc_connector).make_response()
    except HTTPException as http_err:
        raise http_err
    except OcConnectorUpdateError as err:
        LOGGER.error("[delete_oc_connector] %s: %s", type(err), err, exc_info=True)
        abort(400, f"Failed to delete the OpenCelium Connector with ID: {connector_id}!")

# -------------------------------------------------- INTERNAL ROUTES ------------------------------------------------- #

@oc_connectors_blueprint.route('/connectors/internal', methods=['POST'])
@handle_oc_errors("creating the internal DG Connector!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@oc_connectors_blueprint.protect(auth=True, right='base.openCelium.connector.add')
def create_oc_internal_connector(request_user: CmdbUser) -> Response:
    """
    POST route to create an OcConnector in OpenCelium

    Args:
        request_user (CmdbUser): User requesting this data

    Returns:
        dict[str, Any]: The created OcConnector
    """
    try:
        oc_connector_manager: OcConnectorManager = OcConnectorManager()
        dg_sp_manager: DgServicePortalManager = DgServicePortalManager()

        params: dict[str, Any] = request.json

        if current_app.cloud_mode and not current_app.local_mode:
            params['title'] = map_oc_name(request_user.database, OC_INTERNAL_CONNECTOR_NAME)
        else:
            params['title'] = OC_INTERNAL_CONNECTOR_NAME

        created_oc_connector: dict[str, Any] = oc_connector_manager.create_connector(params)

        if current_app.cloud_mode and not current_app.local_mode:
            dg_sp_manager.save_connector_id(
                created_oc_connector['connectorId'],
                request_user.email,
                request_user.database
            )

            created_oc_connector['title'] = unmap_oc_name(created_oc_connector['title'])

        return DefaultResponse(created_oc_connector).make_response()
    except OcConnectorCreateError as err:
        LOGGER.error("[create_oc_internal_connector] OcConnectorCreateError: %s", err, exc_info=True)
        abort(400, "Failed to create the internal DG Connector!")


@oc_connectors_blueprint.route('/connectors/internal', methods=['PUT'])
@handle_oc_errors("updating the internal Connector!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@oc_connectors_blueprint.protect(auth=True, right='base.openCelium.connector.edit')
def update_internal_oc_connector(request_user: CmdbUser) -> Response:
    """
    **PUT** route to update an OcConnector

    Args:
        request_user (CmdbUser): User requesting this data

    Returns:
        dict[str, Any]: The updated OcConnector
    """
    try:
        oc_connector_manager: OcConnectorManager = OcConnectorManager()

        params: dict[str, Any] = request.json

        if current_app.cloud_mode and not current_app.local_mode:
            params['title'] = map_oc_name(request_user.database, OC_INTERNAL_CONNECTOR_NAME)
        else:
            params['title'] = OC_INTERNAL_CONNECTOR_NAME

        internal_connector = oc_connector_manager.get_connector_by_name(params['title'])

        if not internal_connector:
            abort(400, "No internal DataGerry Connector created!")

        updated_oc_connector: dict[str, Any] = oc_connector_manager.update_connector(
                                                    params,
                                                    internal_connector['connectorId']
                                               )

        if current_app.cloud_mode and not current_app.local_mode:
            updated_oc_connector['title'] = unmap_oc_name(updated_oc_connector['title'])

        return DefaultResponse(updated_oc_connector).make_response()
    except HTTPException as http_err:
        raise http_err
    except OcConnectorUpdateError as err:
        LOGGER.error("[update_internal_oc_connector] %s: %s", type(err), err, exc_info=True)
        abort(400, "Failed to update the internal Connector!")


@oc_connectors_blueprint.route('/connectors/internal/get', methods=['POST'])
@handle_oc_errors("retrieving the internal Connector!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@oc_connectors_blueprint.protect(auth=True, right='base.openCelium.connector.view')
def get_internal_oc_connector(request_user: CmdbUser) -> Response:
    """
    GET/HEAD route to retrive the internal OC Connector

    Args:
        request_user (CmdbUser): User requesting this data

    Returns:
        dict[str, Any]: The OcConnector from OpenCelium
    """
    try:
        oc_connector_manager: OcConnectorManager = OcConnectorManager()
        dg_sp_manager: DgServicePortalManager = DgServicePortalManager()

        params: dict[str, Any] = request.json

        password: str = params.get('password', None)

        target_name: str = None

        if current_app.cloud_mode and not current_app.local_mode:
            target_name = map_oc_name(request_user.database, OC_INTERNAL_CONNECTOR_NAME)
        else:
            target_name = OC_INTERNAL_CONNECTOR_NAME

        internal_connector = oc_connector_manager.get_connector_by_name(target_name)

        if not internal_connector:
            return DefaultResponse({}).make_response()

        if password:
            if current_app.cloud_mode and not current_app.local_mode:
                is_valid_connector: bool = dg_sp_manager.check_connector_in_sub(
                    internal_connector['connectorId'],
                    request_user.email,
                    request_user.database
                )

                if not is_valid_connector:
                    abort(400, f"The target Connector with ID:{internal_connector['connectorId']} was not found!")

            internal_connector: dict[str, Any] = oc_connector_manager.get_connector(
                                                        internal_connector['connectorId'],
                                                        password
                                                )

        if current_app.cloud_mode and not current_app.local_mode:
            internal_connector['title'] = unmap_oc_name(internal_connector['title'])

        return DefaultResponse(internal_connector).make_response()
    except HTTPException as http_err:
        raise http_err
    except OcConnectorGetError as err:
        LOGGER.error("[get_internal_oc_connector] OcConnectorGetError: %s.", err, exc_info=True)
        abort(500, "Failed to retrieve the internal connector!")
