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
import os
import tempfile
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
from cmdb.framework.importer.importers.object_importer import ObjectImporter
from cmdb.framework.importer.responses.importer_object_response import ImporterObjectResponse
from cmdb.framework.importer.helper.importer_helper import (
    load_parser_class,
    load_importer_class,
    load_importer_config_class,
    OBJECT_IMPORTER_REGISTRY,
    OBJECT_PARSER_REGISTRY,
    OBJECT_IMPORTER_CONFIG_REGISTRY,
)
from cmdb.interface.rest_api.responses import DefaultResponse
from cmdb.interface.route_utils import (
    insert_request_user,
    verify_api_access,
)
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_helper import enforce_special_type_license
from cmdb.interface.rest_api.routes.importer_routes.importer_route_utils import (
    generate_parsed_output,
    verify_import_access,
)
from cmdb.interface.rest_api.routes.routes_helper import (
    get_file_in_request,
    get_element_from_data_request,
)
from cmdb.interface.rest_api.routes.importer_routes.importer_constants import (
    IMPORTER_KIND_OBJECT,
    ImporterFormField,
    ImporterConfigKey,
)

from cmdb.errors.security import AccessDeniedError
from cmdb.errors.importer import ImportRuntimeError, ImporterLoadError, ParserLoadError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

importer_object_blueprint = APIBlueprint('importer_object', __name__)

