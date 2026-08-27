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
REST routes for importing CmdbObjects from an uploaded file

Five routes back the frontend's import wizard, in the order it calls them: `/importer/` lists the
available importers, `/importer/config/<type>/` and `/parser/default/<type>/` return their default
settings, `/parse/` turns an uploaded file into a preview of the objects it holds, and `/` runs the
import itself. Only **csv** and **json** are registered - the three registries in
`framework.importer.helper.importer_helper` are the single source of truth for what is supported, and
both upload routes reject anything else with a 400 naming the supported set.

Two things about this surface are easy to get wrong:

* **A failed import is still HTTP 200.** `/` answers with the importer's partial report -
  `success_imports` as a count and `failed_imports` as one entry per rejected object, each carrying the
  data the user supplied and every reason it was refused. An import in which *every* row failed is
  therefore a 200 with an empty success count; the outcome is read off `failed_imports`, never off the
  status code. A 4xx/5xx from this route means the request could not be processed at all
* **The CREATE logs are best-effort.** The objects are committed before `_log_imported_objects` runs,
  so a failure there costs the audit entries and nothing else - the response still reports the objects
  as imported, and the user is not told (discussion-backlog #160)

The heavy lifting - parsing, mapping, per-object validation and insertion - lives in
`cmdb.framework.importer`; the routes here resolve the format, authorise the target type, build the
importer and map failures onto HTTP
"""
import json
import os
import tempfile
from typing import Any
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

from cmdb.models.object_model import CmdbObject, CmdbObjectKey
from cmdb.models.type_model.cmdb_type import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.log_model.cmdb_object_log import CmdbObjectLog
from cmdb.framework.rendering.cmdb_multi_render import CmdbMultiRender
from cmdb.framework.rendering.render_constants import RenderObjectInfoKey
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
    NO_CONTENT_TO_IMPORT_MESSAGE,
    ImporterFormField,
    ImporterConfigKey,
)

from cmdb.errors.security import AccessDeniedError
from cmdb.errors.importer import (
    ImportRuntimeError,
    ImporterLoadError,
    ParserLoadError,
    ParserNoContentError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

importer_object_blueprint = APIBlueprint('importer_object', __name__)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #


@importer_object_blueprint.route('/importer/', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@importer_object_blueprint.protect(auth=True, right='base.import.object.*')
def get_object_importer(request_user: CmdbUser) -> Response:  # pylint: disable=unused-argument
    """
    Retrieve a list of available object importers with their metadata

    This endpoint provides information about each registered object importer, including the file type
    it supports, the content type it expects, and the associated icon. This metadata is what the
    frontend's import wizard renders its format picker from

    Returns:
        Response: A Flask Response object containing a JSON list of importer metadata
                  Each item includes:
                    - name (str): The file type handled by the importer
                    - content_type (str): The MIME type expected by the importer
                    - icon (str): A string identifier for an icon representing the importer
    """
    try:
        importer_response = []

        for importer_class in OBJECT_IMPORTER_REGISTRY.values():
            importer_response.append({
                'name': importer_class.FILE_TYPE,
                'content_type': importer_class.CONTENT_TYPE,
                'icon': importer_class.ICON
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
    Retrieve the default configuration for a specific object importer type

    This endpoint returns configuration metadata for a given importer type,
    specifically whether the importer supports manual mapping of fields.

    Args:
        importer_type (str): The identifier for the importer type ('csv' or 'json')

    Returns:
        Response: A Flask Response object containing a JSON with:
            - manually_mapping (bool): Indicates if the importer allows manual field mapping
    """
    try:
        try:
            importer: type[ObjectImporterConfig] = OBJECT_IMPORTER_CONFIG_REGISTRY[importer_type]
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
    Retrieve the default configuration for a specific object parser

    This endpoint provides the default configuration settings for a given parser type.
    These settings define how the parser behaves when processing imported data.

    Args:
        parser_type (str): The identifier for the object parser ('csv' or 'json')

    Returns:
        Response: A Flask Response object containing a JSON object with the parser's
                  default configuration parameters
    """
    try:
        try:
            parser: type[BaseObjectParser] = OBJECT_PARSER_REGISTRY[parser_type]
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
    Parse uploaded object data using the specified parser configuration

    This endpoint receives a file upload along with parser configuration and file format to generate a
    structured parsed output. It is the preview step of the import wizard: nothing is written, the
    caller gets back the objects the file holds so they can be reviewed before the real import

    Expected Multipart Form Data:
        - file (FileStorage): The file to be parsed
        - parser_config (JSON str or object): Configuration options for the parser; optional, an
          absent or unparsable one falls back to the parser's own defaults
        - file_format (str): Identifier for the file format ('csv' or 'json')

    Raises:
        HTTPException: 400 when the file is missing, the format is missing or unsupported, or the file
                       cannot be parsed with the given configuration; 500 on an unexpected failure

    Returns:
        Response: A Flask Response object containing a JSON list of parsed objects
    """
    try:
        # get_file_in_request aborts 400 itself when the file is missing
        request_file: FileStorage = get_file_in_request(ImporterFormField.FILE.value)

        # A missing / unparsable parser config is optional and falls back to the parser's defaults
        parser_config: dict = get_element_from_data_request(ImporterFormField.PARSER_CONFIG.value, request) or {}

        # Same resolution as the import route: an unsupported format is named here rather than
        # surfacing later as a misleading "check your parser configuration"
        file_format = _resolve_file_format()

        try:
            parsed_output = generate_parsed_output(request_file, file_format, parser_config).output()
        except HTTPException:
            raise
        except ParserNoContentError as err:
            # The file parsed fine and simply holds no data row, so the generic message below - which
            # points at the parser configuration - would name the wrong cause
            LOGGER.error("[parse_objects] ParserNoContentError: %s", err)
            abort(400, NO_CONTENT_TO_IMPORT_MESSAGE)
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
    Handle the full import of objects into the CMDB system using an uploaded file

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
        - file_format (str): Format of the uploaded file ('csv' or 'json')
        - parser_config (JSON): Configuration used to parse the file's contents
        - importer_config (JSON): Configuration used to import the parsed data into the system,
                                  must include a valid 'type_id'

    Returns:
        Response: A `DefaultResponse` carrying the partial report of the import - a summary line, the
                  number of imported objects (`success_imports`) and the `failed_imports` of the objects
                  that were rejected (each as `{failed_object, errors}`, carrying the data the user
                  provided and every reason). A partially or fully failed import is still HTTP 200, so
                  the outcome is read off `failed_imports`, never off the status code
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

        # Load + check the file format (client input, so an unusable one is a bad request)
        file_format = _resolve_file_format()

        # Load parser config (optional - falls back to the parser's defaults)
        parser_config: dict = get_element_from_data_request(ImporterFormField.PARSER_CONFIG.value, request) or {}
        if parser_config == {}:
            LOGGER.info('No parser config was provided - using default parser config')

        # Check for importer config
        importer_config_request: dict | None = get_element_from_data_request(
            ImporterFormField.IMPORTER_CONFIG.value, request
        )
        if not importer_config_request:
            LOGGER.error("[import_objects] No import config was provided!")
            abort(400, 'No import config was provided!')

        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        logs_manager: LogsManager = ManagerProvider.get_manager(ManagerType.LOGS, request_user)

        # Resolve + authorise the target type
        type_: CmdbType = _resolve_import_type(importer_config_request, request_user, types_manager)

        # Importing objects of an IPAM special type requires a valid IPAM license
        enforce_special_type_license(request_user, type_.special_type)

        # Load + build the parser / config / importer for the file format
        importer: ObjectImporter = _build_object_importer(
            file_format, working_file, parser_config, importer_config_request, objects_manager, request_user,
        )
        # The type was already read (and authorised) above - the importer reuses it instead of
        # spending a second read on it
        importer.target_type = type_

        # Run the import and log the successfully imported objects (best-effort)
        import_response: ImporterObjectResponse = _run_object_import(importer)
        _log_imported_objects(import_response.success_imports, objects_manager, logs_manager, request_user)

        return DefaultResponse(import_response.as_report()).make_response()
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


def _resolve_file_format() -> str:
    """
    Reads the uploaded file's format and checks that something can actually handle it

    Both the absence of a format and an unsupported one are the caller's mistake, so both are a 400 -
    the same answer the /parse/ route gives. A parser or importer class that then fails to LOAD is a
    different matter and stays a 500

    Returns:
        str: The requested file format

    Raises:
        HTTPException: 400 when no format was provided or no importer is registered for it
    """
    file_format = request.form.get(ImporterFormField.FILE_FORMAT.value)

    if not file_format:
        LOGGER.error("[import_objects] No file format was provided!")
        abort(400, "No file format was provided!")

    if file_format not in OBJECT_IMPORTER_REGISTRY:
        LOGGER.error("[import_objects] Unsupported file format: %s", file_format)
        abort(400, f"Unsupported file format: {file_format}! "
                   f"Supported formats: {', '.join(sorted(OBJECT_IMPORTER_REGISTRY))}")

    return file_format


def _build_importer_config(importer_config_class: type, importer_config_request: dict) -> Any:
    """
    Instantiates the importer configuration from the request payload

    The payload is handed to the config class as keyword arguments, so a key it does not accept - a
    typo, or a field from another importer - raises a TypeError. That is a malformed request, not a
    server fault, so it is reported as a 400 naming the offending payload. The two batch bounds are
    checked here as well: they are counts, and a negative one silently means something else entirely
    (``candidates[-5:]`` is the TAIL of the batch, and a negative maximum reads as "no limit")

    Args:
        importer_config_class (type): The config class registered for the file format
        importer_config_request (dict): The importer config payload from the request

    Returns:
        Any: The instantiated importer configuration

    Raises:
        HTTPException: 400 when the payload carries an unusable key or a negative bound
    """
    for bound in (ImporterConfigKey.START_ELEMENT.value, ImporterConfigKey.MAX_ELEMENTS.value):
        value = importer_config_request.get(bound)

        if isinstance(value, int) and not isinstance(value, bool) and value < 0:
            abort(400, f"'{bound}' must not be negative, got {value}!")

    try:
        return importer_config_class(**importer_config_request)
    except TypeError as err:
        LOGGER.error("[import_objects] Unusable importer config: %s", err)
        abort(400, f"The importer config is not valid for this file format: {err}")


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
        file_format (str): The uploaded file's format ('csv' or 'json')
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

    importer_config = _build_importer_config(importer_config_class, importer_config_request)

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
        HTTPException: 400 when the file carries no data row, 500 on an import runtime / unexpected
                       error, 403 on access denial
    """
    try:
        return importer.start_import()
    except ParserNoContentError as err:
        # An empty file is the caller's, not the server's, problem - it must not surface as a 500
        LOGGER.error("[import_objects] ParserNoContentError: %s", err)
        abort(400, NO_CONTENT_TO_IMPORT_MESSAGE)
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


def _render_imported_objects(
        public_ids: list[int],
        objects_manager: ObjectsManager,
        request_user: CmdbUser) -> dict[int, Any]:
    """
    Reads and renders every imported object, keyed by public_id

    Deliberately batched: one query for all ids and ONE CmdbMultiRender pass over the result, rather
    than a read plus a render per object. CmdbMultiRender builds its type / user caches once per
    instance, so rendering a 5000-row import object-by-object re-reads the same CmdbType 5000 times.
    Objects that no longer exist, or that the renderer skips because their type is gone, are simply
    absent from the mapping and their caller drops the log entry for them

    Args:
        public_ids (list[int]): public_ids of the successfully imported CmdbObjects
        objects_manager (ObjectsManager): Manager used to re-read the imported object state
        request_user (CmdbUser): The user the render is performed for

    Returns:
        dict[int, Any]: public_id -> RenderResult for every object that could be rendered
    """
    stored_objects: list[CmdbObject] = [
        CmdbObject.from_data(document)
        for document in objects_manager.find_objects({CmdbObjectKey.PUBLIC_ID.value: {'$in': public_ids}})
    ]

    if not stored_objects:
        return {}

    rendered = CmdbMultiRender(stored_objects, request_user).result()

    return {
        result.object_information[RenderObjectInfoKey.OBJECT_ID.value]: result
        for result in rendered or []
    }


def _log_imported_objects(
        success_messages: list,
        objects_manager: ObjectsManager,
        logs_manager: LogsManager,
        request_user: CmdbUser) -> None:
    """
    Writes a CREATE log for each successfully imported object (best-effort)

    The objects are already persisted by the time this runs, so nothing here may fail the import: a
    read/render batch that blows up costs every log entry, a single failing insert costs only its own,
    and either way the import still reports success. Nothing surfaces that to the user - the response
    reports the objects as imported, because they are - see discussion-backlog #160

    Args:
        success_messages (list): The ImportSuccessMessage entries of the imported objects. They exist
                                 only inside the import: the response reports the imported objects as a
                                 count, but the CREATE logs need their public_ids
        objects_manager (ObjectsManager): Manager used to re-read the imported object state
        logs_manager (LogsManager): Manager used to persist the create log
        request_user (CmdbUser): The user credited as the log author
    """
    public_ids: list[int] = [message.public_id for message in success_messages]

    if not public_ids:
        return

    try:
        rendered_by_id: dict[int, Any] = _render_imported_objects(public_ids, objects_manager, request_user)
    # A failed batch costs the logs, never the import - the objects are already committed
    except Exception as err:  # pylint: disable=broad-exception-caught
        LOGGER.error("[import_objects] Failed to render %s imported Objects for logging: %s. Type: %s",
                     len(public_ids), err, type(err))

        return

    for public_id in public_ids:
        render_result = rendered_by_id.get(public_id)

        if render_result is None:
            LOGGER.error("[import_objects] Imported Object %s could not be rendered; no ObjectLog written",
                         public_id)
            continue

        try:
            logs_manager.insert_log(
                action=LogAction.CREATE,
                log_type=CmdbObjectLog.__name__,
                object_id=public_id,
                user_id=request_user.get_public_id(),
                user_name=request_user.get_display_name(),
                comment='Object was imported',
                render_state=json.dumps(render_result, default=default).encode('UTF-8'),
                version=render_result.object_information[RenderObjectInfoKey.VERSION.value],
            )
        # The objects are already committed, so any logging failure is best-effort: log it and move on
        except Exception as err:  # pylint: disable=broad-exception-caught
            LOGGER.error("[import_objects] Failed to log imported Object %s: %s. Type: %s",
                         public_id, err, type(err))
