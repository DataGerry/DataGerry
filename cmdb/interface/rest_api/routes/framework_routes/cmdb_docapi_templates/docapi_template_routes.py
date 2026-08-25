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
Implementation of all API routes for DocapiTemplates

A DocapiTemplate is an HTML template rendered into a PDF for one CmdbObject. The eight routes here are
its CRUD surface plus the render call, and every one of them is gated twice: by an ACL right (see
``DocapiTemplateRight``) and by the licensed ``DOCUMENT_GENERATOR`` feature

Two blueprints serve one resource, which is FE contract rather than an accident: ``docs`` carries the
paged list at ``/docs/template`` (the newer collection-parameters route the frontend uses for the
overview) while ``docapi`` carries everything else under ``/docapi/template``. The frontend calls the
create and update routes WITH a trailing slash, which is the form registered here

The render route is guarded by an OBJECT right, not a template one - see ``RENDER_OBJECT_RIGHT``
"""
from logging import Logger, getLogger
import json
from bson import json_util
from flask import abort, request
from werkzeug.exceptions import HTTPException
from werkzeug.wrappers.response import Response

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager import (
    DocapiTemplatesManager,
    ObjectsManager,
)

from cmdb.models.user_model import CmdbUser
from cmdb.models.object_model import CmdbObject
from cmdb.models.docapi_model.docapi_renderer import DocApiRenderer
from cmdb.framework.docapi.docapi_template.docapi_template import DocapiTemplate
from cmdb.framework.results import IterationResult
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.rest_api.responses import GetMultiResponse, DefaultResponse
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.routes.cmdb_license.license_guard import requires_feature
from cmdb.interface.rest_api.routes.framework_routes.cmdb_docapi_templates.docapi_template_constants import (
    RENDER_OBJECT_RIGHT,
    DocapiTemplateRight,
)
from cmdb.interface.blueprints import APIBlueprint

from cmdb.security.license.license_constants import LicenseFeature

from cmdb.errors.manager.docapi_templates_manager import (
    DocapiTemplatesManagerInsertError,
    DocapiTemplatesManagerGetError,
    DocapiTemplatesManagerDeleteError,
    DocapiTemplatesManagerUpdateError,
    DocapiTemplatesManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

docapi_blueprint = APIBlueprint('docapi', __name__, url_prefix='/docapi')

docs_blueprint = APIBlueprint('docs', __name__)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

@docapi_blueprint.route('/template/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@docapi_blueprint.protect(auth=True, right=DocapiTemplateRight.ADD.value)
@requires_feature(LicenseFeature.DOCUMENT_GENERATOR)
def create_template(request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to insert a DocapiTemplate into the database

    Requires the ``base.docapi.template.add`` right and the licensed DOCUMENT_GENERATOR feature. The
    identity and the author are server-owned: the public_id comes from the collection counter and the
    author from the request. Names are unique across templates, because the by-name route resolves a
    template by nothing else

    Args:
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 403 when the user lacks the right or the feature is unlicensed; 400 when the name
            is taken or the insert fails; 500 on an unexpected error

    Returns:
        DefaultResponse: public_id of the created DocapiTemplate
    """
    try:
        docapi_manager: DocapiTemplatesManager = ManagerProvider.get_manager(ManagerType.DOCAPI_TEMPLATES,
                                                                             request_user)

        add_data_dump = json.dumps(request.json)

        new_tpl_data = json.loads(add_data_dump, object_hook=json_util.object_hook)

        template_name = new_tpl_data.get('name')

        if docapi_manager.get_template_by_name(name=template_name):
            abort(400, f"A template with the name '{template_name}' already exists!")

        new_tpl_data['public_id'] = docapi_manager.get_new_docapi_public_id()
        new_tpl_data['author_id'] = request_user.get_public_id()

        template_instance = DocapiTemplate(**new_tpl_data)

        ack = docapi_manager.insert_template(template_instance)

        return DefaultResponse(ack).make_response()
    except HTTPException as http_err:
        raise http_err
    except DocapiTemplatesManagerInsertError as err:
        LOGGER.error("[create_template] %s", err, exc_info=True)
        abort(400, "Could not insert the new template in the database!")
    except Exception as err:
        LOGGER.error("[create_template] Exception: %s. Type: %s", err, type(err).__name__, exc_info=True)
        abort(500, "An error occured when trying to insert the template!")

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@docs_blueprint.route('/template', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@docs_blueprint.protect(auth=True, right=DocapiTemplateRight.VIEW.value)
@requires_feature(LicenseFeature.DOCUMENT_GENERATOR)
@docs_blueprint.parse_collection_parameters()
def get_templates(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for getting multiple DocapiTemplates

    Args:
        params (CollectionParameters): Filter for requested DocapiTemplates
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 403 when the user lacks the right or the feature is unlicensed; 400 when the
            iteration fails; 500 on an unexpected error

    Returns:
        GetMultiResponse: All the DocapiTemplates matching the CollectionParameters
    """
    try:
        docapi_manager: DocapiTemplatesManager = ManagerProvider.get_manager(ManagerType.DOCAPI_TEMPLATES,
                                                                             request_user)

        builder_params = BuilderParameters(**CollectionParameters.get_builder_params(params))

        iteration_result: IterationResult[DocapiTemplate] = docapi_manager.get_templates(builder_params)

        template_list = [DocapiTemplate.to_json(template) for template in iteration_result.results]

        api_response = GetMultiResponse(template_list,
                                        total=iteration_result.total,
                                        params=params,
                                        url=request.url,
                                        body=request.method == 'HEAD')

        return api_response.make_response()
    except HTTPException as http_err:
        raise http_err
    except DocapiTemplatesManagerIterationError as err:
        LOGGER.error("[get_templates] %s", err, exc_info=True)
        abort(400, "Could not retrieve templates from database!")
    except Exception as err:
        LOGGER.error("[get_templates] Exception: %s. Type: %s", err, type(err).__name__, exc_info=True)
        abort(500, "An error occured when trying to retrieve the templates!")


@docapi_blueprint.route('/template/by/<string:searchfilter>', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@docapi_blueprint.protect(auth=True, right=DocapiTemplateRight.VIEW.value)
@requires_feature(LicenseFeature.DOCUMENT_GENERATOR)
def get_template_list_filtered(searchfilter: str, request_user: CmdbUser) -> Response:
    """
    HTTP `GET` route for getting multiple DocapiTemplates filtered by the searchfilter

    With the ``minimal=true`` query parameter only a lightweight representation of each template
    (public_id + label) is returned, and only those fields are read from the database

    Requires the ``base.docapi.template.view`` right and the licensed DOCUMENT_GENERATOR feature

    Args:
        searchfilter (str): Filter for the DocapiTemplates, as a JSON object in the URL
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 403 when the user lacks the right or the feature is unlicensed; 400 when the
            filter is not valid JSON or the read fails; 500 on an unexpected error

    Returns:
        DefaultResponse: All DocapiTemplates matching the searchfilter (minimal when requested)
    """
    try:
        docapi_manager: DocapiTemplatesManager = ManagerProvider.get_manager(ManagerType.DOCAPI_TEMPLATES,
                                                                             request_user)
        try:
            filterdict = json.loads(searchfilter)
        except ValueError:
            abort(400, f"The searchfilter is not valid JSON: {searchfilter}")

        minimal = request.args.get('minimal', 'false') in ['True', 'true']

        if minimal:
            tpl = docapi_manager.get_minimal_templates_by(**filterdict)
        else:
            tpl = docapi_manager.get_templates_by(**filterdict)

        api_response = DefaultResponse(tpl)

        return api_response.make_response()
    except HTTPException as http_err:
        raise http_err
    except DocapiTemplatesManagerGetError as err:
        LOGGER.error("[get_template_list_filtered] %s", err, exc_info=True)
        # A failed read is not "not found" - the filter may well match templates that exist
        abort(400, f"Could not retrieve template list for filter: {searchfilter}")
    except Exception as err:
        LOGGER.error("[get_template_list_filtered] Exception: %s. Type: %s", err, type(err).__name__, exc_info=True)
        abort(500, "An error occured when trying to retrieve the templates!")


@docapi_blueprint.route('/template/<int:public_id>', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@docapi_blueprint.protect(auth=True, right=DocapiTemplateRight.VIEW.value)
@requires_feature(LicenseFeature.DOCUMENT_GENERATOR)
def get_template(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET` route for retrieving a single DocapiTemplate with the given public_id

    Requires the ``base.docapi.template.view`` right and the licensed DOCUMENT_GENERATOR feature

    Args:
        public_id (int): public_id of the DocapiTemplate which should be retrieved
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 403 when the user lacks the right or the feature is unlicensed; 404 when no
            DocapiTemplate carries the public_id; 400 when the read fails; 500 on an unexpected error

    Returns:
        DefaultResponse: The requested DocapiTemplate
    """
    try:
        docapi_manager: DocapiTemplatesManager = ManagerProvider.get_manager(ManagerType.DOCAPI_TEMPLATES,
                                                                             request_user)

        tpl = docapi_manager.get_template(public_id)

        if not tpl:
            abort(404, f"Could not retrieve the requested template with ID: {public_id}!")

        return DefaultResponse(tpl).make_response()
    except HTTPException as http_err:
        raise http_err
    except DocapiTemplatesManagerGetError as err:
        LOGGER.error("[get_template] %s", err, exc_info=True)
        abort(400, "Could not retrieve the requested template!")
    except Exception as err:
        LOGGER.error("[get_template] Exception: %s. Type: %s", err, type(err).__name__, exc_info=True)
        abort(500, "An error occured when trying to retrieve the template!")


@docapi_blueprint.route('/template/name/<string:name>', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@docapi_blueprint.protect(auth=True, right=DocapiTemplateRight.VIEW.value)
@requires_feature(LicenseFeature.DOCUMENT_GENERATOR)
def get_template_by_name(name: str, request_user: CmdbUser) -> Response:
    """
    HTTP `GET` route for retrieving a single DocapiTemplate with the given name

    Requires the ``base.docapi.template.view`` right and the licensed DOCUMENT_GENERATOR feature. Names
    are unique, which is what makes this route able to resolve one template

    Args:
        name (str): name of the DocapiTemplate
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 403 when the user lacks the right or the feature is unlicensed; 404 when no
            DocapiTemplate carries the name; 400 when the read fails; 500 on an unexpected error

    Returns:
        DefaultResponse: The requested DocapiTemplate
    """
    try:
        docapi_manager: DocapiTemplatesManager = ManagerProvider.get_manager(ManagerType.DOCAPI_TEMPLATES,
                                                                                request_user)

        tpl = docapi_manager.get_template_by_name(name=name)

        if not tpl:
            # The id route answers 404 for a missing template; a missing name is the same answer
            abort(404, f"Could not retrieve the template with name:{name}!")

        return DefaultResponse(tpl).make_response()
    except HTTPException as http_err:
        raise http_err
    except DocapiTemplatesManagerGetError as err:
        LOGGER.error("[get_template_by_name] %s", err, exc_info=True)
        abort(400, f"Could not retrieve the template with name:{name}!")
    except Exception as err:
        LOGGER.error("[get_template_by_name] Exception: %s. Type: %s", err, type(err).__name__, exc_info=True)
        abort(500, f"An internal server error occured when trying to retrieve the Template with name:{name}!")


@docapi_blueprint.route('/template/<int:public_id>/render/<int:object_id>', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@docapi_blueprint.protect(auth=True, right=RENDER_OBJECT_RIGHT)
@requires_feature(LicenseFeature.DOCUMENT_GENERATOR)
def render_object_template(public_id: int, object_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET` route for retrieving a single rendered DocapiTemplate

    Requires the ``base.framework.object.view`` right - an OBJECT right, because the document is built
    from the object's field values - and the licensed DOCUMENT_GENERATOR feature. The object is read
    WITHOUT the object ACL, which is a filed decision rather than an oversight

    Every render answers with the same attachment name, ``output.pdf``; the frontend names the download
    itself

    Args:
        public_id (int): public_id of DocapiTemplate which should be used
        object_id (int): public_id of CmdbObject should be rendered
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 403 when the user lacks the right or the feature is unlicensed; 404 when the
            template or the object does not exist; 500 when the render fails

    Returns:
        Response: The rendered DocapiTemplate with the CmdbObject as a PDF-file
    """
    try:
        docapi_manager: DocapiTemplatesManager = ManagerProvider.get_manager(ManagerType.DOCAPI_TEMPLATES,
                                                                                request_user)

        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

        target_template: DocapiTemplate = docapi_manager.get_template(public_id)

        if not target_template:
            abort(404, f"Template with ID: {public_id} not found!")

        target_object = objects_manager.get_object(object_id)

        if not target_object:
            abort(404, f"Object with ID: {object_id} for Template with ID: {public_id} not found!")

        docapi_renderer = DocApiRenderer(
            objects_manager,
            target_template,
            CmdbObject.from_data(target_object)
        )

        output = docapi_renderer.render_object_template(request_user)

        return Response(
            output,
            mimetype="application/pdf",
            headers={
                "Content-Disposition": "attachment; filename=output.pdf"
            }
        )
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[render_object_template] Exception: %s. Type: %s", err, type(err).__name__, exc_info=True)
        abort(500,
            f"An unexpected error occured while trying to render the Template with ID: {public_id} "
            f"for Object with ID: {object_id}!"
        )

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@docapi_blueprint.route('/template/', methods=['PUT'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@docapi_blueprint.protect(auth=True, right=DocapiTemplateRight.EDIT.value)
@requires_feature(LicenseFeature.DOCUMENT_GENERATOR)
def update_template(request_user: CmdbUser) -> Response:
    """
    HTTP `PUT` route for updating a single DocapiTemplate

    Requires the ``base.docapi.template.edit`` right and the licensed DOCUMENT_GENERATOR feature. The
    name stays unique: renaming onto a name another template already carries is refused, the same way
    the create route refuses a taken name - otherwise the by-name route would resolve one of two
    templates arbitrarily

    Args:
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 403 when the user lacks the right or the feature is unlicensed; 404 when the
            template does not exist; 400 when the new name is taken or the update fails; 500 on an
            unexpected error

    Returns:
        DefaultResponse: The updated DocapiTemplate
    """
    try:
        docapi_manager: DocapiTemplatesManager = ManagerProvider.get_manager(ManagerType.DOCAPI_TEMPLATES,
                                                                             request_user)

        add_data_dump = json.dumps(request.json)
        new_tpl_data = json.loads(add_data_dump, object_hook=json_util.object_hook)

        update_tpl_instance = DocapiTemplate(**new_tpl_data)
        template_id: int = update_tpl_instance.get_public_id()

        if not docapi_manager.get_template(template_id):
            abort(404, f"Template with ID: {template_id} not found!")

        name_holder = docapi_manager.get_template_by_name(name=update_tpl_instance.name)

        if name_holder and name_holder.get_public_id() != template_id:
            abort(400, f"A template with the name '{update_tpl_instance.name}' already exists!")

        docapi_manager.update_template(update_tpl_instance)

        return DefaultResponse(DocapiTemplate.to_json(update_tpl_instance)).make_response()
    except HTTPException as http_err:
        raise http_err
    except DocapiTemplatesManagerUpdateError as err:
        LOGGER.error("[update_template] %s", err, exc_info=True)
        abort(400, "Could not update the template!")
    except Exception as err:
        LOGGER.error("[update_template] Exception: %s. Type: %s", err, type(err).__name__, exc_info=True)
        abort(500, "An error occured when trying to update the template!")

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@docapi_blueprint.route('/template/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@docapi_blueprint.protect(auth=True, right=DocapiTemplateRight.DELETE.value)
@requires_feature(LicenseFeature.DOCUMENT_GENERATOR)
def delete_template(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route to delete a single DocapiTemplate

    Requires the ``base.docapi.template.delete`` right and the licensed DOCUMENT_GENERATOR feature

    Args:
        public_id (int): public_id of the DocapiTemplate which should be deleted
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 403 when the user lacks the right or the feature is unlicensed; 404 when the
            template does not exist; 400 when the deletion fails; 500 on an unexpected error

    Returns:
        DefaultResponse: True if the deletion was successful
    """
    try:
        docapi_manager: DocapiTemplatesManager = ManagerProvider.get_manager(ManagerType.DOCAPI_TEMPLATES,
                                                                             request_user)

        if not docapi_manager.get_template(public_id):
            abort(404, f"Template with ID: {public_id} not found!")

        ack = docapi_manager.delete_template(public_id)

        return DefaultResponse(ack).make_response()
    except HTTPException as http_err:
        raise http_err
    except DocapiTemplatesManagerDeleteError as err:
        LOGGER.error("[delete_template] %s", err, exc_info=True)
        abort(400, "Could not delete the template!")
    except Exception as err:
        LOGGER.error("[delete_template] Exception: %s. Type: %s", err, type(err).__name__, exc_info=True)
        abort(500, "An error occured when trying to delete the template!")
