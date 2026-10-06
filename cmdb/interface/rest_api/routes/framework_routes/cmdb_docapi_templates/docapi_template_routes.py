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

The render route needs two rights - the object right ``RENDER_OBJECT_RIGHT`` and the template view right -
and reads its object, and everything the document pulls in, through the caller's READ ACL. The two write
routes hold their body to the template schema (``DocapiTemplate.SCHEMA``, see ``DOCAPI_TEMPLATE_CREATE_SCHEMA``
/ ``DOCAPI_TEMPLATE_UPDATE_SCHEMA``), and every route's error tail is the shared ``handle_route_errors``

``/docapi/template/name/<name>`` is the odd one out among the reads: it is a name-availability check for
the template-name input, so an unused name is a 200 with ``null`` rather than a 404. That check is only
meaningful because a template's ``name`` is decided on CREATE and immutable afterwards
"""
from logging import Logger, getLogger
from typing import Any
from flask import abort, request
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
from cmdb.class_schema.write_schema_helper import build_write_schema
from cmdb.framework.docapi.docapi_template.docapi_template import DocapiTemplate
from cmdb.framework.docapi.docapi_template.docapi_template_constants import DocapiTemplateKey
from cmdb.framework.exporter.export_filename_helper import build_document_export_filename
from cmdb.framework.results import IterationResult
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.rest_api.responses import GetMultiResponse, DefaultResponse
from cmdb.interface.route_utils import (
    handle_manager_errors,
    handle_route_errors,
    insert_request_user,
    verify_api_access,
)
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.routes.cmdb_license.license_guard import requires_feature
from cmdb.interface.rest_api.routes.framework_routes.cmdb_docapi_templates.docapi_template_constants import (
    RENDER_OBJECT_DENIED_MSG,
    RENDER_OBJECT_RIGHT,
    RENDER_TEMPLATE_DEACTIVATED_MSG,
    RENDERED_DOCUMENT_EXTENSION,
    RENDERED_DOCUMENT_MIMETYPE,
    DocapiTemplateRight,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_docapi_templates.docapi_template_helper import (
    parse_template_searchfilter,
)
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.rest_api.routes.routes_helper import build_searchable_builder_params, request_wants_body

from cmdb.security.acl.permission import AccessControlPermission
from cmdb.security.license.license_constants import LicenseFeature

from cmdb.errors.security import AccessDeniedError
from cmdb.errors.manager.docapi_templates_manager import (
    DocapiTemplatesManagerInsertError,
    DocapiTemplatesManagerGetError,
    DocapiTemplatesManagerDeleteError,
    DocapiTemplatesManagerUpdateError,
    DocapiTemplatesManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

#: The create body: the document schema without the two keys the server stamps
DOCAPI_TEMPLATE_CREATE_SCHEMA: dict[str, Any] = build_write_schema(
    DocapiTemplate.SCHEMA, {DocapiTemplateKey.PUBLIC_ID.value, DocapiTemplateKey.AUTHOR_ID.value},
)

#: The update body: the document schema without the author, which the stored template keeps. The public_id
#: stays required - it is the only identity the route has
DOCAPI_TEMPLATE_UPDATE_SCHEMA: dict[str, Any] = build_write_schema(
    DocapiTemplate.SCHEMA, {DocapiTemplateKey.AUTHOR_ID.value},
)

#: The DocapiTemplate columns the template list offers a search box over
DOCAPI_TEMPLATE_SEARCHABLE_FIELDS: tuple[str, ...] = ('public_id', 'name', 'label', 'description')

docapi_blueprint = APIBlueprint('docapi', __name__, url_prefix='/docapi')

docs_blueprint = APIBlueprint('docs', __name__)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

@docapi_blueprint.route('/template/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@docapi_blueprint.protect(auth=True, right=DocapiTemplateRight.ADD.value)
@requires_feature(LicenseFeature.DOCUMENT_GENERATOR)
@docapi_blueprint.validate(DOCAPI_TEMPLATE_CREATE_SCHEMA)
@handle_route_errors("while inserting the Template")
@handle_manager_errors({DocapiTemplatesManagerInsertError: "Could not insert the new template in the database!"})
def create_template(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to insert a DocapiTemplate into the database

    Requires the ``base.docapi.template.add`` right and the licensed DOCUMENT_GENERATOR feature. The body is
    held to ``DOCAPI_TEMPLATE_CREATE_SCHEMA`` - a required, usable ``name`` and every other key of its declared
    type - so a value the renderer could not use is refused here rather than failing every later render. The
    identity and the author are server-owned: the schema drops a sent ``public_id`` / ``author_id``, the
    public_id comes from the collection counter and the author from the request. Names are unique across
    templates, because the by-name route resolves a template by nothing else - and this route is the only
    place a name is decided, since the update route refuses to rename an existing template

    Args:
        data (dict[str, Any]): The validated request body
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 403 when the user lacks the right or the feature is unlicensed; 400 when the body breaks
            the schema, the name is taken or the insert fails; 500 on an unexpected error

    Returns:
        DefaultResponse: public_id of the created DocapiTemplate
    """
    docapi_manager: DocapiTemplatesManager = ManagerProvider.get_manager(ManagerType.DOCAPI_TEMPLATES, request_user)

    template_name: str = data[DocapiTemplateKey.NAME.value]

    if docapi_manager.get_template_by_name(name=template_name):
        abort(400, f"A template with the name '{template_name}' already exists!")

    data[DocapiTemplateKey.PUBLIC_ID.value] = docapi_manager.get_new_docapi_public_id()
    data[DocapiTemplateKey.AUTHOR_ID.value] = request_user.get_public_id()

    ack = docapi_manager.insert_template(DocapiTemplate(**data))

    return DefaultResponse(ack).make_response()

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@docs_blueprint.route('/template', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@docs_blueprint.protect(auth=True, right=DocapiTemplateRight.VIEW.value)
@requires_feature(LicenseFeature.DOCUMENT_GENERATOR)
@docs_blueprint.parse_collection_parameters()
@handle_route_errors("while retrieving the Templates")
@handle_manager_errors({DocapiTemplatesManagerIterationError: "Could not retrieve templates from database!"})
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
    docapi_manager: DocapiTemplatesManager = ManagerProvider.get_manager(ManagerType.DOCAPI_TEMPLATES,
                                                                         request_user)

    builder_params: BuilderParameters = build_searchable_builder_params(params, DOCAPI_TEMPLATE_SEARCHABLE_FIELDS)

    iteration_result: IterationResult[DocapiTemplate] = docapi_manager.get_templates(builder_params)

    template_list = [DocapiTemplate.to_json(template) for template in iteration_result.results]

    api_response = GetMultiResponse(template_list,
                                    total=iteration_result.total,
                                    params=params,
                                    url=request.url,
                                    body=request_wants_body())

    return api_response.make_response()


@docapi_blueprint.route('/template/by/<string:searchfilter>', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@docapi_blueprint.protect(auth=True, right=DocapiTemplateRight.VIEW.value)
@requires_feature(LicenseFeature.DOCUMENT_GENERATOR)
@handle_route_errors("while retrieving the Templates for the filter: {searchfilter}")
@handle_manager_errors({
    # A failed read is not "not found" - the filter may well match templates that exist
    DocapiTemplatesManagerGetError: "Could not retrieve template list for filter: {searchfilter}",
})
def get_template_list_filtered(searchfilter: str, request_user: CmdbUser) -> Response:
    """
    HTTP `GET` route for getting multiple DocapiTemplates filtered by the searchfilter

    With the ``minimal=true`` query parameter only a lightweight representation of each template
    (public_id + label) is returned, and only those fields are read from the database

    Requires the ``base.docapi.template.view`` right and the licensed DOCUMENT_GENERATOR feature

    The filter is an equality match on declared template keys (``SEARCHFILTER_KEYS``) and reaches the
    database as the query document, so ``parse_template_searchfilter`` refuses every MongoDB operator
    before the read - ``$where`` and ``$function`` would run JavaScript on the database server

    Args:
        searchfilter (str): Filter for the DocapiTemplates, as a JSON object in the URL
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 403 when the user lacks the right or the feature is unlicensed; 400 when the
            filter is not valid JSON, is not an object, names a key that is not searchable or an
            operator, or when the read fails; 500 on an unexpected error

    Returns:
        DefaultResponse: All DocapiTemplates matching the searchfilter (minimal when requested)
    """
    docapi_manager: DocapiTemplatesManager = ManagerProvider.get_manager(ManagerType.DOCAPI_TEMPLATES,
                                                                         request_user)
    filterdict: dict[str, Any] = parse_template_searchfilter(searchfilter)

    minimal = request.args.get('minimal', 'false') in ['True', 'true']

    if minimal:
        tpl = docapi_manager.get_minimal_templates_by(**filterdict)
    else:
        tpl = docapi_manager.get_templates_by(**filterdict)

    api_response = DefaultResponse(tpl)

    return api_response.make_response()


@docapi_blueprint.route('/template/<int:public_id>', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@docapi_blueprint.protect(auth=True, right=DocapiTemplateRight.VIEW.value)
@requires_feature(LicenseFeature.DOCUMENT_GENERATOR)
@handle_route_errors("while retrieving the Template with ID: {public_id}")
@handle_manager_errors({DocapiTemplatesManagerGetError: "Could not retrieve the requested template!"})
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
    docapi_manager: DocapiTemplatesManager = ManagerProvider.get_manager(ManagerType.DOCAPI_TEMPLATES,
                                                                         request_user)

    tpl = docapi_manager.get_template(public_id)

    if not tpl:
        abort(404, f"Could not retrieve the requested template with ID: {public_id}!")

    return DefaultResponse(tpl).make_response()


@docapi_blueprint.route('/template/name/<string:name>', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@docapi_blueprint.protect(auth=True, right=DocapiTemplateRight.VIEW.value)
@requires_feature(LicenseFeature.DOCUMENT_GENERATOR)
@handle_route_errors("when trying to retrieve the Template with name:{name}")
@handle_manager_errors({DocapiTemplatesManagerGetError: "Could not retrieve the template with name:{name}!"})
def get_template_by_name(name: str, request_user: CmdbUser) -> Response:
    """
    HTTP `GET` route for resolving a DocapiTemplate by its name

    Requires the ``base.docapi.template.view`` right and the licensed DOCUMENT_GENERATOR feature. Names
    are unique, which is what makes this route able to resolve one template

    This is a name-availability check, not a fetch of a resource the caller already knows exists: the
    frontend calls it while the user types a template name to tell them whether the name is still free.
    An unused name is therefore a successful answer, NOT a 404 - the route answers 200 with ``null`` so
    the caller can read "free" off the body instead of off an error. Only a failing read is an error

    Args:
        name (str): name of the DocapiTemplate
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 403 when the user lacks the right or the feature is unlicensed; 400 when the read
            fails; 500 on an unexpected error

    Returns:
        DefaultResponse: The DocapiTemplate carrying the name, or ``None`` when the name is unused
    """
    docapi_manager: DocapiTemplatesManager = ManagerProvider.get_manager(ManagerType.DOCAPI_TEMPLATES, request_user)

    tpl = docapi_manager.get_template_by_name(name=name)

    return DefaultResponse(tpl).make_response()


@docapi_blueprint.route('/template/<int:public_id>/render/<int:object_id>', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@docapi_blueprint.protect(auth=True, right=RENDER_OBJECT_RIGHT)
@docapi_blueprint.protect(auth=True, right=DocapiTemplateRight.VIEW.value)
@requires_feature(LicenseFeature.DOCUMENT_GENERATOR)
@handle_route_errors("while rendering the Template with ID: {public_id} for Object with ID: {object_id}")
def render_object_template(public_id: int, object_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET` route for retrieving a single rendered DocapiTemplate

    Requires two rights, because a render reads two things and answers both: ``base.framework.object.view``
    for the object's field values and ``base.docapi.template.view`` for the template, which the document
    reproduces in full - plus the licensed DOCUMENT_GENERATOR feature. A deactivated template is not
    rendered. The template is not checked against the object's type: a field the object's type lacks
    renders blank, and a ``DEFAULT`` template is bound to no type at all. The object is then read
    through the caller's READ ACL, like ``GET /objects/<id>``: an object whose type the caller's group
    may not read is a 403, and so is never rendered. The same ACL holds inside the document - every
    object it references, names by id, reaches through a relation or lists in a report table is read
    for the caller, and one they may not read renders blank

    The attachment is named by ``build_document_export_filename`` - the same helper the object and type
    exports use - so a rendered document carries its template, its object and the time it was taken
    rather than one generic ``output.pdf`` shared by every render

    Args:
        public_id (int): public_id of DocapiTemplate which should be used
        object_id (int): public_id of CmdbObject should be rendered
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 403 when the user lacks either right, the feature is unlicensed or the object's
            type ACL denies them READ; 400 when the template is deactivated; 404 when the template or the
            object does not exist; 500 when the render fails

    Returns:
        Response: The rendered DocapiTemplate with the CmdbObject as a PDF-file
    """
    docapi_manager: DocapiTemplatesManager = ManagerProvider.get_manager(ManagerType.DOCAPI_TEMPLATES,
                                                                            request_user)

    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

    target_template: DocapiTemplate = docapi_manager.get_template(public_id)

    if not target_template:
        abort(404, f"Template with ID: {public_id} not found!")

    if not target_template.get_active():
        abort(400, RENDER_TEMPLATE_DEACTIVATED_MSG.format(public_id=public_id))

    try:
        target_object = objects_manager.get_object(object_id, request_user, AccessControlPermission.READ)
    except AccessDeniedError:
        abort(403, RENDER_OBJECT_DENIED_MSG.format(object_id=object_id))

    if not target_object:
        abort(404, f"Object with ID: {object_id} for Template with ID: {public_id} not found!")

    docapi_renderer = DocApiRenderer(
        objects_manager,
        target_template,
        CmdbObject.from_data(target_object)
    )

    output = docapi_renderer.render_object_template(request_user)

    # The label is optional on the model, the name is required and unique, so the name stands in for
    # a template that carries no label
    filename: str = build_document_export_filename(
        target_template.get_label() or target_template.get_name(),
        object_id,
        RENDERED_DOCUMENT_EXTENSION,
    )

    return Response(
        output,
        mimetype=RENDERED_DOCUMENT_MIMETYPE,
        headers={
            # Quoted like every other export in the repo: the template label reaches this value, and
            # an unquoted header cannot carry a separator character
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )


# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@docapi_blueprint.route('/template/', methods=['PUT'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@docapi_blueprint.protect(auth=True, right=DocapiTemplateRight.EDIT.value)
@requires_feature(LicenseFeature.DOCUMENT_GENERATOR)
@docapi_blueprint.validate(DOCAPI_TEMPLATE_UPDATE_SCHEMA)
@handle_route_errors("while updating the Template")
@handle_manager_errors({DocapiTemplatesManagerUpdateError: "Could not update the template!"})
def update_template(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `PUT` route for updating a single DocapiTemplate

    Requires the ``base.docapi.template.edit`` right and the licensed DOCUMENT_GENERATOR feature

    The route addresses its template by the body's ``public_id`` - there is no id in the URL - so the body is
    held to ``DOCAPI_TEMPLATE_UPDATE_SCHEMA``, which requires that id as an integer next to the create route's
    rules. The author is server-owned: the schema drops a sent ``author_id`` and the stored template keeps the
    author it was created by

    The name is IMMUTABLE once the template exists: a payload carrying any other name than the stored
    one is refused, even when that name is free. The name is the template's stable handle - the frontend
    probes it for availability while a name is being typed (see ``get_template_by_name``) and only the
    create route decides it. Because it never moves once created, the create route's uniqueness check
    plus the unique index on ``name`` are the whole guarantee; nothing here can collide. Every other
    property is freely editable, and the whole document is expected in the payload

    Args:
        data (dict[str, Any]): The validated request body
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 403 when the user lacks the right or the feature is unlicensed; 404 when the
            template does not exist; 400 when the body breaks the schema, would rename the template, or the
            update fails; 500 on an unexpected error

    Returns:
        DefaultResponse: The updated DocapiTemplate
    """
    docapi_manager: DocapiTemplatesManager = ManagerProvider.get_manager(ManagerType.DOCAPI_TEMPLATES, request_user)

    template_id: int = data[DocapiTemplateKey.PUBLIC_ID.value]
    current_template: DocapiTemplate | None = docapi_manager.get_template(template_id)

    if not current_template:
        abort(404, f"Template with ID: {template_id} not found!")

    if data[DocapiTemplateKey.NAME.value] != current_template.name:
        abort(400, f"The 'name' of a template is not changable - '{current_template.name}' can not "
                   f"be renamed to '{data[DocapiTemplateKey.NAME.value]}'!")

    # The creator stays the author: an edit does not hand the template to whoever saved it
    data[DocapiTemplateKey.AUTHOR_ID.value] = current_template.get_author_id()

    update_tpl_instance = DocapiTemplate(**data)
    docapi_manager.update_template(update_tpl_instance)

    return DefaultResponse(DocapiTemplate.to_json(update_tpl_instance)).make_response()

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@docapi_blueprint.route('/template/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@docapi_blueprint.protect(auth=True, right=DocapiTemplateRight.DELETE.value)
@requires_feature(LicenseFeature.DOCUMENT_GENERATOR)
@handle_route_errors("while deleting the Template with ID: {public_id}")
@handle_manager_errors({DocapiTemplatesManagerDeleteError: "Could not delete the template!"})
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
    docapi_manager: DocapiTemplatesManager = ManagerProvider.get_manager(ManagerType.DOCAPI_TEMPLATES,
                                                                         request_user)

    if not docapi_manager.get_template(public_id):
        abort(404, f"Template with ID: {public_id} not found!")

    ack = docapi_manager.delete_template(public_id)

    return DefaultResponse(ack).make_response()