# -------------------------------------------------------------------------------------------------------------------- #
@importer_object_blueprint.route('/importer/', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@importer_object_blueprint.protect(auth=True, right='base.import.object.*')
def get_object_importer(request_user: CmdbUser) -> Response:  # pylint: disable=unused-argument
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

        for importer in OBJECT_IMPORTER_REGISTRY:
            importer_response.append({
                'name': OBJECT_IMPORTER_REGISTRY.get(importer).FILE_TYPE,
                'content_type': OBJECT_IMPORTER_REGISTRY.get(importer).CONTENT_TYPE,
                'icon': OBJECT_IMPORTER_REGISTRY.get(importer).ICON
            })

        return DefaultResponse(importer_response).make_response()
    except Exception as err:
        LOGGER.error("[get_object_importer] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occurred while retrieving the ObjectImporter!")


@importer_object_blueprint.route('/importer/config/<string:importer_type>/', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@importer_object_blueprint.protect(auth=True, right='base.import.object.*')
def get_default_object_importer_config(  # pylint: disable=unused-argument
        importer_type: str,
        request_user: CmdbUser) -> Response:
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
            importer: ObjectImporterConfig = OBJECT_IMPORTER_CONFIG_REGISTRY[importer_type]
        except KeyError:
            abort(404, f"ObjectImporter config with Type: {importer_type} not found!")

        return DefaultResponse({'manually_mapping': importer.MANUALLY_MAPPING}).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[get_default_object_importer_config] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occurred while retrieving the ObjectImporter config!")


@importer_object_blueprint.route('/parser/default/<string:parser_type>/', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@importer_object_blueprint.protect(auth=True, right='base.import.object.*')
def get_default_object_parser_config(  # pylint: disable=unused-argument
        parser_type: str,
        request_user: CmdbUser) -> Response:
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
            parser: BaseObjectParser = OBJECT_PARSER_REGISTRY[parser_type]
        except KeyError:
            abort(404, f"ObjectParser config with Type: {parser_type} not found!")

        return DefaultResponse(parser.DEFAULT_CONFIG).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[get_default_object_parser_config] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occurred while retrieving the default ObjectParser config!")


@importer_object_blueprint.route('/parse/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@importer_object_blueprint.protect(auth=True, right='base.import.object.*')
def parse_objects(request_user: CmdbUser) -> Response:  # pylint: disable=unused-argument
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
        # get_file_in_request aborts 400 itself when the file is missing
        request_file: FileStorage = get_file_in_request(ImporterFormField.FILE.value)

        # A missing / unparsable parser config is optional and falls back to the parser's defaults
        parser_config: dict = get_element_from_data_request(ImporterFormField.PARSER_CONFIG.value, request) or {}

        file_format = request.form.get(ImporterFormField.FILE_FORMAT.value)
        if not file_format:
            abort(400, "No file format was provided!")

        try:
            parsed_output = generate_parsed_output(request_file, file_format, parser_config).output()
        except HTTPException:
            raise
        except Exception as err:
            LOGGER.error("[parse_objects] Error: %s, Type: %s", err, type(err), exc_info=True)
            abort(400, "Could not parse the provided file with the given configuration!")

        return DefaultResponse(parsed_output).make_response()
    except HTTPException:
        raise
    except Exception as err:
        LOGGER.error("[parse_objects] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occurred while parsing Objects!")


@importer_object_blueprint.route('/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@importer_object_blueprint.protect(auth=True, right='base.import.object.*')
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
    working_file: str | None = None
    request_file: FileStorage | None = None

    try:
        # Check if file exists
        if not request.files:
            LOGGER.error("[import_objects] No import file!")
            abort(400, 'No import file was provided!')

        request_file = get_file_in_request(ImporterFormField.FILE.value)
        working_file = _save_import_file_to_temp(request_file)

        # Load file format
        file_format = request.form.get(ImporterFormField.FILE_FORMAT.value)

        # Load parser config (optional - falls back to the parser's defaults)
        parser_config: dict = get_element_from_data_request(ImporterFormField.PARSER_CONFIG.value, request) or {}
        if parser_config == {}:
            LOGGER.info('No parser config was provided - using default parser config')

        # Check for importer config
        importer_config_request: dict = get_element_from_data_request(
            ImporterFormField.IMPORTER_CONFIG.value, request
        ) or None
        if not importer_config_request:
            LOGGER.error("[import_objects] No import config was provided!")
            abort(400, 'No import config was provided!')

        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        logs_manager: LogsManager = ManagerProvider.get_manager(ManagerType.LOGS, request_user)

        # Resolve + authorise the target type
        type_: CmdbType = _resolve_import_type(importer_config_request, request_user, types_manager)

        # Importing objects of an IPAM special type requires a valid IPAM license
        enforce_special_type_license(request_user, bool(type_ and type_.special_type))

        # Load + build the parser / config / importer for the file format
        importer: ObjectImporter = _build_object_importer(
            file_format, working_file, parser_config, importer_config_request, objects_manager, request_user,
        )

        # Run the import and log the successfully imported objects (best-effort)
        import_response: ImporterObjectResponse = _run_object_import(importer)
        _log_imported_objects(import_response.success_imports, objects_manager, logs_manager, request_user)

        return DefaultResponse(import_response).make_response()
    except HTTPException:
        raise
    except Exception as err:
        LOGGER.error("[import_objects] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occurred while importing Objects!")
    finally:
        if request_file is not None:
            request_file.close()
        _remove_temp_file(working_file)


def _resolve_import_type(
        importer_config_request: dict,
        request_user: CmdbUser,
        types_manager: TypesManager) -> CmdbType:
    """
    Resolves and authorises the target CmdbType for an import

    Args:
        importer_config_request (dict): The importer config payload (must carry a valid 'type_id')
        request_user (CmdbUser): The user performing the import
        types_manager (TypesManager): Manager used to resolve the type

    Returns:
        CmdbType: The resolved, active, access-verified target type

    Raises:
        HTTPException: 404 if the type is missing, 403 if it is deactivated or the user lacks import
            access, 400 for any other resolution error
    """
    try:
        type_id = importer_config_request.get(ImporterConfigKey.TYPE_ID.value)
        type_ = types_manager.get_type(type_id)

        if not type_:
            abort(404, f"Type with public_id {type_id} not found!")

        type_ = CmdbType.from_data(type_)

        if not type_.active:
            raise AccessDeniedError(f'Objects cannot be created because type `{type_.name}` is deactivated.')

        verify_import_access(request_user, type_, types_manager)

        return type_
    except HTTPException:
        raise
    except AccessDeniedError:
        LOGGER.error("[import_objects] Access denied while importing objects")
        abort(403, "Access denied for importing objects!")
    except Exception as error:
        LOGGER.error("[import_objects] Exception: %s. Type: %s", error, type(error), exc_info=True)
        abort(400, "Could not import objects!")


def _build_object_importer(
        file_format: str,
        working_file: str,
        parser_config: dict,
        importer_config_request: dict,
        objects_manager: ObjectsManager,
        request_user: CmdbUser) -> ObjectImporter:
    """
    Loads and instantiates the parser, importer config and importer for the given file format

    Args:
        file_format (str): The uploaded file's format (e.g. 'csv', 'json')
        working_file (str): Path to the saved import file
        parser_config (dict): Parser configuration
        importer_config_request (dict): Importer configuration payload
        objects_manager (ObjectsManager): Manager used by the importer to read/insert objects
        request_user (CmdbUser): The user performing the import

    Returns:
        ObjectImporter: The ready-to-run importer

    Raises:
        HTTPException: 500 if any parser/importer class fails to load
    """
    try:
        parser_class = load_parser_class(IMPORTER_KIND_OBJECT, file_format)
    except ParserLoadError as err:
        LOGGER.error("[import_objects] ParserLoadError: %s", err, exc_info=True)
        abort(500, "Failed to load ObjectParser class!")

    parser = parser_class(parser_config)

    try:
        importer_config_class = load_importer_config_class(IMPORTER_KIND_OBJECT, file_format)
    except ImporterLoadError as err:
        LOGGER.error("[import_objects] ImporterLoadError: %s", err, exc_info=True)
        abort(500, "Failed to load ObjectImporter config!")

    importer_config = importer_config_class(**importer_config_request)

    try:
        importer_class = load_importer_class(IMPORTER_KIND_OBJECT, file_format)
    except ImporterLoadError as err:
        LOGGER.error("[import_objects] ImporterLoadError: %s", err, exc_info=True)
        abort(500, f"Failed to load ObjectImporter for file format: {file_format}!")

    return importer_class(working_file, importer_config, parser, objects_manager, request_user)


def _run_object_import(importer: ObjectImporter) -> ImporterObjectResponse:
    """
    Runs the import, mapping importer errors to HTTP responses

    Args:
        importer (ObjectImporter): The importer to run

    Returns:
        ImporterObjectResponse: The import result (success/failure messages)

    Raises:
        HTTPException: 500 on an import runtime / unexpected error, 403 on access denial
    """
    try:
        return importer.start_import()
    except ImportRuntimeError as err:
        LOGGER.error("[import_objects] ImportRuntimeError: %s", err, exc_info=True)
        abort(500, "Failed to import Objects!")
    except AccessDeniedError as err:
        LOGGER.error("[import_objects] AccessDeniedError: %s", err)
        abort(403, "No permission to import Objects!")
    except Exception as err:
        LOGGER.error("[import_objects] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "Unexpected error occurred while importing Objects!")


def _save_import_file_to_temp(request_file: FileStorage) -> str:
    """
    Persists an uploaded import file to a private temporary file

    A per-request temporary file (instead of a fixed `/tmp/<filename>` path) avoids concurrent imports
    of the same filename clobbering each other's data.

    Args:
        request_file (FileStorage): The uploaded import file

    Returns:
        str: The path of the temporary file the upload was saved to
    """
    suffix = f'_{secure_filename(request_file.filename)}'
    file_descriptor, working_file = tempfile.mkstemp(suffix=suffix)
    os.close(file_descriptor)
    request_file.save(working_file)

    return working_file


def _remove_temp_file(working_file: str | None) -> None:
    """
    Removes a temporary import file if it exists (best-effort cleanup)

    Args:
        working_file (str | None): The path of the temporary file, or None if none was created
    """
    if working_file and os.path.exists(working_file):
        os.remove(working_file)


def _log_imported_objects(
        success_imports: list,
        objects_manager: ObjectsManager,
        logs_manager: LogsManager,
        request_user: CmdbUser) -> None:
    """
    Writes a CREATE log for each successfully imported object (best-effort)

    The objects are already persisted by the time this runs, so a failure to fetch, render or log a
    single object must not fail the whole import - it is logged and the remaining objects continue.

    Args:
        success_imports (list): The ImportSuccessMessage entries of the imported objects
        objects_manager (ObjectsManager): Manager used to re-read the imported object state
        logs_manager (LogsManager): Manager used to persist the create log
        request_user (CmdbUser): The user credited as the log author
    """
    for message in success_imports:
        try:
            current_object = CmdbObject.from_data(objects_manager.get_object(message.public_id))
            render_result = CmdbMultiRender([current_object], request_user).result(single_object=True)

            logs_manager.insert_log(
                action=LogAction.CREATE,
                log_type=CmdbObjectLog.__name__,
                object_id=message.public_id,
                user_id=request_user.get_public_id(),
                user_name=request_user.get_display_name(),
                comment='Object was imported',
                render_state=json.dumps(render_result, default=default).encode('UTF-8'),
                version=current_object.version,
            )
        # The objects are already committed, so any logging failure is best-effort: log it and move on
        except Exception as err:  # pylint: disable=broad-exception-caught
            LOGGER.error("[import_objects] Failed to log imported Object %s: %s. Type: %s",
                         message.public_id, err, type(err))
