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
Implementation of all API routes for CmdbObjects
"""
from logging import Logger, getLogger
from flask import abort, request
from werkzeug.exceptions import HTTPException

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager import (
    ObjectsManager,
)

from cmdb.models.user_model import CmdbUser
from cmdb.models.object_model import CmdbObject
from cmdb.framework.results import IterationResult
from cmdb.framework.rendering.render_list import RenderList
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.rest_api.responses import GetMultiResponse
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters

# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

itsa_blueprint = APIBlueprint('itsa', __name__)

# -------------------------------------------------------------------------------------------------------------------- #

@itsa_blueprint.route('/search', methods=['GET', 'HEAD'])
@itsa_blueprint.parse_collection_parameters(view='object')
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@itsa_blueprint.protect(auth=True, right='base.framework.object.view')
def search_objects(params: CollectionParameters, request_user: CmdbUser):
    """
    TODO: document
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

        view = params.optional.get('view', 'object')

        # LOGGER.debug(f"view: {view}")

        if _fetch_only_active_objs():
            if isinstance(params.filter, dict):
                params.filter = [{'$match': params.filter}]
                params.filter.append({'$match': {'active': {"$eq": True}}})
            elif isinstance(params.filter, list):
                params.filter.append({'$match': {'active': {"$eq": True}}})

        builder_params = BuilderParameters(**CollectionParameters.get_builder_params(params))

        # LOGGER.debug(f"builder_params: {builder_params}")

        # BuilderParameters(
        #     criteria=[{'$match': {'type_id': 1}}, {'$match': {'active': {'$eq': True}}}],
        #     limit=25,
        #     skip=0,
        #     sort='fields.text-19742',
        #     order=1
        # )

        query = builder_params.criteria
        sort_stage = {'$sort': {builder_params.sort: builder_params.order}}

        if view == 'object':
            if builder_params.get_sort().startswith('fields'):
                sort_value = builder_params.get_sort()[7:]
                query.extend([
                    {
                        '$addFields': {
                            'order_field': {
                                '$arrayElemAt': [
                                    {
                                        '$filter': {
                                            'input': '$fields',
                                            'as': 'f',
                                            'cond': {'$eq': ['$$f.name', sort_value]}
                                        }
                                    },
                                    0
                                ]
                            }
                        }
                    },
                    {
                        '$addFields': {
                            'order_value': '$order_field.value'
                        }
                    }
                ])

                sort_stage = {'$sort': {'order_value': builder_params.order}}

            query.extend([
                {'$lookup': {
                        'from': 'framework.types',
                        'localField': 'type_id',
                        'foreignField': 'public_id',
                        'as': 'type'
                    }
                },
                {'$unwind': {'path': '$type', 'preserveNullAndEmptyArrays': True}},
                {'$match': {'$or': [
                    {'type.acl': {'$exists': False}},
                    {'type.acl.activated': False},
                    {'$and': [
                        {'type.acl.groups.includes.1': {'$exists': True}},
                        {'type.acl.groups.includes.1': {'$all': ['READ']}}
                    ]}
                ]}},
                sort_stage
            ])

            if builder_params.skip > 0:
                query.append({'$skip': builder_params.skip})

            query.append({'$limit': builder_params.limit})


        if view == 'object_relation':
            relation_id, direction = builder_params.sort.split("_", 1)

            relation_id = int(relation_id)
            query.extend([
                # Join with types
                {
                    '$lookup': {
                        'from': 'framework.types',
                        'localField': 'type_id',
                        'foreignField': 'public_id',
                        'as': 'type'
                    }
                },
                {'$unwind': {'path': '$type', 'preserveNullAndEmptyArrays': True}},

                # ACL filtering
                {
                    '$match': {
                        '$or': [
                            {'type.acl': {'$exists': False}},
                            {'type.acl.activated': False},
                            {
                                '$and': [
                                    {'type.acl.groups.includes.1': {'$exists': True}},
                                    {'type.acl.groups.includes.1': {'$all': ['READ']}}
                                ]
                            }
                        ]
                    }
                },
                {
                    '$lookup': {
                        'from': 'framework.objectRelations',
                        'let': { 'obj_id': '$public_id' },
                        'pipeline': [
                            {
                                '$match': {
                                    '$expr': {
                                        '$or': [
                                            { '$eq': [ '$relation_parent_id', '$$obj_id' ] },
                                            { '$eq': [ '$relation_child_id', '$$obj_id' ] }
                                        ]
                                    }
                                }
                            },
                            {
                                '$group': {
                                    '_id': {
                                        'relation_id': '$relation_id',
                                        'direction': {
                                            '$cond': [
                                                { '$eq': [ '$relation_parent_id', '$$obj_id' ] },
                                                'parent',
                                                'child'
                                            ]
                                        }
                                    },
                                    'count': { '$sum': 1 }
                                }
                            }
                        ],
                        'as': 'relation_counts'
                    }
                },

                # Expose the counter for a specific relation+direction
                {
                    '$addFields': {
                        'relation_sort_value': {
                            '$reduce': {
                                'input': '$relation_counts',
                                'initialValue': 0,
                                'in': {
                                    '$cond': [
                                        {
                                            '$and': [
                                                { '$eq': [ '$$this._id.relation_id', relation_id ] },
                                                { '$eq': [ '$$this._id.direction', direction ] }
                                            ]
                                        },
                                        '$$this.count',
                                        '$$value'
                                    ]
                                }
                            }
                        }
                    }
                },

                #  Sort by that specific counter
                { '$sort': { 'relation_sort_value': builder_params.order } },  # or 1 for ascending
            ])

            if builder_params.skip > 0:
                query.append({'$skip': builder_params.skip})

            query.append({'$limit': builder_params.limit})

        # LOGGER.debug(f"query: {query}")

        result = list(objects_manager.aggregate(query))

        iteration_result: IterationResult[CmdbObject] = IterationResult(result, len(result), CmdbObject)
        # LOGGER.debug(f"iteration_result.results: {iteration_result.results}")

        result_data = RenderList(object_list=iteration_result.results,
                                    request_user=request_user,
                                    ref_render=True,
                                    objects_manager=objects_manager).render_result_list(raw=True)

        api_response = GetMultiResponse(result_data,
                                        total=iteration_result.total,
                                        params=params,
                                        url=request.url,
                                        body=request.method == 'HEAD')

        return api_response.make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[search_objects] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while searching/filtering Objects!")

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

def _fetch_only_active_objs() -> bool:
    """
    Checking if request have cookie parameter for object active state
    Returns:
        True if cookie is set or value is true else false
    """
    if request.args.get('onlyActiveObjCookie') is not None:
        value = request.args.get('onlyActiveObjCookie')
        return value in ['True', 'true']

    return False
