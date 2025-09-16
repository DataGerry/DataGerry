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
import re
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

# --------------------------------------------------- OBJECT - SORT -------------------------------------------------- #
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

# ---------------------------------------------- OBJECT RELATION - SORT ---------------------------------------------- #

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

# --------------------------------------------- OBJECT RELATION - FILTER --------------------------------------------- #

        if view == "object_relation_filter":
            # ===== Stage 1: Build query with objectRelation filters safely =====
            query = []

            query.append({
                "$addFields": {
                    "public_id_str": {"$toString": "$public_id"}
                }
            })

            # Add normalized_fields (only for filtering)
            query.append({
                "$addFields": {
                    "normalized_fields": {
                        "$map": {
                            "input": "$fields",
                            "as": "f",
                            "in": {
                                "name": "$$f.name",
                                "value": {
                                    "$function": {
                                        "body": """
                                            function(val) {
                                                if (typeof val !== 'string') return val;
                                                var match = val.match(/<a [^>]+>(.*?)<\\/a>/i);
                                                if (match) {
                                                    return match[1]; // inner text only
                                                }
                                                return val;
                                            }
                                        """,
                                        "args": ["$$f.value"],
                                        "lang": "js"
                                    }
                                }
                            }
                        }
                    }
                }
            })
            # query.append({
            #     "$addFields": {
            #         "fields": {
            #             "$map": {
            #                 "input": "$fields",
            #                 "as": "f",
            #                 "in": {
            #                     "name": "$$f.name",
            #                     "value": {
            #                         "$cond": [
            #                             { "$regexMatch": { "input": "$$f.value", "regex": "^<a href=.*>.*</a>$" } },
            #                             {
            #                                 "$arrayElemAt": [
            #                                     { "$split": [
            #                                         { "$arrayElemAt": [ { "$split": [ "$$f.value", ">" ] }, 1 ] },
            #                                         "<"
            #                                     ] },
            #                                     0
            #                                 ]
            #                             },
            #                             "$$f.value"
            #                         ]
            #                     }
            #                 }
            #             }
            #         }
            #     }
            # })

            # query.extend(process_match_criteria(builder_params))
            # Use normalized_fields in filtering
            query.extend(process_match_criteria(builder_params))

            # Step 2: join types
            query.append({
                "$lookup": {
                    "from": "framework.types",
                    "localField": "type_id",
                    "foreignField": "public_id",
                    "as": "type"
                }
            })
            query.append({
                "$unwind": {
                    "path": "$type",
                    "preserveNullAndEmptyArrays": True
                }
            })

            # Step 3: ACL filter
            query.append({
                "$match": {
                    "$or": [
                        {"type.acl": {"$exists": False}},
                        {"type.acl.activated": False},
                        {"$and": [
                            {"type.acl.groups.includes.1": {"$exists": True}},
                            {"type.acl.groups.includes.1": {"$all": ["READ"]}}
                        ]}
                    ]
                }
            })

            # Step 4: join objectRelations
            query.append({
                "$lookup": {
                    "from": "framework.objectRelations",
                    "let": {"obj_id": "$public_id"},
                    "pipeline": [
                        {
                            "$match": {
                                "$expr": {
                                    "$or": [
                                        {"$eq": ["$relation_parent_id", "$$obj_id"]},
                                        {"$eq": ["$relation_child_id", "$$obj_id"]}
                                    ]
                                }
                            }
                        },
                        {
                            "$group": {
                                "_id": {
                                    "relation_id": "$relation_id",
                                    "direction": {
                                        "$cond": [
                                            {"$eq": ["$relation_parent_id", "$$obj_id"]},
                                            "parent",
                                            "child"
                                        ]
                                    }
                                },
                                "count": {"$sum": 1}
                            }
                        }
                    ],
                    "as": "relation_counts"
                }
            })

            # Step 5: build filter_values object
            query.append({
                "$addFields": {
                    "filter_values": {
                        "$arrayToObject": {
                            "$map": {
                                "input": "$relation_counts",
                                "as": "r",
                                "in": {
                                    "k": {"$concat": [
                                        {"$toString": "$$r._id.relation_id"},
                                        "_",
                                        "$$r._id.direction"
                                    ]},
                                    "v": {"$toString": "$$r.count"}
                                }
                            }
                        }
                    }
                }
            })

            # Stage 6: Append objectRelation count filters **after filter_values is added**
            object_relation_filters = []
            for criterion in builder_params.criteria:
                if "$match" in criterion:
                    match_value = criterion["$match"]
                    for key, value in match_value.items():
                        object_relation_filters.extend(extract_object_relation_filters(value))

            # Only append non-empty filters
            for f in object_relation_filters:
                if f:  # <- prevents empty $and/$or errors
                    query.append({"$match": f})

            # Step 7: sorting, skipping, limiting
            sort_key = builder_params.sort
            sort_order = -1 if builder_params.order == -1 else 1

            if isinstance(sort_key, str):
                # Case 1: objectRelation sort (e.g. 3_child)
                parts = sort_key.split("_")
                if len(parts) == 2 and parts[0].isdigit() and parts[1] in ["parent", "child"]:
                    sort_key = f"filter_values.{sort_key}"
                # Case 2: normalized field sort (e.g. fields.text-19742)
                elif sort_key.startswith("fields."):
                    field_name = sort_key.split(".", 1)[1]  # → text-19742
                    # Add a dedicated top-level field for sorting
                    query.append({
                        "$addFields": {
                            f"sort_field_{field_name}": {
                                "$let": {
                                    "vars": {
                                        "match": {
                                            "$arrayElemAt": [
                                                {
                                                    "$filter": {
                                                        "input": "$normalized_fields",
                                                        "as": "f",
                                                        "cond": {"$eq": ["$$f.name", field_name]}
                                                    }
                                                },
                                                0
                                            ]
                                        }
                                    },
                                    "in": "$$match.value"
                                }
                            }
                        }
                    })
                    sort_key = f"sort_field_{field_name}"
            # If sort is an objectRelation field like '3_child' or '1_parent'
            # if isinstance(sort_key, str):
            #     parts = sort_key.split("_")
            #     if len(parts) == 2 and parts[0].isdigit() and parts[1] in ["parent", "child"]:
            #         sort_key = f"filter_values.{sort_key}"

            query.append({"$sort": {sort_key: sort_order}})
            # query.append({"$sort": {builder_params.sort: -1 if builder_params.order == -1 else 1}})
            query.append({"$skip": builder_params.skip})
            query.append({"$limit": builder_params.limit})

            # Step 8: final projection
            query.append({
                "$project": {
                    "type": 0,
                    "relation_counts": 0,
                    "filter_values": 0,
                    "public_id_str": 0,
                    "normalized_fields": 0,
                    **({f"sort_field_{field_name}": 0} if "field_name" in locals() else {})
                }
            })

        # LOGGER.debug(f"query: {query}")

        result = list(objects_manager.aggregate(query))

        iteration_result: IterationResult[CmdbObject] = IterationResult(result, len(result), CmdbObject)
        # LOGGER.debug(f"iteration_result.results: {iteration_result.results}")

        result_data = RenderList(object_list=iteration_result.results,
                                    request_user=request_user,
                                    ref_render=True,
                                    objects_manager=objects_manager).render_result_list(raw=True)

        # LOGGER.debug(f"results count: {len(result_data)}")
        # LOGGER.debug(f"results: {result_data}")

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


