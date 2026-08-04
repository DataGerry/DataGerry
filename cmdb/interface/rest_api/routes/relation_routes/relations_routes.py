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
Implementation of all API routes for CmdbRelations

A CmdbRelation is the DEFINITION of a relationship between two CmdbTypes; its instances are the
CmdbObjectRelations served by ``object_relation_routes``. The five routes here are the definition's
CRUD surface:

- ``POST   /relations/``            create (the public_id is server-owned, see below)
- ``GET    /relations/``            paged list
- ``GET    /relations/<public_id>`` single
- ``PUT    /relations/<public_id>`` update, plus the cascade onto its instances
- ``DELETE /relations/<public_id>`` delete, refused while instances exist

Three invariants hold across them:

1. **The identity is server-owned.** The create route drops any public_id the payload carries and the
   update route pins the document's public_id to the URL, so a body can neither choose nor rewrite a
   relation's id.
2. **The allowed CmdbTypes must exist.** Create and update refuse ids no CmdbType carries (400),
   because such a side could never be filled by any object.
3. **The cascade onto the instances is NOT atomic.** An update persists the relation first and only
   then reconciles the dependent CmdbObjectRelations (delete the ones whose type is no longer
   allowed, apply the section-field diff to the rest); a delete removes the relation and only then
   pulls it out of the CiExplorerProfiles. That order means a failed cascade leaves the relation
   already written, so those failures are reported as a partial application (500 naming what was and
   was not applied) rather than as a failed update.
