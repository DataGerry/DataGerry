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
This module contains the implementation of the ObjectsManager
"""
from logging import Logger, getLogger
import json
from typing import Any

from bson import Regex, json_util
from pymongo import UpdateOne
from pymongo.command_cursor import CommandCursor

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_utils import object_hook
from cmdb.manager.query_builder import Builder
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.base_manager import BaseManager

from cmdb.models.object_model import CmdbObject
from cmdb.models.object_group_model import ObjectReferenceType
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.models.isms_model import IsmsControlMeasureAssignment, IsmsRiskAssessment
from cmdb.security.acl.helpers import verify_access
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.framework.results import IterationResult

from cmdb.errors.manager import (
    BaseManagerGetError,
    BaseManagerIterationError,
    BaseManagerUpdateError,
    BaseManagerDeleteError,
)
from cmdb.errors.manager.objects_manager import (
    ObjectsManagerInitError,
    ObjectsManagerGetError,
    ObjectsManagerGetTypeError,
    ObjectsManagerDeleteError,
    ObjectsManagerInsertError,
    ObjectsManagerUpdateError,
    ObjectsManagerIterationError,
    ObjectsManagerMdsReferencesError,
    ObjectsManagerCheckError,
    ObjectsManagerSummaryLineError,
)
from cmdb.errors.models.cmdb_object import (
    CmdbObjectInitFromDataError,
)
from cmdb.errors.models.cmdb_type import CmdbTypeInitFromDataError
from cmdb.errors.security import AccessDeniedError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                ObjectsManager - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class ObjectsManager(BaseManager):
    """
    The ObjectsManager manages the interaction between CmdbObjects and the database

    Extends: BaseMaanger
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        """
        Set the database connection for the ObjectsManager

        Args:
            dbm (MongoDatabaseManager): Database interaction manager
            database (str | None): Name of the database to which the 'dbm' should connect. Only used in CLOUD_MODE

        Raises:
            ObjectsManagerInitError: If the ObjectsManager could not be initialised
        """
        try:
            super().__init__(CmdbObject.COLLECTION, dbm, database)
        except Exception as err:
            raise ObjectsManagerInitError(str(err)) from err

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

    def insert_object(
        self,
        data: dict[str, Any],
        user: CmdbUser | None = None,
        permission: AccessControlPermission | None = None
    ) -> int:
        """
        Insert a CmdbObject into the database

        Args:
            data (dict): New CmdbObject data as a dict
            user (CmdbUser | None): CmdbUser requesting the action
            permission (AccessControlPermission | None): Extended CmdbUser ACL rights

        Raises:
            ObjectsManagerInsertError: If an error occured during insertion
            AccessDeniedError: If the CmdbUser does not have the permission for this action

        Returns:
            int: The public_id of the created CmdbObject
        """
        try:
            new_object: CmdbObject = CmdbObject.from_data(data)

            object_type = self.get_object_type(new_object.type_id)

            if not object_type:
                raise ObjectsManagerInsertError("CmdbType of CmdbObject not found in database!")

            if not object_type.active:
                raise AccessDeniedError(
                    f'Objects cannot be created because type `{object_type.name}` is deactivated.'
                )

            verify_access(object_type, user, permission)

            return self.insert(CmdbObject.to_json(new_object))
        except AccessDeniedError as err:
            raise err
        except Exception as err:
            LOGGER.error("[insert_object] Exception: %s. Type: %s", err, type(err))
            raise ObjectsManagerInsertError(str(err)) from err


    def bulk_update_multi_data_sections(self, updated_objects: list[CmdbObject]) -> None:
        """
        Bulk updates the multi_data_sections field for a list of updated CmdbObjects.

        Args:
            updated_objects (list[CmdbObject]): Objects that have modified multi_data_sections.

        Raises:
            BaseManagerUpdateError: If the bulk write fails.
        """
        try:
            if not updated_objects:
                return

            operations: list[UpdateOne] = [
                UpdateOne(
                    {"public_id": obj.public_id},
                    {"$set": {"multi_data_sections": obj.multi_data_sections}}
                )
                for obj in updated_objects
            ]

            self.bulk_write(operations)
        except Exception as err:
            LOGGER.error("[bulk_update_multi_data_sections] Exception: %s. Type: %s", err, type(err))
            raise ObjectsManagerInsertError(str(err)) from err

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def get_object(
        self,
        public_id: int,
        user: CmdbUser | None = None,
        permission: AccessControlPermission | None = None,
        as_dict: bool = True
    ) -> dict[str, Any] | CmdbObject | None:
        """
        Retrieves a CmdbObject from the database

        Args:
            public_id (int): public_id of the CmdbObject
            user (CmdbUser | None): CmdbUser requesting the CmdbObject or None
            permission (AccessControlPermission | None): Extended CmdbUser ACL rights or None
            as_dict (bool): If true the CmdbObject is returned as dictionary else as an CmdbObject
            
        Raises:
            AccessDeniedError: If the CmdbUser does not have the permission for this action
            ObjectsManagerGetError: When a CmdbObject could not be retrieved

        Returns:
            dict[str, Any] | Cmdbobject | None: The CmdbObject either as object or dict if found else None
        """
        try:
            requested_object = self.get_one(public_id)

            if requested_object:
                requested_object = CmdbObject.from_data(requested_object)
                object_type = self.get_object_type(requested_object.type_id)
                verify_access(object_type, user, permission)

                return CmdbObject.to_json(requested_object) if as_dict else requested_object

            return None
        except AccessDeniedError as err:
            raise err
        except Exception as err:
            LOGGER.error("[get_object] Exception: %s. Type: %s", err, type(err))
            raise ObjectsManagerGetError(str(err)) from err


    def iterate(
        self,
        builder_params: BuilderParameters,
        user: CmdbUser | None = None,
        permission: AccessControlPermission | None = None
    ) -> IterationResult[CmdbObject]:
        """
        Retrieves multiple CmdbObjects

        Args:
            builder_params (BuilderParameters): Filter for which CmdbObjects should be retrieved
            user (CmdbUser | None): CmdbUser requesting the action
            permission (AccessControlPermission | None): Extended CmdbUser ACL rights

        Raises:
            ObjectsManagerIterationError: When the iteration failed

        Returns:
            IterationResult[CmdbObject]: All CmdbObjects matching the filter
        """
        try:
            aggregation_result, total = self.iterate_query(builder_params, user, permission)

            iteration_result: IterationResult[CmdbObject] = IterationResult(aggregation_result,
                                                                            total,
                                                                            CmdbObject)
            return iteration_result
        except Exception as err:
            LOGGER.error("[iterate] Exception: %s. Type: %s", err, type(err))
            raise ObjectsManagerIterationError(str(err)) from err


    def get_objects_by(
        self,
        sort: str = "public_id",
        direction: int = -1,
        user: CmdbUser | None = None,
        permission: AccessControlPermission | None = None,
        **requirements,
    ) -> list[CmdbObject]:
        """
        Retrieves a list of CmdbObjects based on the provided filters

        This method fetches objects using the specified sorting and filter criteria, then filters them
        by verifying user access permissions. The resulting list contains only the objects the user 
        has access to

        Args:
            sort (str): The field by which to sort the results. Defaults to 'public_id'
            direction (int): The direction of sorting; -1 for descending, 1 for ascending. Defaults to -1
            user (CmdbUser | None): The user for access control verification. Defaults to None
            permission (AccessControlPermission | None): The required permission
            **requirements: Additional filter criteria passed as keyword arguments

        Raises:
            ObjectsManagerGetError: If an error occurs while retrieving or processing the objects

        Returns:
            List[CmdbObject]: A list of CmdbObjects the user has access to
        """
        try:
            valid_objects = []

            objects = self.get_many(sort=sort, direction=direction, **requirements)

            for obj in objects:
                cur_object = CmdbObject.from_data(obj)

                cur_type = self.get_object_type(cur_object.type_id)

                try:
                    verify_access(cur_type, user, permission)
                    valid_objects.append(cur_object)
                except Exception:
                    # Skip objects that the user doesn't have access to
                    continue

            return valid_objects
        except AccessDeniedError as err:
            raise err
        except Exception as err:
            LOGGER.error("[get_objects_by] Exception: %s. Type: %s", err, type(err))
            raise ObjectsManagerGetError(err) from err


    def group_objects_by_value(
        self,
        value: str,
        match: dict | None = None,
        user: CmdbUser | None = None,
        permission: AccessControlPermission | None = None
    ) -> list[dict]:
        """
        Groups objects based on a specific field value and filters them by the provided criteria,
        ensuring the user has the necessary access permissions for each object.

        This method performs an aggregation operation to group documents by a specific field 
        and then sorts the grouped results by their count in descending order. The resulting
        objects are verified for user access before being returned.

        Args:
            value (str): The field by which to group the objects (e.g., 'type_id')
            match (dict | None): Filtering criteria to apply to the documents before grouping
            user (CmdbUser | None): The user making the request
            permission (AccessControlPermission | None): The required permissions for the user

        Raises:
            ObjectsManagerIterationError: If the iteration fails

        Returns:
            List[Dict]: A list of objects grouped by the specified field, containing the documents 
                        that meet the selection criteria and pass the access control checks
        """
        try:
            grouped_objects = []
            aggregation_pipeline = []

            if match:
                aggregation_pipeline.append({'$match': match})

            aggregation_pipeline.append({
                '$group': {
                    '_id': f'${value}',
                    'result': {'$first': '$$ROOT'},
                    'count': {'$sum': 1},
                }
            })

            aggregation_pipeline.append({'$sort': {'count': -1}})

            objects = self.aggregate_objects(aggregation_pipeline)

            for obj in objects:
                cur_object = CmdbObject.from_data(obj['result'])

                try:
                    cur_type = self.get_object_type(cur_object.type_id)
                    verify_access(cur_type, user, permission)
                    grouped_objects.append(obj)
                except Exception:
                    # If access verification fails, skip this object
                    continue

            return grouped_objects
        except Exception as err:
            LOGGER.error("[group_objects_by_value] Exception: %s. Type: %s", err, type(err))
            raise ObjectsManagerIterationError(str(err)) from err


    def get_object_type(self, type_id: int, as_dict: bool = False) -> dict[str, Any] | CmdbType | None:
        """
        Retrieves the CmdbType with the given public_id

        Args:
            type_id (int): public_id of the CmdbType
            as_dict(bool = False): If True the CmdbType will be returned as a dictionary instead of a CmdbType

        Raises:
            ObjectsManagerGetTypeError: If the CmdbType could not be retrieved or initialised
            ObjectsManagerGetTypeError: If an unexpected Exception occurs

        Returns:
            dict[str, Any], CmdbType | None: CmdbType with the given type_id either as dict or object if found
                                             in database else None
        """
        try:
            requested_type: dict[str, Any] | None = self.get_one_from_other_collection(CmdbType.COLLECTION, type_id)

            if requested_type:
                requested_type: CmdbType = CmdbType.from_data(requested_type)

                if as_dict:
                    requested_type: dict[str, Any] = CmdbType.to_json(requested_type)

                return requested_type

            return None
        except (BaseManagerGetError, CmdbTypeInitFromDataError) as err:
            raise ObjectsManagerGetTypeError(str(err)) from err
        except Exception as err:
            LOGGER.error("[get_object_type] Exception: %s, Type: %s", err, type(err))
            raise ObjectsManagerGetTypeError(str(err)) from err


    def find_objects(
            self,
            criteria: dict[str, Any],
            as_dict: bool = False
        ) -> list[CmdbObject] | list[dict[str, Any]]:
        """
        Get a list of CmdbObjects by a filter

        Args:
            criteria: Filter which should be applied during the search
            as_dict (bool = False): If True the list will contain dictionaries instead of CmdbObjects

        Raises:
            ObjectsManagerGetError: When the retrieval of CmdbObjects failed

        Returns:
            list[CmdbType] | list[dict[str, Any]]: list of CmdbObjects matching the criteria
        """
        try:
            found_objects: dict[str, Any] = list(self.find(criteria=criteria))

            if as_dict:
                return found_objects

            return [CmdbObject.from_data(found_object) for found_object in found_objects]
        except Exception as err:
            LOGGER.error("[find_objects] Exception: %s. Type: %s", err, type(err))
            raise ObjectsManagerGetError(str(err)) from err


    def get_new_object_public_id(self) -> int:
        """
        Gets the next couter for the public_id from database and increases it

        Raises:
            ObjectsManagerGetError: If operation fails

        Returns:
            int: The next public_id for a CmdbObject
        """
        try:
            return self.get_next_public_id(inc_id=True)
        except BaseManagerGetError as err:
            raise ObjectsManagerGetError(str(err)) from err


    def aggregate_objects(self, pipeline: list[dict], **kwargs) -> CommandCursor:
        """
        Executes an aggregation pipeline on the database to process and retrieve CmdbObjects

        This method wraps the `aggregate` function, applying the given aggregation pipeline 
        and handling potential iteration errors

        Args:
            pipeline (list[dict]): A list of aggregation stages to be executed on the database
            **kwargs: Additional keyword arguments to be passed to the aggregation function

        Raises:
            ObjectsManagerIterationError: If an error occurs during the aggregation process

        Returns:
            CommandCursor: The result of the aggregation query
        """
        try:
            return self.aggregate(pipeline=pipeline, **kwargs)
        except BaseManagerIterationError as err:
            raise ObjectsManagerIterationError(err) from err


    #TODO: REFACTOR-FIX
    def get_mds_references_for_object(self,
                                      referenced_object: CmdbObject,
                                      query_filter: dict | list) -> list[dict]:
        """
        Retrieves all CmdbObjects whose multi-data sections (MDS) reference a given object

        This method constructs an aggregation pipeline to find CmdbObject that contain reference 
        fields pointing to the specified `referenced_object`

        Args:
            referenced_object (CmdbObject): The CmdbObject being referenced
            query_filter (dict | list): Additional query filters to apply in the pipeline. 
                                              Can be a dictionary (single filter) or a list of filters

        Raises:
            ObjectsManagerIterationError: If the iteration fails

        Returns:
            list[dict]: A list of CmdbObjects that reference the given `referenced_object` in their 
                        multi-data sections
        """
        try:
            object_type_id = referenced_object.type_id

            query_pipeline = []

            if isinstance(query_filter, dict):
                query_pipeline.append(query_filter)
            elif isinstance(query_filter, list):
                for filter_item in query_filter:
                    if "$match" in filter_item and filter_item["$match"]:
                        if "type_id" in filter_item["$match"]:
                            filter_type_id = filter_item["$match"]["type_id"]
                            del filter_item["$match"]["type_id"]
                            filter_item["$match"]["public_id"] = filter_type_id

                query_pipeline += query_filter

            # Get all types which reference this type
            query_pipeline.append({'$match': {"$and": [
                                        {"fields.type": "ref"},
                                        {"fields.ref_types": object_type_id}
                                    ]}
                        })

            # Filter the public_id's of these types
            query_pipeline.append({'$project': {"public_id": 1, "_id": 0}})

            # Get all objects of these types
            query_pipeline.append(Builder.lookup_(_from='framework.objects',
                                        _local='public_id',
                                        _foreign='type_id',
                                        _as='type_objects'))

            # Filter out types which don't have any objects
            query_pipeline.append({'$match': {"type_objects.0": {"$exists": True}}})

            # Spread out the arrays
            query_pipeline.append(Builder.unwind_({'path': '$type_objects'}))

            # Filter the objects which actually have any multi section data
            query_pipeline.append({'$match': {"type_objects.multi_data_sections.0": {"$exists": True}}})

            # Remove the public_id field
            query_pipeline.append({'$project': {"type_objects": 1}})

            # Spread out as a list
            query_pipeline.append({'$replaceRoot': {"newRoot": '$type_objects'}})

            query_pipeline.append({'$project': {"_id": 0}})

            results = list(self.aggregate_from_other_collection(CmdbType.COLLECTION, query_pipeline))

            matching_results = []

            # Check if the mds data references the current object
            for result in results:
                try:
                    for mds_entry in result.get("multi_data_sections", []):
                        for value in mds_entry.get("values", []):
                            data_set: dict
                            for data_set in value.get("data", []):
                                if (
                                    self.is_ref_field(data_set["name"], result)
                                    and "value" in data_set
                                    and data_set["value"] == referenced_object.public_id
                                ):
                                    matching_results.append(result)
                                    # this result is a match => go back to outer loop
                                    raise StopIteration()
                except StopIteration:
                    pass
                except ObjectsManagerCheckError as err:
                    raise BaseManagerIterationError(err) from err

            return matching_results
        except Exception as err:
            LOGGER.error("[get_mds_references_for_object] Exception: %s, Type: %s", err, type(err))
            raise ObjectsManagerIterationError(err) from err


    #TODO: REFACTOR-FIX
    def references(
        self,
        object_: CmdbObject,
        criteria: dict,
        limit: int,
        skip: int,
        sort: str,
        order: int,
        user: CmdbUser = None,
        permission: AccessControlPermission = None
    ) -> IterationResult[CmdbObject]:
        """
        Retrieves all CmdbObjects that reference the given CmdbObject

        This method searches for references to `object_` in both:
        1. Object fields that are marked as references (`ref` type fields)
        2. Render metadata sections that define a reference section (`ref-section`)

        Additionally, it merges results from multi-data section (MDS) references

        Args:
            object_ (CmdbObject): The CmdbObject whose references are being retrieved
            criteria (Dict): A filter to apply when querying for references
            limit (int): The maximum number of results to return
            skip (int): The number of results to skip (for pagination)
            sort (str): The field by which to sort the results
            order (int): The sorting order (1 for ascending, -1 for descending)
            user (CmdbUser | None): The requesting user (for access control)
            permission (AccessControlPermission | None): The required permission level

        Raises:
            ObjectsManagerIterationError: If iteration fails

        Returns:
            IterationResult[CmdbObject]: A paginated and sorted collection of CmdbObjects
            that reference the given object
        """
        try:
            query = []

            if isinstance(criteria, dict):
                query.append(criteria)
            elif isinstance(criteria, list):
                query += criteria

            # Lookup related types by joining with the 'framework.types' collection
            query.append(Builder.lookup_(_from='framework.types', _local='type_id', _foreign='public_id', _as='type'))
            query.append(Builder.unwind_({'path': '$type', 'preserveNullAndEmptyArrays': True}))

            # Define reference conditions for both field-based and section-based references
            field_ref_query = {
                    'type.fields.type': 'ref',
                    '$or': [
                        {'type.fields.ref_types': Regex(f'.*{object_.type_id}.*', 'i')},
                        {'type.fields.ref_types': object_.type_id}
                    ]
            }

            section_ref_query = {
                    'type.render_meta.sections.type': 'ref-section',
                    'type.render_meta.sections.reference.type_id': object_.type_id
            }

            query.append(Builder.match_(Builder.or_([field_ref_query, section_ref_query])))
            query.append(Builder.match_({'fields.value': object_.public_id}))

            builder_params = BuilderParameters(criteria=query, sort=sort, order=order)

            # limit and skip will be handled when merged with the MDS results in '__merge_mds_references()'
            result = self.iterate(builder_params, user, permission)
            mds_result = self.get_mds_references_for_object(object_, criteria)

            merge_result = self.__merge_mds_references(mds_result, result, limit, skip, sort, order)

            return merge_result
        except ObjectsManagerMdsReferencesError as err:
            raise ObjectsManagerIterationError(err) from err
        except ObjectsManagerIterationError as err:
            raise err
        except Exception as err:
            LOGGER.error("[references] Exception: %s, Type: %s", err, type(err))
            raise ObjectsManagerIterationError(err) from err


    def get_grouped_objects_for_types(self, type_ids: list[int]) -> dict[int, list[CmdbObject]]:
        """
        Grouping all existing objects by the given public_ids of CmdbTypes

        Args:
            type_ids (list[int]): All public_ids of CmdbTypes which should be considered

        Returns:
            dict[int, list[CmdbObject]]: Dictionary with grouped CmdbObjects

        Example:
            {
                1: [Obj1, Obj2],
                2: [Obj3, Obj4],
            }
        """
        try:
            objects_of_types: list[CmdbObject] = self.find_objects(criteria={'type_id': {"$in": type_ids}})

            # Group objects
            objects_by_type: dict[int, list[CmdbObject]] = {}

            for obj in objects_of_types:
                objects_by_type.setdefault(obj.type_id, []).append(obj)

            return objects_by_type
        except ObjectsManagerGetError as err:
            LOGGER.error("[get_grouped_objects_for_types] ObjectsManagerGetError: %s", err)
            raise
        except Exception as err:
            LOGGER.error("[get_grouped_objects_for_types] Exception: %s, Type: %s", err, type(err))
            raise ObjectsManagerGetError(str(err)) from err


    def get_objects_lookup(self, public_ids: list[int]) -> dict[int, CmdbObject]:
        """TODO: document"""
        all_objects: list[CmdbObject] = self.find_objects(criteria={"public_id": {"$in": public_ids}})

        return {obj.public_id: obj for obj in all_objects}

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

    def update_object(self,
                      public_id: int,
                      data: CmdbObject | dict,
                      user: CmdbUser = None,
                      permission: AccessControlPermission = None) -> None:
        """
        Updates a CmdbObject in the database

        Args:
            public_id (int): public_id of the CmdbObject which should be updated
            data: (CmdbObject | dict): The new data for the CmdbObject
            user (CmdbUser): Request user
            permission (AccessControlPermission): ACL permission

        Raises:
            ObjectsManagerUpdateError: If the update operation fails
            AccessDeniedError: If the CmdbUser does not have the permission for this action
        """
        try:
            if isinstance(data, CmdbObject):
                instance = CmdbObject.to_json(data)
            else:
                instance = json.loads(json.dumps(data, default=json_util.default), object_hook=object_hook)

            object_type = self.get_object_type(instance.get('type_id'))

            if not object_type.active:
                raise AccessDeniedError(
                    f'Objects cannot be updated because type `{object_type.name}` is deactivated.'
                )
            verify_access(object_type, user, permission)

            self.update({'public_id': public_id}, instance)
        except AccessDeniedError as err:
            raise err
        except Exception as err:
            LOGGER.error("[update_object] Exception: %s, Type: %s", err, type(err))
            raise ObjectsManagerUpdateError(err) from err


    def update_many_objects(self, query: dict, update: dict, add_to_set: bool = False) -> None:
        """
        Update multiple CmdbObjects that match the given filter

        Args:
            query (dict): The filter criteria to select the CmdbObjects to update
            update (dict): The changes to apply to the matching CmdbObjects
            add_to_set (bool): If True, uses `$addToSet` to append unique values 
                                         to an array field instead of overwriting. Defaults to False

        Raises:
            ObjectsManagerUpdateError: If an error occurs during the update operation
        """
        try:
            self.update_many(criteria=query, update=update, add_to_set=add_to_set)
        except BaseManagerUpdateError as err:
            raise ObjectsManagerUpdateError(err) from err

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_object(self,
                      public_id: int,
                      user: CmdbUser = None,
                      permission: AccessControlPermission = None) -> bool:
        """
        Deletes a CmdbObject by its public_id after verifying access and type status

        Args:
            public_id (int): public_id of the CmdbObject which should be deleted
            user (CmdbUser | None): The CmdbUser requesting deletion
            permission (AccessControlPermission | None): The required permission for deletion

        Raises:
            AccessDeniedError: If the object's type is deactivated or the user lacks permission
            ObjectsManagerDeleteError: If any issue occurs during retrieval or deletion

        Returns:
            bool: True if the CmdbObject was successfully deleted, False otherwise
        """
        try:
            to_delete_object = self.get_object(public_id)

            if not to_delete_object:
                return False

            type_id = CmdbObject.from_data(to_delete_object).type_id

            object_type = self.get_object_type(type_id)

            if not object_type.active:
                raise AccessDeniedError(
                    f'Objects cannot be removed because type `{object_type.name}` is deactivated.'
                )

            verify_access(object_type, user, permission)

            return self.delete({'public_id': public_id})
        except AccessDeniedError as err:
            raise err
        except (ObjectsManagerGetError, BaseManagerDeleteError, CmdbObjectInitFromDataError) as err:
            raise ObjectsManagerDeleteError(err) from err
        except Exception as err:
            LOGGER.error("[delete_object] Exception: %s, Type: %s", err, type(err))
            raise ObjectsManagerDeleteError(err) from err


    def delete_with_follow_up(
            self, public_id: int,
            user: CmdbUser = None,
            permission: AccessControlPermission = None
        ) -> bool:
        """
        Deletes a CmdbObject by its public_id after verifying access and type status and also deletes
        RiskAssessments using this Object!

        Args:
            public_id (int): public_id of the CmdbObject which should be deleted
            user (CmdbUser | None): The CmdbUser requesting deletion
            permission (AccessControlPermission | None): The required permission for deletion

        Raises:
            AccessDeniedError: If the object's type is deactivated or the user lacks permission
            ObjectsManagerDeleteError: If any issue occurs during retrieval or deletion

        Returns:
            bool: True if the CmdbObject was successfully deleted, False otherwise
        """
        self.delete_object_from_risk_assessment_cascade(public_id)

        return self.delete_object(public_id, user, permission)


    def delete_all_object_references(self, public_ids: int | list[int]) -> None:
        """
        Remove one or multiple public_id references from all objects.
        Only fields with type 'ref' or 'ref-section-field' are affected.
        Also removes references inside multi_data_sections.
        """
        try:
            if not public_ids:
                raise ObjectsManagerUpdateError("No public ids provided to delete from references!")

            if isinstance(public_ids, list):
                if not public_ids:
                    return

                ids_filter: dict[str, list[int]] = {"$in": public_ids}
            else:
                ids_filter: int = public_ids

            # Remove from normal fields
            filter_query: dict[str, Any] = {
                "fields": {
                    "$elemMatch": {
                        "type": {"$in": ["ref", "ref-section-field"]},
                        "value": ids_filter,
                    }
                }
            }

            update: dict[str, Any] = {
                "$set": {
                    "fields.$[f].value": ""
                }
            }

            array_filters: list[dict[str, Any]] = [
                {
                    "f.type": {"$in": ["ref", "ref-section-field"]},
                    "f.value": ids_filter,
                }
            ]

            self.update_many_raw(
                filter_query=filter_query,
                update=update,
                array_filters=array_filters,
            )

            # Remove from multi_data_sections[].values[].data[]
            filter_query_multi: dict[str, Any] = {
                "multi_data_sections.values.data": {
                    "$elemMatch": {
                        "type": {"$in": ["ref", "ref-section-field"]},
                        "value": ids_filter,
                    }
                }
            }

            update_multi: dict[str, Any] = {
                "$set": {
                    "multi_data_sections.$[].values.$[].data.$[f].value": ""
                }
            }

            array_filters_multi: list[dict[str, Any]] = [
                {
                    "f.type": {"$in": ["ref", "ref-section-field"]},
                    "f.value": ids_filter,
                }
            ]

            self.update_many_raw(
                filter_query=filter_query_multi,
                update=update_multi,
                array_filters=array_filters_multi,
            )
        except Exception as err:
            LOGGER.error("[delete_all_object_references] Exception: %s, Type: %s", err, type(err))
            raise ObjectsManagerUpdateError(str(err)) from err

    # def delete_all_object_references(self, public_ids: int | list[int]) -> None:
    #     """
    #     Remove one or multiple public_id references from all objects. Only fields with type 'ref' or
    #     'ref-section-field' are affected

    #     Args:
    #         public_ids(int | list[int]): public_id or list of public_ids which should be removed from references

    #     Raises:
    #         ObjectsManagerUpdateError: When no public_ids are provided
    #         ObjectsManagerUpdateError: If the removal of the referenced public_ids failed
    #     """
    #     try:
    #         if not public_ids:
    #             raise ObjectsManagerUpdateError("No public ids provided to delete from references!")

    #         if isinstance(public_ids, list):
    #             if not public_ids:
    #                 return

    #             ids_filter: dict[str, list[int]] = {"$in": public_ids}
    #         else:
    #             ids_filter: int = public_ids

    #         filter_query: dict[str, Any] = {
    #             "fields": {
    #                 "$elemMatch": {
    #                     "type": {"$in": ["ref", "ref-section-field"]},
    #                     "value": ids_filter,
    #                 }
    #             }
    #         }

    #         update: dict[str, Any] = {
    #             "$set": {
    #                 "fields.$[f].value": ""
    #             }
    #         }

    #         array_filters: list[dict[str, Any]] = [
    #             {
    #                 "f.type": {"$in": ["ref", "ref-section-field"]},
    #                 "f.value": ids_filter,
    #             }
    #         ]

    #         self.update_many_raw(
    #             filter_query=filter_query,
    #             update=update,
    #             array_filters=array_filters,
    #         )
    #     except Exception as err:
    #         LOGGER.error("[delete_all_object_references] Exception: %s, Type: %s", err, type(err))
    #         raise ObjectsManagerUpdateError(str(err)) from err