def should_skip_elem_match(elem):
    """
    Returns True if the elemMatch is an objectRelation count field (like 1_parent, 3_child).
    Returns False for all other $elemMatch (normal fields).
    """
    if isinstance(elem, list):
        return any(should_skip_elem_match(x) for x in elem)

    if not isinstance(elem, dict):
        return False

    # Direct $elemMatch inside 'fields'
    if "fields" in elem and "$elemMatch" in elem["fields"]:
        em = elem["fields"]["$elemMatch"]
        name = em.get("name", "")
        parts = name.split("_")
        if len(parts) == 2 and parts[0].isdigit() and parts[1] in ["parent", "child"]:
            return True
        return False

    # Recursively check nested $and / $or
    for k in ["$and", "$or"]:
        if k in elem and isinstance(elem[k], list):
            # Skip only if any child is objectRelation count
            return any(should_skip_elem_match(x) for x in elem[k])

    return False


def extract_object_relation_filters(value):
    """
    Recursively walk a value (list or dict) and extract objectRelation count filters
    from $elemMatch inside fields with names like <number>_parent or <number>_child.
    Returns a list of dicts suitable for $match stage.
    """
    filters = []

    if isinstance(value, list):
        for item in value:
            filters.extend(extract_object_relation_filters(item))

    elif isinstance(value, dict):
        # Nested $and / $or
        for op in ["$and", "$or"]:
            if op in value and isinstance(value[op], list):
                # Only include non-empty filters
                nested_filters = [f for f in extract_object_relation_filters(value[op]) if f]
                filters.extend(nested_filters)

        # $elemMatch inside 'fields'
        if "fields" in value and "$elemMatch" in value["fields"]:
            em = value["fields"]["$elemMatch"]
            if isinstance(em, dict) and "name" in em:
                parts = em["name"].split("_")
                if len(parts) == 2 and parts[0].isdigit() and parts[1] in ["parent", "child"]:
                    # Only include valid objectRelation filters
                    filters.append({f"filter_values.{em['name']}": em["value"]})

    return filters

