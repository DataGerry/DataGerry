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
REST API routes for CmdbCategory CRUD

Blueprint ``categories_blueprint`` is mounted at ``/rest/categories`` (see
``init_rest_api.py``). Endpoints exposed:

    POST   /                  insert_cmdb_category
    GET    /                  get_cmdb_categories      (supports ``?view=tree``)
    GET    /<public_id>       get_cmdb_category
    PUT    /<public_id>       update_cmdb_category
    PATCH  /<public_id>       update_cmdb_category
    DELETE /<public_id>       delete_cmdb_category

All routes require authentication (JWT or ``x-api-key`` in cloud mode), ApiLevel.ADMIN,
and the per-route ``base.framework.category.*`` right. Manager-layer errors are translated
to HTTP 400 (business-rule / lookup failures) or HTTP 500 (unexpected) following the
codebase convention - 409 is not used here.
"""
from logging import Logger, getLogger
from typing import Any
from datetime import datetime, timezone

from flask import request, abort
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager import CategoriesManager

from cmdb.models.user_model import CmdbUser
from cmdb.models.category_model import CmdbCategory, CategoryTree
from cmdb.framework.results import IterationResult
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.rest_api.responses import (
    DeleteSingleResponse,
    UpdateSingleResponse,
    InsertSingleResponse,
    GetMultiResponse,
    GetSingleResponse,
)
from cmdb.interface.rest_api.routes.framework_routes.categories_constants import CategoryListView

from cmdb.errors.manager.categories_manager import (
    CategoriesManagerInsertError,
    CategoriesManagerGetError,
    CategoriesManagerUpdateError,
    CategoriesManagerDeleteError,
    CategoriesManagerIterationError,
    CategoriesManagerTreeInitError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

categories_blueprint = APIBlueprint('categories', __name__)

# ---------------------------------------------------- CRUD-CREATE --------------------------------------------------- #

@categories_blueprint.route('/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@categories_blueprint.protect(auth=True, right='base.framework.category.add')
@categories_blueprint.validate(CmdbCategory.SCHEMA)
def insert_cmdb_category(data: dict, request_user: CmdbUser) -> Response:
    """
    POST ``/rest/categories/`` - insert a CmdbCategory

    Payload is validated against ``CmdbCategory.SCHEMA`` before this function runs. A
    ``creation_time`` (UTC now) is stamped on the dict if the caller did not supply one.
    The persisted document is re-read from the database and returned so that any
    server-side defaults are reflected in the response.

    Required right: ``base.framework.category.add``. Required API level: ``ApiLevel.ADMIN``.

    Args:
        data (dict): Validated CmdbCategory payload (shape: ``CmdbCategory.SCHEMA``)
        request_user (CmdbUser): Authenticated requester, injected by ``@insert_request_user``

    Raises:
        HTTPException: 400 when the manager rejects the insert
            (``CategoriesManagerInsertError``) or the post-insert read
            (``CategoriesManagerGetError``)
        HTTPException: 404 when the inserted CmdbCategory cannot be retrieved afterwards
        HTTPException: 500 on any unexpected error

    Returns:
        Response: ``InsertSingleResponse`` containing the persisted CmdbCategory dict and
            its assigned public_id
    """
    try:
        categories_manager: CategoriesManager = ManagerProvider.get_manager(
            ManagerType.CATEGORIES,
            request_user
        )

        data.setdefault('creation_time', datetime.now(timezone.utc))

        result_id: int = categories_manager.insert_category(data)

        created_category: dict[str, Any] | None = categories_manager.get_category(result_id)

        if not created_category:
            abort(404, "Could not retrieve the created Category from the database!")

        return InsertSingleResponse(created_category, result_id).make_response()
    except HTTPException as http_err:
        raise http_err
    except CategoriesManagerInsertError as err:
        LOGGER.error("[insert_cmdb_category] %s", err, exc_info=True)
        abort(400, "Failed to insert the new Category in the database!")
    except CategoriesManagerGetError as err:
        LOGGER.error("[insert_cmdb_category] %s", err, exc_info=True)
        abort(400, "Failed to retrieve the created Category from the database!")
    except Exception as err:
        LOGGER.error("[insert_cmdb_category] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while inserting the Category into the database!")

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@categories_blueprint.route('/', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@categories_blueprint.protect(auth=True, right='base.framework.category.view')
@categories_blueprint.parse_collection_parameters(view=CategoryListView.LIST.value)
def get_cmdb_categories(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    GET/HEAD ``/rest/categories/`` - list CmdbCategories (flat list or tree)

    When ``params.optional['view'] == CategoryListView.TREE`` the response is a
    ``CategoryTree`` built from every CmdbCategory + every CmdbType (un-paginated). For
    any other view the standard paginated, filtered, sorted listing pipeline is used via
    ``CategoriesManager.iterate``.

    Required right: ``base.framework.category.view``. Required API level: ``ApiLevel.ADMIN``.

    Args:
        params (CollectionParameters): Filter, sort and pagination parameters parsed from the
            query string by ``@parse_collection_parameters(view='list')``
        request_user (CmdbUser): Authenticated requester, injected by ``@insert_request_user``

    Raises:
        HTTPException: 400 when the iteration pipeline fails
            (``CategoriesManagerIterationError``)
        HTTPException: 500 when tree composition fails
            (``CategoriesManagerTreeInitError``) or on any unexpected error

    Returns:
        Response: ``GetMultiResponse`` - paginated for the flat list view, un-paginated for
            ``view=tree`` (the tree is returned as a whole)
    """
    try:
        categories_manager: CategoriesManager = ManagerProvider.get_manager(
            ManagerType.CATEGORIES,
            request_user
        )

        body: bool = request.method == 'HEAD'

        if params.optional['view'] == CategoryListView.TREE:
            tree: CategoryTree = categories_manager.tree
            api_response = GetMultiResponse(
                CategoryTree.to_json(tree),
                len(tree),
                params,
                request.url,
                body
            )

            return api_response.make_response(pagination=False)

        # if view is not 'tree'
        builder_params = BuilderParameters(**CollectionParameters.get_builder_params(params))

        iteration_result: IterationResult[CmdbCategory] = categories_manager.iterate(builder_params)
        category_list: list[dict[str, Any]] = [CmdbCategory.to_json(category) for category in iteration_result.results]

        api_response = GetMultiResponse(
            category_list,
            iteration_result.total,
            params,
            request.url,
            body
        )

        return api_response.make_response()
    except CategoriesManagerIterationError as err:
        LOGGER.error("[get_cmdb_categories] %s", err, exc_info=True)
        abort(400, "Could not retrieve Categories from database!")
    except CategoriesManagerTreeInitError as err:
        LOGGER.error("[get_cmdb_categories] %s", err, exc_info=True)
        abort(500, "Failed to place the Categories into a tree structure!")
    except Exception as err:
        LOGGER.error("[get_cmdb_categories] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while retrieving Categories from the database!")


