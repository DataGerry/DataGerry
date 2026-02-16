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
Implementation of all API routes for CmdbCategories
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
    HTTP `POST` route to insert a CmdbCategory into the database

    Args:
        data (CmdbCategory.SCHEMA): Data of the CmdbCategory which should be inserted
        request_user (CmdbUser): User requesting this data

    Returns:
        InsertSingleResponse: The new CmdbCategory and its public_id
    """
    try:
        categories_manager: CategoriesManager = ManagerProvider.get_manager(ManagerType.CATEGORIES,
                                                                            request_user)

        data.setdefault('creation_time', datetime.now(timezone.utc))

        result_id: int = categories_manager.insert_category(data)

        created_category = categories_manager.get_category(result_id)

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
@categories_blueprint.parse_collection_parameters(view='list')
def get_cmdb_categories(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for getting multiple CmdbCategories

    Args:
        params (CollectionParameters): Filter for requested CmdbCategories
        request_user (CmdbUser): User requesting this data

    Returns:
        GetMultiResponse: All the CmdbCategories matching the CollectionParameters
    """
    try:
        categories_manager: CategoriesManager = ManagerProvider.get_manager(ManagerType.CATEGORIES,
                                                                            request_user)

        body: bool = request.method == 'HEAD'

        if params.optional['view'] == 'tree':
            tree: CategoryTree = categories_manager.tree
            api_response = GetMultiResponse(CategoryTree.to_json(tree),
                                            len(tree),
                                            params,
                                            request.url,
                                            body)

            return api_response.make_response(pagination=False)

        # if view is not 'tree'
        builder_params = BuilderParameters(**CollectionParameters.get_builder_params(params))

        iteration_result: IterationResult[CmdbCategory] = categories_manager.iterate(builder_params)

        category_list: list[dict[str, Any]] = [CmdbCategory.to_json(category) for category in iteration_result.results]

        api_response = GetMultiResponse(category_list,
                                        iteration_result.total,
                                        params,
                                        request.url,
                                        body)

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
def get_cmdb_category(public_id: int, request_user: CmdbUser):
    """
    HTTP `GET`/`HEAD` route to retrieve a single CmdbCategory

    Args:
        public_id (int): public_id of the CmdbCategory
        request_user (CmdbUser): User requesting this data

    Returns:
        GetSingleResponse: The requested CmdbCategory
    """
    try:
        categories_manager: CategoriesManager = ManagerProvider.get_manager(ManagerType.CATEGORIES,
                                                                            request_user)

        requested_category = categories_manager.get_category(public_id)

        if not requested_category:
            abort(404, f"The Category with ID:{public_id} was not found!")

        return GetSingleResponse(requested_category, body = request.method == 'HEAD').make_response()
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
def update_cmdb_category(public_id: int, data: dict, request_user: CmdbUser):
    """
    HTTP `PUT`/`PATCH` route to update a single CmdbCategory

    Args:
        public_id (int): public_id of the CmdbCategory which should be updated
        data (CmdbCategory.SCHEMA): New CmdbCategory data
        request_user (CmdbUser): User requesting this data

    Returns:
        UpdateSingleResponse: The new data of the CmdbCategory
    """
    try:
        categories_manager: CategoriesManager = ManagerProvider.get_manager(ManagerType.CATEGORIES,
                                                                            request_user)

        category = CmdbCategory.from_data(data)

        to_update_category = categories_manager.get_category(public_id)

        if not to_update_category:
            abort(404, f"The Category with ID:{public_id} was not found!")

        categories_manager.update_category(public_id, category)

        return UpdateSingleResponse(result=data).make_response()
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
def delete_cmdb_category(public_id: int, request_user: CmdbUser):
    """
    HTTP `DELETE` route to delete a single CmdbCategory

    Args:
        public_id (int): public_id of the CmdbCategory which should be deleted
        request_user (CmdbUser): User requesting this data

    Returns:
        DeleteSingleResponse: The deleted CmdbCategory data
    """
    try:
        categories_manager: CategoriesManager = ManagerProvider.get_manager(ManagerType.CATEGORIES,
                                                                            request_user)

        to_delete_category = categories_manager.get_category(public_id)

        if not to_delete_category:
            abort(404, f"The Category with ID:{public_id} was not found!")

        categories_manager.delete_category(public_id)

        # Update 'parent' attribute on direct children
        categories_manager.reset_children_categories(public_id)

        return DeleteSingleResponse(raw=to_delete_category).make_response()
    except HTTPException as http_err:
        raise http_err
    except CategoriesManagerDeleteError as err:
        LOGGER.error("[delete_cmdb_category] %s", err, exc_info=True)
        abort(400, f"Failed to delete the Category with the ID:{public_id}")
    except CategoriesManagerGetError as err:
        LOGGER.error("[delete_cmdb_category] %s", err, exc_info=True)
        abort(400, "Failed not retrieve a Category from the database!")
    except CategoriesManagerUpdateError as err:
        LOGGER.error("[delete_cmdb_category] %s", err, exc_info=True)
        abort(500, "Could not update a child Category although the requested Category got deleted!")
    except Exception as err:
        LOGGER.error("[delete_cmdb_category] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while deleting the Category with ID: {public_id}!")