# def process_match_criteria(builder_params, fields_key="fields"):
#     query = []
#     for criterion in builder_params.criteria:
#         if "$match" in criterion:
#             match_condition = criterion["$match"]

#             if "$or" in match_condition:
#                 for or_item in match_condition["$or"]:
#                     if "$and" in or_item:
#                         for and_item in or_item["$and"]:
#                             if should_skip_elem_match(and_item):
#                                 continue
#                             if fields_key != "fields" and "fields" in and_item:
#                                 and_item[fields_key] = and_item.pop("fields")
#                             query.append({"$match": and_item})
#                     else:
#                         if should_skip_elem_match(or_item):
#                             continue
#                         if fields_key != "fields" and "fields" in or_item:
#                             or_item[fields_key] = or_item.pop("fields")
#                         query.append({"$match": or_item})
#             else:
#                 new_match = {}
#                 for key, value in match_condition.items():
#                     if should_skip_elem_match({key: value}):
#                         continue
#                     new_match[key] = value
#                 if new_match:
#                     query.append({"$match": new_match})
#     return query




def process_match_criteria(builder_params):
    """
    Processes builder_params.criteria and builds $match stages for normal fields.
    ObjectRelation count filters (like '1_parent', '3_child') are skipped and handled later.
    Returns a list of $match stages for the pipeline.
    """
    query = []

    for criterion in builder_params.criteria:
        if "$match" in criterion:
            match_condition = criterion["$match"]

            # Case: $or in match_condition
            if "$or" in match_condition:
                for or_item in match_condition["$or"]:
                    if "$and" in or_item:
                        for and_item in or_item["$and"]:
                            if should_skip_elem_match(and_item):
                                continue

                            # Normalize regex on public_id
                            if (
                                "public_id" in and_item
                                and isinstance(and_item["public_id"], dict)
                                and "$regex" in and_item["public_id"]
                            ):
                                and_item["public_id_str"] = and_item.pop("public_id")

                            # Redirect fields → normalized_fields
                            if "fields" in and_item:
                                and_item["normalized_fields"] = and_item.pop("fields")

                            query.append({"$match": and_item})

                    else:
                        if should_skip_elem_match(or_item):
                            continue

                        if (
                            "public_id" in or_item
                            and isinstance(or_item["public_id"], dict)
                            and "$regex" in or_item["public_id"]
                        ):
                            or_item["public_id_str"] = or_item.pop("public_id")

                        if "fields" in or_item:
                            or_item["normalized_fields"] = or_item.pop("fields")

                        query.append({"$match": or_item})

            else:
                # Normal $match
                new_match = {}
                for key, value in match_condition.items():
                    if should_skip_elem_match({key: value}):
                        continue

                    if key == "public_id" and isinstance(value, dict) and "$regex" in value:
                        new_match["public_id_str"] = value
                    elif key == "fields":
                        new_match["normalized_fields"] = value
                    else:
                        new_match[key] = value

                if new_match:
                    query.append({"$match": new_match})

    return query



# # working one
# def process_match_criteria(builder_params):
#     """
#     Processes builder_params.criteria and builds $match stages for normal fields.
#     ObjectRelation count filters (like '1_parent', '3_child') are skipped and handled later.
#     Returns a list of $match stages for the pipeline.
#     """
#     query = []

#     for criterion in builder_params.criteria:
#         if "$match" in criterion:
#             match_condition = criterion["$match"]

#             # Check if this $match has an $or containing an $and (objectRelation + normal fields)
#             if "$or" in match_condition:
#                 for or_item in match_condition["$or"]:
#                     if "$and" in or_item:
#                         for and_item in or_item["$and"]:
#                             if should_skip_elem_match(and_item):
#                                 continue  # skip objectRelation count filters
#                             if "public_id" in and_item and isinstance(and_item["public_id"], dict) and "$regex" in and_item["public_id"]:
#                                 and_item["public_id_str"] = and_item.pop("public_id")
#                             query.append({"$match": and_item})
#                     else:
#                         if should_skip_elem_match(or_item):
#                             continue
#                         if "public_id" in or_item and isinstance(or_item["public_id"], dict) and "$regex" in or_item["public_id"]:
#                             or_item["public_id_str"] = or_item.pop("public_id")
#                         query.append({"$match": or_item})
#             else:
#                 # Normal $match, just skip objectRelation count filters
#                 new_match = {}
#                 for key, value in match_condition.items():
#                     if should_skip_elem_match({key: value}):
#                         continue
#                     new_match[key] = value
#                 if new_match:
#                     query.append({"$match": new_match})

#     return query
