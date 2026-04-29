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
Implementation of all API routes for Object Imports
"""
import json
from logging import Logger, getLogger
from flask import request, abort
from werkzeug import Response
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename
from werkzeug.exceptions import HTTPException

from cmdb.database.database_utils import default
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import (
    ObjectsManager,
    TypesManager,
    LogsManager,
)

from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model.cmdb_type import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.log_model.cmdb_object_log import CmdbObjectLog
from cmdb.framework.rendering.cmdb_multi_render import CmdbMultiRender
from cmdb.framework.importer.configs.object_importer_config import ObjectImporterConfig
from cmdb.framework.importer.parser.base_object_parser import BaseObjectParser
from cmdb.framework.importer.responses.importer_object_response import ImporterObjectResponse
from cmdb.framework.importer.helper.importer_helper import (
    load_parser_class,
    load_importer_class,
    load_importer_config_class,
    __OBJECT_IMPORTER__,
    __OBJECT_PARSER__,
    __OBJECT_IMPORTER_CONFIG__,
)
from cmdb.interface.rest_api.routes.importer_routes.import_routes import importer_blueprint
from cmdb.interface.rest_api.responses import DefaultResponse
from cmdb.interface.route_utils import (
    insert_request_user,
    right_required,
    verify_api_access,
)
from cmdb.interface.blueprints import NestedBlueprint
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.routes.importer_routes.importer_route_utils import (
    get_file_in_request,
    get_element_from_data_request,
    generate_parsed_output,
    verify_import_access,
)

from cmdb.errors.manager import BaseManagerInsertError
from cmdb.errors.security import AccessDeniedError
from cmdb.errors.manager.objects_manager import ObjectsManagerGetError
from cmdb.errors.render import InstanceRenderError
from cmdb.errors.importer import ImportRuntimeError, ImporterLoadError, ParserLoadError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

importer_object_blueprint = NestedBlueprint(importer_blueprint, url_prefix='/object')

# -------------------------------------------------------------------------------------------------------------------- #
#TODO: ROUTE-FIX (Remove one route)
@importer_object_blueprint.route('/importer/', methods=['GET'])
@importer_object_blueprint.route('/importer', methods=['GET'])
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def get_object_importer():
    """
    Retrieve a list of available object importers with their metadata.

    This endpoint provides information about each registered object importer, including
    the file type it supports, the content type it expects, and the associated icon.
    This metadata can be used by clients to render UI elements for importing objects.

    Returns:
        Response: A Flask Response object containing a JSON list of importer metadata
                  Each item includes:
                    - name (str): The file type handled by the importer
                    - content_type (str): The MIME type expected by the importer
                    - icon (str): A string identifier for an icon representing the importer
    """
    try:
        importer_response = []

        for importer in __OBJECT_IMPORTER__:
            importer_response.append({
                'name': __OBJECT_IMPORTER__.get(importer).FILE_TYPE,
                'content_type': __OBJECT_IMPORTER__.get(importer).CONTENT_TYPE,
                'icon': __OBJECT_IMPORTER__.get(importer).ICON
            })

        return DefaultResponse(importer_response).make_response()
    except Exception as err:
        LOGGER.error("[get_object_importer] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while retrieving the ObjectImporter!")


#TODO: ROUTE-FIX (Remove one route)
@importer_object_blueprint.route('/importer/config/<string:importer_type>/', methods=['GET'])
@importer_object_blueprint.route('/importer/config<string:importer_type>', methods=['GET'])
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def get_default_object_importer_config(importer_type: str):
    """
    Retrieve the default configuration for a specific object importer type.

    This endpoint returns configuration metadata for a given importer type,
    specifically whether the importer supports manual mapping of fields.

    Args:
        importer_type (str): The identifier for the importer type (e.g., 'csv', 'json')

    Returns:
        Response: A Flask Response object containing a JSON with:
            - manually_mapping (bool): Indicates if the importer allows manual field mapping
    """
    try:
        try:
            importer: ObjectImporterConfig = __OBJECT_IMPORTER_CONFIG__[importer_type]
        except IndexError:
            abort(404, f"ObjectImporter config with Type: {importer_type} not found!")

        return DefaultResponse({'manually_mapping': importer.MANUALLY_MAPPING}).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[get_default_object_importer_config] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while retrieving the ObjectImporter config!")


#TODO: ROUTE-FIX (Remove one route)
@importer_object_blueprint.route('/parser/', methods=['GET'])
@importer_object_blueprint.route('/parser', methods=['GET'])
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def get_object_parser():
    """
    Retrieve a list of available object parsers.

    This endpoint returns a list of all registered object parsers. These parsers are used
    to interpret or convert raw data into structured objects based on supported formats.

    Returns:
        Response: A Flask Response object containing a JSON array of parser identifiers.
                  Each item in the list represents a supported object parser.
    """
    try:
        parser = list(__OBJECT_PARSER__)

        return DefaultResponse(parser).make_response()
    except Exception as err:
        LOGGER.error("[get_object_parser] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while retrieving the ObjectParsers!")


#TODO: ROUTE-FIX (Remove one route)
@importer_object_blueprint.route('/parser/default/<string:parser_type>', methods=['GET'])
@importer_object_blueprint.route('/parser/default/<string:parser_type>/', methods=['GET'])
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def get_default_object_parser_config(parser_type: str):
    """
    Retrieve the default configuration for a specific object parser.

    This endpoint provides the default configuration settings for a given parser type.
    These settings define how the parser behaves when processing imported data.

    Args:
        parser_type (str): The identifier for the object parser (e.g., 'csv', 'xml', 'json')

    Returns:
        Response: A Flask Response object containing a JSON object with the parser's
                  default configuration parameters
    """
    try:
        try:
            parser: BaseObjectParser = __OBJECT_PARSER__[parser_type]
        except IndexError:
            abort(404, f"ObjectParser config with Type: {parser_type} not found!")

        return DefaultResponse(parser.DEFAULT_CONFIG).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[get_default_object_parser_config] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while retrieving the default ObjectParser config!")


#TODO: ROUTE-FIX (Remove one route)
@importer_object_blueprint.route('/parse/', methods=['POST'])
@importer_object_blueprint.route('/parse', methods=['POST'])
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def parse_objects():
    """
    Parse uploaded object data using the specified parser configuration.

    This endpoint receives a file upload along with parser configuration and file format
    to generate a structured parsed output. It is typically used in data import workflows
    where input files (e.g., CSV, JSON) are converted into objects that can be reviewed or stored.

    Expected Multipart Form Data:
        - file (FileStorage): The file to be parsed.
        - parser_config (JSON str or object): Configuration options for the parser.
        - file_format (str): Identifier for the file format (e.g., 'csv', 'json').

    Returns:
        Response: A Flask Response object containing a JSON list of parsed objects.
    """
    try:
        try:
            #TODO: REFACTOR-FIX (get_file_in_request-function)
            request_file: FileStorage = get_file_in_request('file', request.files)
        except Exception as err:
            LOGGER.error("[parse_objects] Exception: %s, Type: %s", err, type(err))
            abort(500, "No file in request!")

        # Load parser config
        try:
            parser_config: dict = get_element_from_data_request('parser_config', request) or {}
        except Exception as err:
            LOGGER.error("[parse_objects] Exception: %s, Type: %s", err, type(err))
            abort(500, "No parser config!")
        # Load file format
        file_format = request.form.get('file_format', None)

        if not file_format:
            abort(500, "No file format!")

        try:
            parsed_output = generate_parsed_output(request_file, file_format, parser_config).output()
        except Exception as err:
            LOGGER.error("[parse_objects] Error: %s, Type: %s", err, type(err), exc_info=True)
            abort(500, "Could not generate parsed output!")

        return DefaultResponse(parsed_output).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[parse_objects] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while parsing Objects!")


#TODO: REFACTOR-FIX (reduce complexity)
@importer_object_blueprint.route('/', methods=['POST'])
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@insert_request_user
@right_required('base.import.object.*')
def import_objects(request_user: CmdbUser) -> Response:
    """
    Handle the full import of objects into the CMDB system using an uploaded file.

    This endpoint manages the complete lifecycle of object import:
    - Upload and validate an import file
    - Parse the file based on provided parser configuration
    - Load appropriate parser and importer classes dynamically
    - Perform object imports with access control
    - Log all successfully imported objects

    Args:
        request_user (CmdbUser): The authenticated user making the import request. This user is
                                 also used for permission verification and logging purposes

    Expected Multipart Form Data:
        - file (FileStorage): The import file to be uploaded and processed
        - file_format (str): Format of the uploaded file (e.g., 'csv', 'json')
        - parser_config (JSON): Configuration used to parse the file's contents
        - importer_config (JSON): Configuration used to import the parsed data into the system,
                                  must include a valid 'type_id'

    Returns:
        Response: A `DefaultResponse` containing the results of the import operation,
                  including success/failure
    """
    try:
        # Check if file exists
        if not request.files:
            LOGGER.error("[import_objects] No import file!")
            abort(400, 'No import file was provided!')

        request_file: FileStorage = get_file_in_request('file', request.files)

        filename = secure_filename(request_file.filename)
        working_file = f'/tmp/{filename}'
        request_file.save(working_file)

        # Load file format
        file_format = request.form.get('file_format', None)

        # Load parser config
        parser_config: dict = get_element_from_data_request('parser_config', request) or {}
        if parser_config == {}:
            LOGGER.info('No parser config was provided - using default parser config')

        # Check for importer config
        importer_config_request: dict = get_element_from_data_request('importer_config', request) or None
        if not importer_config_request:
            LOGGER.error("[import_objects] No import config was provided!")
            abort(400, 'No import config was provided!')

        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        logs_manager: LogsManager = ManagerProvider.get_manager(ManagerType.LOGS, request_user)

        # Check if type exists
        try:
            type_ = types_manager.get_type(importer_config_request.get('type_id'))

            if type_:
                type_ = CmdbType.from_data(type_)

                if not type_.active:
                    raise AccessDeniedError(f'Objects cannot be created because type `{type_.name}` is deactivated.')
                verify_import_access(request_user, type_, types_manager)
        except AccessDeniedError:
            LOGGER.error("[import_objects] No import config was provided!")
            abort(403, "Access denied for importing objects!")
        except Exception as error:
            LOGGER.error("[import_objects] Exception: %s. Type: %s", error, type(error), exc_info=True)
            abort(400, "Could not import objects!")

        # Load parser
        try:
            parser_class = load_parser_class('object', file_format)
        except ParserLoadError as err:
            LOGGER.error("[import_objects] ParserLoadError: %s", err, exc_info=True)
            abort(500, "Failed to load ObjectParser class!")

        parser = parser_class(parser_config)

        # Load importer config
        try:
            importer_config_class = load_importer_config_class('object', file_format)
        except ImporterLoadError as err:
            LOGGER.error("[import_objects] ImporterLoadError: %s", err, exc_info=True)
            abort(500, "Failed to load ObjectImprter config!")

        importer_config = importer_config_class(**importer_config_request)

        # Load importer
        try:
            importer_class = load_importer_class('object', file_format)
        except ImporterLoadError as err:
            LOGGER.error("[import_objects] ImporterLoadError: %s", err, exc_info=True)
            abort(500, f"Failed to load ObjectImporter for file format: {file_format}!")

        importer = importer_class(working_file, importer_config, parser, objects_manager, request_user)

        try:
            import_response: ImporterObjectResponse = importer.start_import()
        except ImportRuntimeError as err:
            LOGGER.error("[import_objects] ImportRuntimeError: %s", err, exc_info=True)
            abort(500, "Failed to import Objects!")
        except AccessDeniedError as err:
            LOGGER.error("[import_objects] AccessDeniedError: %s", err)
            abort(403, "No permission to import Objects!")
        except Exception as err:
            LOGGER.error("[import_objects] Exception: %s. Type: %s", err, type(err), exc_info=True)
            abort(500, "Unexpected error occured while importing Objects!")

        # close request file
        request_file.close()

        # log all successful imports
        for message in import_response.success_imports:
            try:
                # get object state of every imported object
                current_object = objects_manager.get_object(message.public_id)
                current_object = CmdbObject.from_data(current_object)

                current_object_render_result = CmdbMultiRender(
                    [current_object],
                    request_user
                ).result(single_object=True)

                # insert object create log
                log_params = {
                    'object_id': message.public_id,
                    'user_id': request_user.get_public_id(),
                    'user_name': request_user.get_display_name(),
                    'comment': 'Object was imported',
                    'render_state': json.dumps(
                                        current_object_render_result,
                                        default=default).encode('UTF-8'),
                    'version': current_object.version
                }

                logs_manager.insert_log(action=LogAction.CREATE, log_type=CmdbObjectLog.__name__, **log_params)
            except ObjectsManagerGetError as err:
                LOGGER.error("[import_objects] ObjectsManagerGetError: %s. Type: %s", err, type(err), exc_info=True)
                abort(500, "Failed to retrieve an inserted Object!")
            except InstanceRenderError as err:
                #TODO: ERROR-FIX
                LOGGER.error("[import_objects] InstanceRenderError: %s. Type: %s", err, type(err), exc_info=True)
                abort(500, "Failed to render imported Object!")
            except BaseManagerInsertError as err:
                #TODO: ERROR-FIX
                LOGGER.debug("[import_objects] %s", err)
                abort(500, "Failed to insert imported Object into the database!")

        return DefaultResponse(import_response).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[import_objects] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while importing Objects!")
