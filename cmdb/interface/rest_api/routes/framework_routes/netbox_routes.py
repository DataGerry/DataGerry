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
import logging
import requests
from typing import Any
from flask import abort, request
from werkzeug import Response

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager.types_manager import TypesManager
from cmdb.models.user_model import CmdbUser
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.blueprints import APIBlueprint
from cmdb.framework.results import IterationResult
from cmdb.manager.query_builder import BuilderParameters

# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

netbox_blueprint = APIBlueprint('netbox', __name__)

# ------------------------------------------------- HELPER METHODS ------------------------------------------------- #

def _get_netbox_api_token(request_user: CmdbUser) -> str:
    """
    Get NetBox API token from the 'rack' type description
    
    Args:
        request_user (CmdbUser): User requesting the data
        
    Returns:
        str: NetBox API token
        
    Raises:
        HTTPException: If rack type is not found or has no description
    """
    try:
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
        
        # Build filter to find rack type by name
        builder_params = BuilderParameters(criteria={'name': 'rack'})
        iteration_result: IterationResult = types_manager.iterate(builder_params)
        
        if iteration_result.total == 0:
            LOGGER.error("[_get_netbox_api_token] Rack type not found in database")
            abort(404, "Rack type not found in database")
            
        rack_type = iteration_result.results[0]
        
        if not rack_type.description:
            LOGGER.error("[_get_netbox_api_token] Rack type found but has no description containing NetBox API token")
            abort(400, "Rack type found but has no description containing NetBox API token")
        
        # Log the token (masked for security)
        LOGGER.error("[_get_netbox_api_token] Retrieved NetBox API token: %s (length: %d)", 
                   rack_type.description, len(rack_type.description))
            
        return rack_type.description
        
    except Exception as err:
        LOGGER.error("[_get_netbox_api_token] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "Failed to retrieve NetBox API token from database")

def _proxy_to_netbox(request_user: CmdbUser, path: str) -> Response:
    """
    Proxy request to NetBox API
    
    Args:
        request_user (CmdbUser): User making the request
        path (str): The API path to proxy to NetBox
        
    Returns:
        Response: The response from NetBox API
    """
    try:
        # Get NetBox API token
        api_token = _get_netbox_api_token(request_user)
        
        # NetBox API base URL -  demo instance
        netbox_base_url = "https://demo.netbox.dev"
        
        # Build the full URL
        url = f"{netbox_base_url}/api/{path}"
        
        # Prepare headers for NetBox API
        headers = {
            'Authorization': f'Token {api_token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        
        # Copy relevant headers from original request
        if 'Accept' in request.headers:
            headers['Accept'] = request.headers['Accept']
        
        # Log the request details
        LOGGER.error("[_proxy_to_netbox] Sending request to NetBox API:")
        LOGGER.error("[_proxy_to_netbox]   Method: %s", request.method)
        LOGGER.error("[_proxy_to_netbox]   URL: %s", url)
        LOGGER.error("[_proxy_to_netbox]   Headers: %s", {k: '***' if k.lower() == 'authorization' else v for k, v in headers.items()})
        LOGGER.error("[_proxy_to_netbox]   Query params: %s", dict(request.args))
        
        # Make the request to NetBox API
        response = requests.request(
            method=request.method,
            url=url,
            headers=headers,
            params=request.args,
            data=request.get_data(),
            cookies=request.cookies,
            allow_redirects=False,
            timeout=30
        )
        
        # Log the response details
        LOGGER.error("[_proxy_to_netbox] Received response from NetBox API:")
        LOGGER.error("[_proxy_to_netbox]   Status Code: %s", response.status_code)
        LOGGER.error("[_proxy_to_netbox]   Response Headers: %s", dict(response.headers))
        LOGGER.error("[_proxy_to_netbox]   Response Size: %d bytes", len(response.content))
        
        # Create Flask response from NetBox response
        flask_response = Response(
            response=response.content,
            status=response.status_code,
            headers=dict(response.headers)
        )
        
        # Remove problematic headers that might cause issues
        flask_response.headers.pop('Transfer-Encoding', None)
        flask_response.headers.pop('Content-Encoding', None)
        
        return flask_response
        
    except requests.RequestException as err:
        LOGGER.error("[_proxy_to_netbox] RequestException: %s", err, exc_info=True)
        abort(502, f"Failed to connect to NetBox API: {str(err)}")
    except Exception as err:
        LOGGER.error("[_proxy_to_netbox] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occurred while proxying to NetBox API")

# ------------------------------------------------- PROXY ROUTES ------------------------------------------------- #

@netbox_blueprint.route('/rack-elevation/<int:rack_id>', methods=['GET'])
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@insert_request_user
@netbox_blueprint.protect(auth=True, right='base.framework.type.view')
def get_rack_elevation(rack_id: int, request_user: CmdbUser) -> Response:
    """
    Get rack elevation SVG from NetBox API
    
    Args:
        rack_id (int): The rack ID to fetch elevation for
        request_user (CmdbUser): User making the request
        
    Returns:
        Response: The SVG response from NetBox API
    """
    LOGGER.error("[get_rack_elevation] Fetching rack elevation for rack_id: %d", rack_id)
    path = f"dcim/racks/{rack_id}/elevation/?render=svg"
    return _proxy_to_netbox(request_user, path)

@netbox_blueprint.route('/<path:netbox_path>', methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'])
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@insert_request_user
@netbox_blueprint.protect(auth=True, right='base.framework.type.view')
def proxy_netbox_api(netbox_path: str, request_user: CmdbUser) -> Response:
    """
    Proxy route for NetBox API calls
    
    Args:
        netbox_path (str): The NetBox API path to proxy
        request_user (CmdbUser): User making the request
        
    Returns:
        Response: The response from NetBox API
    """
    LOGGER.debug("Proxying NetBox API request to path: %s", netbox_path)
    return _proxy_to_netbox(request_user, netbox_path)

@netbox_blueprint.route('/', methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'])
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@insert_request_user
@netbox_blueprint.protect(auth=True, right='base.framework.type.view')
def proxy_netbox_api_root(request_user: CmdbUser) -> Response:
    """
    Proxy route for NetBox API root calls
    
    Args:
        request_user (CmdbUser): User making the request
        
    Returns:
        Response: The response from NetBox API
    """
    LOGGER.debug("Proxying NetBox API request to root")
    return _proxy_to_netbox(request_user, "")