@categories_blueprint.route('/<int:public_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@categories_blueprint.protect(auth=True, right='base.framework.category.view')
def get_cmdb_category(public_id: int, request_user: CmdbUser) -> Response:
    """
    GET/HEAD ``/rest/categories/<public_id>`` - retrieve a single CmdbCategory

    Returns the raw category document (not the model instance). HEAD requests share the
    same handler; the body is suppressed downstream by ``GetSingleResponse(body=...)``.

    Required right: ``base.framework.category.view``. Required API level: ``ApiLevel.ADMIN``.

    Args:
        public_id (int): public_id of the CmdbCategory to retrieve
        request_user (CmdbUser): Authenticated requester, injected by ``@insert_request_user``

    Raises:
        HTTPException: 404 when no CmdbCategory with that public_id exists
        HTTPException: 400 when the read fails (``CategoriesManagerGetError``)
        HTTPException: 500 on any unexpected error

    Returns:
        Response: ``GetSingleResponse`` containing the CmdbCategory document
    """
    try:
        categories_manager: CategoriesManager = ManagerProvider.get_manager(
            ManagerType.CATEGORIES,
            request_user
        )

        requested_category: dict[str, Any] | None = categories_manager.get_category(public_id)

        if not requested_category:
            abort(404, f"The Category with ID:{public_id} was not found!")

        body: bool = request.method == 'HEAD'

        return GetSingleResponse(requested_category, body=body).make_response()
    except HTTPException as http_err:
        raise http_err
    except CategoriesManagerGetError as err:
        LOGGER.error("[get_cmdb_category] %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the requested Category with ID:{public_id} from the database!")
    except Exception as err:
        LOGGER.error("[get_cmdb_category] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while retrieving the Category with ID:{public_id}!")

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@categories_blueprint.route('/<int:public_id>', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@categories_blueprint.protect(auth=True, right='base.framework.category.edit')
@categories_blueprint.validate(CmdbCategory.SCHEMA)
def update_cmdb_category(public_id: int, data: dict, request_user: CmdbUser) -> Response:
    """
    PUT/PATCH ``/rest/categories/<public_id>`` - update a CmdbCategory

    The target is first read to confirm existence (404 otherwise), then the supplied dict
    is hydrated to a ``CmdbCategory`` instance and handed to ``update_category``. Payload
    is validated against ``CmdbCategory.SCHEMA`` by the blueprint decorator before this
    function runs.

    Required right: ``base.framework.category.edit``. Required API level: ``ApiLevel.ADMIN``.

    Args:
        public_id (int): public_id of the CmdbCategory which should be updated
        data (dict): Validated CmdbCategory payload (shape: ``CmdbCategory.SCHEMA``)
        request_user (CmdbUser): Authenticated requester, injected by ``@insert_request_user``

    Raises:
        HTTPException: 404 when no CmdbCategory with that public_id exists
        HTTPException: 400 when the pre-read fails (``CategoriesManagerGetError``) or the
            write fails (``CategoriesManagerUpdateError``)
        HTTPException: 500 on any unexpected error

    Returns:
        Response: ``UpdateSingleResponse`` containing the re-read CmdbCategory document so
            any server-side normalization is reflected in the response
    """
    try:
        categories_manager: CategoriesManager = ManagerProvider.get_manager(
            ManagerType.CATEGORIES,
            request_user
        )

        to_update_category: dict[str, Any] | None = categories_manager.get_category(public_id)

        if not to_update_category:
            abort(404, f"The Category with ID:{public_id} was not found!")

        categories_manager.update_category(public_id, data)

        updated_category: dict[str, Any] | None = categories_manager.get_category(public_id)

        return UpdateSingleResponse(updated_category).make_response()
    except HTTPException as http_err:
        raise http_err
    except CategoriesManagerGetError as err:
        LOGGER.error("[update_cmdb_category] %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the requested Category with ID:{public_id} from the database!")
    except CategoriesManagerUpdateError as err:
        LOGGER.error("[update_cmdb_category] %s", err, exc_info=True)
        abort(400, f"Failed to update the Category with ID:{public_id}!")
    except Exception as err:
        LOGGER.error("[update_cmdb_category] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while updating the Category with ID:{public_id}!")

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@categories_blueprint.route('/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@categories_blueprint.protect(auth=True, right='base.framework.category.delete')
def delete_cmdb_category(public_id: int, request_user: CmdbUser) -> Response:
    """
    DELETE ``/rest/categories/<public_id>`` - detach children, then delete the CmdbCategory

    Two-step operation, executed in order:

    1. ``remove_category_as_parent(public_id)`` nulls the ``parent`` field on every
       CmdbCategory that referenced this one as a parent.
    2. ``delete_category(public_id)`` removes the CmdbCategory document.

    The two steps are NOT transactional, but the order is chosen so that any failure in
    step 1 leaves the database untouched; only a failure in step 2 after step 1 succeeded
    can leave the database in a partial state (children detached, parent still present).

    Required right: ``base.framework.category.delete``. Required API level: ``ApiLevel.ADMIN``.

    Args:
        public_id (int): public_id of the CmdbCategory which should be deleted
        request_user (CmdbUser): Authenticated requester, injected by ``@insert_request_user``

    Raises:
        HTTPException: 404 when no CmdbCategory with that public_id exists
        HTTPException: 400 when the pre-read fails (``CategoriesManagerGetError``) or when
            step 1 fails (``CategoriesManagerUpdateError``); no DB change has happened yet
        HTTPException: 500 when step 2 fails (``CategoriesManagerDeleteError``) after step
            1 succeeded - children are already detached but the parent still exists - or
            on any other unexpected error

    Returns:
        Response: ``DeleteSingleResponse`` containing the pre-delete CmdbCategory document
    """
    try:
        categories_manager: CategoriesManager = ManagerProvider.get_manager(
            ManagerType.CATEGORIES,
            request_user
        )

        to_delete_category: dict[str, Any] | None = categories_manager.get_category(public_id)

        if not to_delete_category:
            abort(404, f"The Category with ID:{public_id} was not found!")

        # Detach children first so a failure here leaves the parent intact
        categories_manager.remove_category_as_parent(public_id)

        categories_manager.delete_category(public_id)

        return DeleteSingleResponse(raw=to_delete_category).make_response()
    except HTTPException as http_err:
        raise http_err
    except CategoriesManagerGetError as err:
        LOGGER.error("[delete_cmdb_category] %s", err, exc_info=True)
        abort(400, "Failed to retrieve a Category from the database!")
    except CategoriesManagerUpdateError as err:
        LOGGER.error("[delete_cmdb_category] %s", err, exc_info=True)
        abort(400, f"Failed to detach child Categories of the Category with ID:{public_id}!")
    except CategoriesManagerDeleteError as err:
        LOGGER.error("[delete_cmdb_category] %s", err, exc_info=True)
        abort(500, f"Child Categories were detached but deleting the Category with ID:{public_id} failed!")
    except Exception as err:
        LOGGER.error("[delete_cmdb_category] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while deleting the Category with ID: {public_id}!")