"""
from logging import Logger, getLogger
from typing import Any
from flask import request, abort
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager import RelationsManager, ObjectRelationsManager, CiExplorerProfileManager, TypesManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.user_model import CmdbUser
from cmdb.models.relation_model import CmdbRelation, RelationKey
from cmdb.models.object_relation_model import ObjectRelationKey
from cmdb.framework.results import IterationResult
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.rest_api.responses import (
    InsertSingleResponse,
    GetMultiResponse,
    GetSingleResponse,
    UpdateSingleResponse,
    DeleteSingleResponse,
)
from cmdb.interface.rest_api.routes.relation_routes.relation_constants import RelationRight
from cmdb.interface.rest_api.routes.relation_routes.relations_helper import (
    apply_relation_update,
    cascade_relation_update,
    validate_relation_type_ids,
)

from cmdb.errors.manager import (
    BaseManagerDeleteError,
    BaseManagerGetError,
    BaseManagerUpdateError,
)
from cmdb.errors.manager.ci_explorer_profile_manager import CiExplorerProfileManagerUpdateError
from cmdb.errors.manager.relations_manager import (
    RelationsManagerInsertError,
    RelationsManagerGetError,
    RelationsManagerIterationError,
    RelationsManagerUpdateError,
    RelationsManagerDeleteError,
)
from cmdb.errors.manager.types_manager import TypesManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

relations_blueprint = APIBlueprint('relations', __name__)

# Number of matching CmdbObjectRelations the in-use check asks for: the existence of one is enough to
# refuse the delete, so the server may stop counting there
IN_USE_PROBE_LIMIT: int = 1

# ---------------------------------------------------- CRUD-CREATE --------------------------------------------------- #

@relations_blueprint.route('/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@relations_blueprint.protect(auth=True, right=RelationRight.ADD.value)
@relations_blueprint.validate(CmdbRelation.SCHEMA)
def insert_cmdb_relation(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to insert a CmdbRelation into the database

    The public_id is server-owned: one carried by the payload is dropped so the id always comes from
    the collection's counter, and the allowed parent / child CmdbTypes are checked to exist before
    anything is written

    Args:
        data (CmdbRelation.SCHEMA): Data of the CmdbRelation which should be inserted
        request_user (CmdbUser): CmdbUser which wants to create this CmdbRelation

    Raises:
        HTTPException: 400 if a referenced CmdbType does not exist or the insert / re-read fails,
                       500 if the created CmdbRelation cannot be read back or on any other failure

    Returns:
        InsertSingleResponse: The new CmdbRelation and its public_id
    """
    try:
        relations_manager: RelationsManager = ManagerProvider.get_manager(
            ManagerType.RELATIONS,
            request_user
        )
        types_manager: TypesManager = ManagerProvider.get_manager(
            ManagerType.TYPES,
            request_user
        )

        validate_relation_type_ids(types_manager, data)

        # The identity is server-owned: never let the payload choose the new public_id
        data.pop(RelationKey.PUBLIC_ID.value, None)

        result_id: int = relations_manager.insert_relation(data)

        created_relation: dict | None = relations_manager.get_relation(result_id)

        if created_relation:
            return InsertSingleResponse(created_relation, result_id).make_response()

        # The insert reported success, so a missing document is a server-side inconsistency
        abort(500, "The Relation was created but could not be retrieved from the database!")
    except HTTPException as http_err:
        raise http_err
    except TypesManagerGetError as err:
        LOGGER.error("[insert_cmdb_relation] TypesManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to validate the Types referenced by the Relation!")
    except RelationsManagerInsertError as err:
        LOGGER.error("[insert_cmdb_relation] RelationsManagerInsertError: %s", err, exc_info=True)
        abort(400, "Failed to insert the new Relation in the database!")
    except RelationsManagerGetError as err:
        LOGGER.error("[insert_cmdb_relation] RelationsManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve the created Relation from the database!")
    except Exception as err:
        LOGGER.error("[insert_cmdb_relation] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while creating the new Relation!")

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@relations_blueprint.route('/', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@relations_blueprint.protect(auth=True, right=RelationRight.VIEW.value)
@relations_blueprint.parse_collection_parameters()
def get_cmdb_relations(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for getting multiple CmdbRelations

    Args:
        params (CollectionParameters): Filter for requested CmdbRelations
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 400 if the iteration fails, 500 on any other failure

    Returns:
        GetMultiResponse: All the CmdbRelations matching the CollectionParameters
    """
    try:
        body = request.method == 'HEAD'

        relations_manager: RelationsManager = ManagerProvider.get_manager(
            ManagerType.RELATIONS,
            request_user
        )

        builder_params = BuilderParameters(**CollectionParameters.get_builder_params(params))

        iteration_result: IterationResult[CmdbRelation] = relations_manager.iterate(builder_params)
        relation_list = [CmdbRelation.to_json(relation) for relation in iteration_result.results]

        api_response = GetMultiResponse(relation_list,
                                        iteration_result.total,
                                        params,
                                        request.url,
                                        body)

        return api_response.make_response()
    except RelationsManagerIterationError as err:
        LOGGER.error("[get_cmdb_relations] RelationsManagerIterationError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve Relations from the database!")
    except Exception as err:
        LOGGER.error("[get_cmdb_relations] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while iterating Relations!")


@relations_blueprint.route('/<int:public_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@relations_blueprint.protect(auth=True, right=RelationRight.VIEW.value)
def get_cmdb_relation(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve a single CmdbRelation

    Args:
        public_id (int): public_id of the CmdbRelation
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 404 if no CmdbRelation carries that public_id, 400 if the lookup fails,
                       500 on any other failure

    Returns:
        GetSingleResponse: The requested CmdbRelation
    """
    try:
        relations_manager: RelationsManager = ManagerProvider.get_manager(
            ManagerType.RELATIONS,
            request_user
        )

        requested_relation: dict | None = relations_manager.get_relation(public_id)

        if requested_relation:
            return GetSingleResponse(requested_relation, body = request.method == 'HEAD').make_response()

        abort(404, f"The Relation with ID:{public_id} was not found!")
    except HTTPException as http_err:
        raise http_err
    except RelationsManagerGetError as err:
        LOGGER.error("[get_cmdb_relation] RelationsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the Relation with ID: {public_id} from the database!")
    except Exception as err:
        LOGGER.error("[get_cmdb_relation] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while retrieving Relation with ID: {public_id}!")

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@relations_blueprint.route('/<int:public_id>', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@relations_blueprint.protect(auth=True, right=RelationRight.EDIT.value)
@relations_blueprint.validate(CmdbRelation.SCHEMA)
def update_cmdb_relation(public_id: int, data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `PUT`/`PATCH` route to update a single CmdbRelation

    The relation is persisted first and its dependent CmdbObjectRelations are reconciled afterwards,
    so a failed update leaves the instances untouched. The reverse is not true: the cascade is not
    atomic, so a cascade failure is reported as a partial application (the relation IS updated)

    Args:
        public_id (int): public_id of the CmdbRelation which should be updated
        data (CmdbRelation.SCHEMA): New CmdbRelation data
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 404 if no CmdbRelation carries that public_id, 400 if a referenced CmdbType
                       does not exist or the lookup / update fails, 500 if the cascade onto the
                       CmdbObjectRelations fails after the relation was updated, or on any other
                       failure

    Returns:
        UpdateSingleResponse: The new data of the CmdbRelation
    """
    try:
        relations_manager: RelationsManager = ManagerProvider.get_manager(
            ManagerType.RELATIONS,
            request_user
        )
        object_relations_manager: ObjectRelationsManager = ManagerProvider.get_manager(
            ManagerType.OBJECT_RELATIONS,
            request_user
        )
        types_manager: TypesManager = ManagerProvider.get_manager(
            ManagerType.TYPES,
            request_user
        )

        to_update_relation: dict[str, Any] | None = relations_manager.get_relation(public_id)

        if not to_update_relation:
            abort(404, f"The Relation with ID:{public_id} was not found!")

        validate_relation_type_ids(types_manager, data)

        relation, changed_fields = apply_relation_update(public_id, data, to_update_relation, relations_manager)

        cascade_relation_update(public_id, to_update_relation, data, changed_fields, object_relations_manager)

        return UpdateSingleResponse(CmdbRelation.to_json(relation)).make_response()
    except HTTPException as http_err:
        raise http_err
    except TypesManagerGetError as err:
        LOGGER.error("[update_cmdb_relation] TypesManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to validate the Types referenced by the Relation!")
    except RelationsManagerGetError as err:
        LOGGER.error("[update_cmdb_relation] RelationsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the Relation with ID: {public_id} from the database!")
    except RelationsManagerUpdateError as err:
        LOGGER.error("[update_cmdb_relation] RelationsManagerUpdateError: %s", err, exc_info=True)
        abort(400, f"Failed to update the Relation with ID: {public_id}!")
    except (BaseManagerDeleteError, BaseManagerUpdateError) as err:
        # The relation itself is already updated at this point - report the partial application
        LOGGER.error("[update_cmdb_relation] Cascade failed: %s", err, exc_info=True)
        abort(500, f"The Relation with ID: {public_id} was updated, but its ObjectRelations could not "
                   "be updated accordingly!")
    except Exception as err:
        LOGGER.error("[update_cmdb_relation] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while updating Relation with ID: {public_id}!")

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@relations_blueprint.route('/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@relations_blueprint.protect(auth=True, right=RelationRight.DELETE.value)
def delete_cmdb_relation(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route to delete a single CmdbRelation

    A CmdbRelation still used by a CmdbObjectRelation is not deletable: deleting it would leave every
    instance pointing at a definition that no longer exists, so the request is refused with 400 (a
    business rule, not an authorisation problem). Once deleted, the relation is also pulled out of
    every CiExplorerProfile - a step that runs after the delete and is therefore reported separately
    when it fails

    Args:
        public_id (int): public_id of the CmdbRelation which should be deleted
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 404 if no CmdbRelation carries that public_id, 400 if the relation is still in
                       use or the lookup / in-use check / delete fails, 500 if the CiExplorerProfile
                       cleanup fails after the relation was deleted, or on any other failure

    Returns:
        DeleteSingleResponse: The deleted CmdbRelation data
    """
    try:
        relations_manager: RelationsManager = ManagerProvider.get_manager(
            ManagerType.RELATIONS,
            request_user
        )
        object_relations_manager: ObjectRelationsManager = ManagerProvider.get_manager(
            ManagerType.OBJECT_RELATIONS,
            request_user
        )
        ci_explorer_profile_manager: CiExplorerProfileManager = ManagerProvider.get_manager(
            ManagerType.CI_EXPLORER_PROFILE,
            request_user
        )

        to_delete_relation: dict[str, Any] | None = relations_manager.get_relation(public_id)

        if not to_delete_relation:
            abort(404, f"The Relation with ID:{public_id} was not found!")

        # Check if the CmdbRelation is currently used by any CmdbObjectRelation. One instance is
        # enough to refuse the delete, so the count stops there instead of loading a document
        instances_in_use: int = object_relations_manager.count_documents(
            {ObjectRelationKey.RELATION_ID.value: public_id},
            limit=IN_USE_PROBE_LIMIT,
        )

        if instances_in_use:
            abort(400, f"The Relation with ID:{public_id} is currently in use and cannot be deleted!")

        relations_manager.delete_relation(public_id)

        # Delete this relation from all CiExplorerProfiles
        ci_explorer_profile_manager.remove_relation_from_profiles(public_id)

        return DeleteSingleResponse(raw=to_delete_relation).make_response()
    except HTTPException as http_err:
        raise http_err
    except RelationsManagerDeleteError as err:
        LOGGER.error("[delete_cmdb_relation] RelationsManagerDeleteError: %s", err, exc_info=True)
        abort(400, f"Failed to delete the Relation with ID:{public_id}!")
    except RelationsManagerGetError as err:
        LOGGER.error("[delete_cmdb_relation] RelationsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the Relation with ID:{public_id} from the database!")
    except BaseManagerGetError as err:
        # The in-use probe failed, so whether the relation may be deleted is unknown - nothing written
        LOGGER.error("[delete_cmdb_relation] In-use check failed: %s", err, exc_info=True)
        abort(400, f"Failed to check whether the Relation with ID:{public_id} is still in use!")
    except CiExplorerProfileManagerUpdateError as err:
        # The relation is already deleted at this point - report the partial application
        LOGGER.error("[delete_cmdb_relation] CiExplorerProfile cleanup failed: %s", err, exc_info=True)
        abort(500, f"The Relation with ID:{public_id} was deleted, but could not be removed from all "
                   "CI Explorer profiles!")
    except Exception as err:
        LOGGER.error("[delete_cmdb_relation] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while deleting Relation with ID:{public_id}!")