# ------------------------------------------------- HELPER FUNCTIONS ------------------------------------------------- #

    def delete_object_from_risk_assessment_cascade(self, deleted_object_id: int) -> None:
        """
        Deletes all RiskAssessments and their associated ControlMeasureAssignments that reference 
        the given CmdbObjectGroup.

        This function performs the following steps:
        1. Finds all RiskAssessments where 'object_id_ref_type' is 'OBJECT_GROUP' and 
        'object_id' matches the deleted group ID
        2. Deletes these RiskAssessments
        3. Deletes all ControlMeasureAssignments referencing the deleted RiskAssessments

        Args:
            deleted_group_id (int): The public_id of the deleted CmdbObjectGroup
        """
        # Find all RiskAssessments referencing this Object
        risk_assessment_query: dict[str, Any] = {
            'object_id_ref_type': ObjectReferenceType.OBJECT,
            'object_id': deleted_object_id
        }

        matching_risk_assessments: list[dict[str, Any]] = list(self.dbm.find(
            IsmsRiskAssessment.COLLECTION,
            self.db_name,
            risk_assessment_query,
            projection={'public_id': 1}
        ))

        if not matching_risk_assessments:
            return

        # Collect all RiskAssessment public_ids
        risk_assessment_ids = [ra['public_id'] for ra in matching_risk_assessments]

        if risk_assessment_ids:
            # Delete the RiskAssessments
            self.dbm.delete_many(
                IsmsRiskAssessment.COLLECTION,
                self.db_name,
                **{'public_id': {'$in': risk_assessment_ids}},
            )

            # Delete all ControlMeasureAssignments referencing those RiskAssessments
            self.dbm.delete_many(
                IsmsControlMeasureAssignment.COLLECTION,
                self.db_name,
                **{'risk_assessment_id': {'$in': risk_assessment_ids}},
            )


    #pylint: disable=R0917
    def __merge_mds_references(self,
                                mds_result: list,
                                obj_result: IterationResult,
                                limit: int,
                                skip: int,
                                sort: str,
                                order: int) -> IterationResult:
        """
        Merges MDS references into the existing object result set while ensuring uniqueness.
        The merged results are sorted and paginated as per the given parameters

        Args:
            mds_result (list[dict]): List of multi-data section references
            obj_result (IterationResult): Existing objects retrieved via normal references
            limit (int): Maximum number of objects to return (0 for no limit)
            skip (int): Number of objects to skip (for pagination)
            sort (str): Attribute name to sort by
            order (int): Sorting order (-1 for descending, 1 for ascending)

        Raises:
            ObjectsManagerMdsReferencesError: If the merge of references failed

        Returns:
            IterationResult: Merged, sorted, and paginated result set
        """
        try:
            # get public_id's of all currently referenced objects as a set
            referenced_ids = {obj.public_id for obj in obj_result.results}

            # add MDS objects to normal references if they are not already referenced
            for ref_obj in mds_result:
                new_obj = CmdbObject.from_data(ref_obj)
                if new_obj.public_id not in referenced_ids:
                    obj_result.results.append(new_obj)
                    referenced_ids.add(new_obj.public_id)

            obj_result.total = len(obj_result.results)

            # sort all findings according to sort and order
            descending_order = order == -1

            obj_result.results.sort(key=lambda obj: getattr(obj, sort, None), reverse=descending_order)

            # just keep the given limit of objects if limit > 0
            if limit > 0:
                list_length = limit + skip

                # if the list_length is longer than the object_list then just set it to len(object_list)
                list_length = min(list_length, len(obj_result.results))

                obj_result.results = obj_result.results[skip:list_length]

            return obj_result
        except Exception as err:
            LOGGER.error("[__merge_mds_references] Exception: %s, Type: %s", err, type(err))
            raise ObjectsManagerMdsReferencesError(err) from err


    def is_ref_field(self, field_name: str, ref_object: dict) -> bool:
        """
        Checks if the given field in the referenced object is of type 'ref'

        Args:
            field_name (str): The name of the field to check
            referenced_object (dict): The referenced object containing the field's information

        Raises:
            ObjectsManagerCheckError: If the field could not be checked

        Returns:
            bool: True if the field is a reference field, otherwise False
        """
        try:
            ref_type = self.get_object_type(ref_object["type_id"])

            for field in ref_type.fields:
                if field["name"] == field_name and field["type"] == "ref":
                    return True

            return False
        except ObjectsManagerGetError as err:
            raise ObjectsManagerCheckError(err) from err
        except Exception as err:
            LOGGER.error("[is_ref_field] Exception: %s, Type: %s", err, type(err))
            raise ObjectsManagerCheckError(err) from err


    def get_summary_line(self, public_id: int, with_type: bool = True) -> str:
        """
        Retrieves the summary line of an CmdbObject

        Args:
            public_id (int): public_id of the CmdbObject
            with_type (bool): If True then the Type label should be part of the summary line

        Returns:
            str: The summary line of the CmdbObject
        """
        try:
            default_line: str = ""

            if not public_id:
                return default_line

            target_object = self.get_object(public_id)

            if not target_object:
                return default_line

            object_type_id = target_object.get('type_id')

            target_object_type = self.get_object_type(object_type_id)

            if not target_object_type:
                return default_line

            if with_type:
                default_line = f"{target_object_type.label} #{target_object.get('public_id')}"
            else:
                default_line = f"#{target_object.get('public_id')}"

            if not target_object_type.has_summaries():
                return default_line

            summary_line = default_line

            try:
                summary_fields = target_object_type.get_summary().fields
                first = True

                line:dict
                for line in summary_fields:
                    field_name = line.get('name')
                    field_value = next(
                        (field['value'] for field in target_object['fields'] if field['name'] == field_name), None
                    )

                    if first:
                        summary_line += f' - {field_value}'
                        first = False
                    else:
                        summary_line += f' | {field_value}'
            except Exception as err:
                LOGGER.debug(
                    "Failed to build summary line for Object-ID: %s and Type-ID: %s. Error: %s!",
                    target_object.get('public_id'),
                    target_object_type.public_id,
                    err
                )
                summary_line = default_line

            return summary_line
        except Exception as err:
            raise ObjectsManagerSummaryLineError(err) from err


    # def get_reference_field_names_from_type(self, type_schema: dict) -> set[str]:
    #     """TODO: document"""
    #     return {
    #         field["name"]
    #         for field in type_schema.get("fields", [])
    #         if field.get("type") in {"ref", "ref-section-field"}
    #     }
