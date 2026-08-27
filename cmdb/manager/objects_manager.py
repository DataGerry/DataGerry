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
import copy
import json
from typing import Any

from bson import json_util
from pymongo import UpdateOne
from pymongo.command_cursor import CommandCursor

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_utils import object_hook
from cmdb.manager.query_builder import Builder
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.base_manager import BaseManager

from cmdb.models.object_model import (
    CmdbObject,
    CmdbObjectKey,
    CmdbObjectFieldKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
)
from cmdb.models.object_group_model import ObjectReferenceType
from cmdb.models.type_model import CmdbType
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.section_type_enum import SectionType
from cmdb.models.user_model import CmdbUser
from cmdb.models.isms_model import IsmsControlMeasureAssignment, IsmsRiskAssessment
from cmdb.security.acl.helpers import verify_access
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.framework.results import IterationResult

from cmdb.errors.manager import (
    BaseManagerGetError,
    BaseManagerIterationError,
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

    Owns the CmdbObject CRUD surface (create / read / update / delete) plus the higher-level
    read helpers built on top of it: reference resolution (field- and MDS-based) via ``references``,
    per-type grouping and counting, batched type/object lookups used to avoid N+1 access checks,
    summary-line composition, and the delete-time cascades that scrub object references and remove
    dependent ISMS RiskAssessments / ControlMeasureAssignments. Access control is enforced through
    ``verify_access`` against each object's CmdbType, and every failure is surfaced as a typed
    ``ObjectsManager*Error``

    Extends: BaseManager
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
            ObjectsManagerUpdateError: If the bulk write fails.
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
            raise ObjectsManagerUpdateError(str(err)) from err

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


    def iterate_results(
        self,
        builder_params: BuilderParameters,
        user: CmdbUser | None = None,
        permission: AccessControlPermission | None = None
    ) -> list[CmdbObject]:
        """
        Retrieves multiple CmdbObjects WITHOUT running the total-count aggregation

        The counterpart of ``iterate`` for callers that consume only the rows: it returns the models
        directly instead of an IterationResult, so there is no total to report and the second
        aggregation ``iterate`` pays for is never run. Use ``iterate`` whenever the total is needed
        (paginated responses); use this for a full result set that is simply handed on

        Args:
            builder_params (BuilderParameters): Filter for which CmdbObjects should be retrieved
            user (CmdbUser | None): CmdbUser requesting the action
            permission (AccessControlPermission | None): Extended CmdbUser ACL rights

        Raises:
            ObjectsManagerIterationError: When the iteration failed

        Returns:
            list[CmdbObject]: All CmdbObjects matching the filter
        """
        try:
            aggregation_result: list[dict[str, Any]] = self.aggregate_query(builder_params, user, permission)

            return [CmdbObject.from_data(result) for result in aggregation_result]
        except Exception as err:
            LOGGER.error("[iterate_results] Exception: %s. Type: %s", err, type(err))
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
            cmdb_objects: list[CmdbObject] = [CmdbObject.from_data(obj) for obj in objects]

            # Batch-load the types once instead of one get_object_type call per object (no N+1):
            # a type query for thousands of same-type objects collapses to a single lookup
            types_lookup: dict[int, CmdbType] = self._load_types_lookup(
                list({cur_object.type_id for cur_object in cmdb_objects})
            )

            for cur_object in cmdb_objects:
                cur_type = types_lookup.get(cur_object.type_id)

                try:
                    verify_access(cur_type, user, permission)
                    valid_objects.append(cur_object)
                except AccessDeniedError:
                    # Skip objects the user does not have access to (other errors propagate)
                    continue

            return valid_objects
        except AccessDeniedError as err:
            raise err
        except Exception as err:
            LOGGER.error("[get_objects_by] Exception: %s. Type: %s", err, type(err))
            raise ObjectsManagerGetError(str(err)) from err


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
                except AccessDeniedError:
                    # If access verification fails, skip this object (other errors propagate)
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
            as_dict: bool = False,
            projection: dict[str, Any] | None = None,
        ) -> list[CmdbObject] | list[dict[str, Any]]:
        """
        Get a list of CmdbObjects by a filter

        Args:
            criteria: Filter which should be applied during the search
            as_dict (bool = False): If True the list will contain dictionaries instead of CmdbObjects
            projection (dict[str, Any] | None): Optional Mongo projection limiting the returned
                fields. Only valid together with as_dict=True - a partial document cannot be
                deserialized into a CmdbObject

        Raises:
            ObjectsManagerGetError: When the retrieval of CmdbObjects failed, or when a
                projection is combined with as_dict=False

        Returns:
            list[CmdbObject] | list[dict[str, Any]]: list of CmdbObjects matching the criteria
        """
        if projection is not None and not as_dict:
            raise ObjectsManagerGetError("'projection' requires as_dict=True!")

        try:
            if projection is not None:
                # Preserve the default '_id' exclusion the projection-less path applies in
                # MongoDatabaseManager.find, unless the caller addressed '_id' explicitly
                safe_projection: dict[str, Any] = {'_id': 0, **projection}
                found_objects: list[dict[str, Any]] = list(self.find(criteria=criteria, projection=safe_projection))
            else:
                found_objects = list(self.find(criteria=criteria))

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
            raise ObjectsManagerIterationError(str(err)) from err


    def count_objects_grouped_by_type(self) -> dict[int, int]:
        """
        Counts all CmdbObjects grouped by their type_id

        Uses a single ``$group`` aggregation (one round-trip) instead of one count per type, so it
        scales independently of the number of CmdbTypes. Types that currently have no objects are
        absent from the result

        Raises:
            ObjectsManagerIterationError: If the aggregation fails

        Returns:
            dict[int, int]: Mapping of type_id to the number of CmdbObjects of that type
        """
        return self.count_objects_grouped_by_type_with_total()[0]


    def count_objects_grouped_by_type_with_total(self) -> tuple[dict[int, int], int]:
        """
        Counts all CmdbObjects grouped by their type_id and returns the exact overall total

        The per-type mapping drops groups whose ``_id`` is not an int (a document with a missing or
        malformed ``type_id`` cannot be attributed to a CmdbType), but the total counts **every**
        document, so it always matches an unfiltered ``count_documents()``. Callers that need both
        numbers - the Service Portal config-item sync needs the breakdown and the total - get them
        from this one aggregation instead of paying for a separate full-collection count

        Raises:
            ObjectsManagerIterationError: If the aggregation fails

        Returns:
            tuple[dict[int, int], int]: The type_id -> count mapping and the total object count
        """
        pipeline: list[dict[str, Any]] = [
            {"$group": {"_id": f"${CmdbObjectKey.TYPE_ID.value}", "count": {"$sum": 1}}}
        ]

        cursor: CommandCursor = self.aggregate_objects(pipeline)

        counts_by_type: dict[int, int] = {}
        total: int = 0

        for doc in cursor:
            count: int = doc["count"]
            total += count

            if isinstance(doc.get("_id"), int):
                counts_by_type[doc["_id"]] = count

        return counts_by_type, total


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

            # Work on a copy: the caller (references()) shares this filter with its own query, so
            # the type_id -> public_id swap below must not mutate the caller's filter in place
            query_filter = copy.deepcopy(query_filter)

            if isinstance(query_filter, dict):
                query_pipeline.append(query_filter)
            elif isinstance(query_filter, list):
                for filter_item in query_filter:
                    if "$match" in filter_item and filter_item["$match"]:
                        if CmdbObjectKey.TYPE_ID.value in filter_item["$match"]:
                            filter_type_id = filter_item["$match"][CmdbObjectKey.TYPE_ID.value]
                            del filter_item["$match"][CmdbObjectKey.TYPE_ID.value]
                            filter_item["$match"][CmdbObjectKey.PUBLIC_ID.value] = filter_type_id

                query_pipeline += query_filter

            # Get all types which reference this type
            query_pipeline.append({'$match': {"$and": [
                                        {"fields.type": FieldType.REFERENCE.value},
                                        {"fields.ref_types": object_type_id}
                                    ]}
                        })

            # Filter the public_id's of these types
            query_pipeline.append({'$project': {"public_id": 1, "_id": 0}})

            # Get all objects of these types
            query_pipeline.append(Builder.lookup_(from_collection='framework.objects',
                                                  local_field='public_id',
                                                  foreign_field='type_id',
                                                  as_field='type_objects'))

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

            return self._filter_mds_results_referencing(results, referenced_object.public_id)
        except Exception as err:
            LOGGER.error("[get_mds_references_for_object] Exception: %s, Type: %s", err, type(err))
            raise ObjectsManagerIterationError(str(err)) from err


    def _ref_field_names_by_type(self, type_ids: list[int]) -> dict[int, set[str]]:
        """
        Resolves the set of 'ref'-type field names for each given CmdbType, in one batch

        Replaces a per-row type lookup with a single batched load so MDS-reference checking does
        not round-trip to the database for every candidate object

        Args:
            type_ids (list[int]): The CmdbType public_ids to resolve

        Returns:
            dict[int, set[str]]: Mapping of type public_id to the names of its 'ref'-type fields
        """
        types_lookup: dict[int, CmdbType] = self._load_types_lookup(type_ids)

        return {
            type_id: {
                field[CmdbObjectFieldKey.NAME.value]
                for field in cmdb_type.fields
                if field.get(CmdbObjectFieldKey.TYPE.value) == FieldType.REFERENCE.value
            }
            for type_id, cmdb_type in types_lookup.items()
        }


    def _filter_mds_results_referencing(self, results: list[dict], referenced_public_id: int) -> list[dict]:
        """
        Keeps only the result objects whose MDS rows reference the given object via a ref field

        Args:
            results (list[dict]): Candidate CmdbObject documents (must carry multi_data_sections)
            referenced_public_id (int): public_id the MDS ref field must point at

        Returns:
            list[dict]: The subset of results that reference the given object in their MDS data
        """
        # Pre-resolve the ref-field names per type once instead of per MDS row (no N+1 type fetch)
        result_type_ids: list[int] = list({
            result.get(CmdbObjectKey.TYPE_ID.value)
            for result in results
            if isinstance(result.get(CmdbObjectKey.TYPE_ID.value), int)
        })
        ref_field_names_by_type: dict[int, set[str]] = self._ref_field_names_by_type(result_type_ids)

        matching_results: list[dict] = []

        for result in results:
            ref_field_names: set[str] = ref_field_names_by_type.get(result.get(CmdbObjectKey.TYPE_ID.value), set())

            if self._mds_rows_reference(result, ref_field_names, referenced_public_id):
                matching_results.append(result)

        return matching_results


    @staticmethod
    def _mds_rows_reference(result: dict, ref_field_names: set[str], referenced_public_id: int) -> bool:
        """
        Reports whether any MDS row of the object holds a ref field pointing at the given id

        Args:
            result (dict): A CmdbObject document carrying multi_data_sections
            ref_field_names (set[str]): Names of the object type's 'ref'-type fields
            referenced_public_id (int): public_id the ref field must point at

        Returns:
            bool: True if any MDS ref field references the given object
        """
        for mds_entry in result.get(CmdbObjectKey.MULTI_DATA_SECTIONS.value, []):
            for value in mds_entry.get(CmdbObjectMdsKey.VALUES.value, []):
                for data_set in value.get(CmdbObjectMdsRowKey.DATA.value, []):
                    if (
                        data_set.get(CmdbObjectFieldKey.NAME.value) in ref_field_names
                        and data_set.get(CmdbObjectFieldKey.VALUE.value) == referenced_public_id
                    ):
                        return True

        return False


    # The reference query exposes the full pagination/sort surface (limit/skip/sort/order) plus the
    # target object and the ACL user/permission, so the argument count is inherent to the contract
    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def references(
        self,
        object_: CmdbObject,
        criteria: dict,
        limit: int,
        skip: int,
        sort: str,
        order: int,
        user: CmdbUser | None = None,
        permission: AccessControlPermission | None = None
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
            query.append(Builder.lookup_(from_collection='framework.types',
                                         local_field='type_id',
                                         foreign_field='public_id',
                                         as_field='type'))
            query.append(Builder.unwind_({'path': '$type', 'preserveNullAndEmptyArrays': True}))

            # Keep only objects whose type references object_'s type and which point at its public_id
            query.append(Builder.match_(Builder.or_(self._build_reference_match_queries(object_))))
            query.append(Builder.match_({'fields.value': object_.public_id}))

            builder_params = BuilderParameters(criteria=query, sort=sort, order=order)

            # limit and skip will be handled when merged with the MDS results in '__merge_mds_references()'
            result = self.iterate(builder_params, user, permission)
            mds_result = self.get_mds_references_for_object(object_, criteria)

            merge_result = self.__merge_mds_references(mds_result, result, limit, skip, sort, order)

            return merge_result
        except ObjectsManagerMdsReferencesError as err:
            raise ObjectsManagerIterationError(str(err)) from err
        except ObjectsManagerIterationError as err:
            raise err
        except Exception as err:
            LOGGER.error("[references] Exception: %s, Type: %s", err, type(err))
            raise ObjectsManagerIterationError(str(err)) from err


    @staticmethod
    def _build_reference_match_queries(object_: CmdbObject) -> list[dict[str, Any]]:
        """
        Builds the field-based and section-based reference match queries for ``references()``

        Both match against the joined 'type' document. ref_types is always a list of integer type
        public_ids, so an exact match is correct (the former substring-regex alternative never
        matched a numeric field anyway)

        Args:
            object_ (CmdbObject): The object whose referencing objects are being searched

        Returns:
            list[dict[str, Any]]: The field-ref and section-ref match queries, for an `$or`
        """
        field_ref_query: dict[str, Any] = {
            'type.fields.type': FieldType.REFERENCE.value,
            'type.fields.ref_types': object_.type_id,
        }

        section_ref_query: dict[str, Any] = {
            'type.render_meta.sections.type': SectionType.REF_SECTION.value,
            'type.render_meta.sections.reference.type_id': object_.type_id,
        }

        return [field_ref_query, section_ref_query]


    def get_objects_lookup(self, public_ids: list[int]) -> dict[int, CmdbObject]:
        """
        Batch-loads the CmdbObjects for the given public_ids and returns them keyed by public_id

        Issues a single query over all ids instead of one lookup per id

        Args:
            public_ids (list[int]): The CmdbObject public_ids to load

        Returns:
            dict[int, CmdbObject]: Mapping of public_id to its CmdbObject for every id that resolved
        """
        all_objects: list[CmdbObject] = self.find_objects(criteria={"public_id": {"$in": public_ids}})

        return {obj.public_id: obj for obj in all_objects}

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

    def update_object(self,
                      public_id: int,
                      data: CmdbObject | dict,
                      user: CmdbUser | None = None,
                      permission: AccessControlPermission | None = None,
                      partial: bool = False) -> None:
        """
        Updates a CmdbObject in the database

        Args:
            public_id (int): public_id of the CmdbObject which should be updated
            data: (CmdbObject | dict): The new data for the CmdbObject
            user (CmdbUser): Request user
            permission (AccessControlPermission): ACL permission
            partial (bool): If True, `data` holds only the top-level keys to set - a targeted $set
                instead of a full-document write, so a concurrent edit of another field survives. The
                type_id then comes from the stored object, both guards below still apply, and the
                caller owns the pipeline this skips (version bump, log, webhook). Defaults to False

        Raises:
            ObjectsManagerUpdateError: If the update operation fails
            AccessDeniedError: If the CmdbUser does not have the permission for this action
        """
        try:
            if isinstance(data, CmdbObject):
                instance = CmdbObject.to_json(data)
            else:
                instance = json.loads(json.dumps(data, default=json_util.default), object_hook=object_hook)

            if partial:
                stored_object = self.get_one(public_id)

                if not stored_object:
                    raise ObjectsManagerUpdateError(f"No CmdbObject with ID: {public_id} found!")

                type_id = stored_object.get('type_id')
            else:
                type_id = instance.get('type_id')

            object_type = self.get_object_type(type_id)

            if not object_type:
                raise ObjectsManagerUpdateError("CmdbType of CmdbObject not found in database!")

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
            raise ObjectsManagerUpdateError(str(err)) from err

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_object(self,
                      public_id: int,
                      user: CmdbUser | None = None,
                      permission: AccessControlPermission | None = None,
                      object_type: CmdbType | None = None) -> bool:
        """
        Deletes a CmdbObject by its public_id after verifying access and type status

        Args:
            public_id (int): public_id of the CmdbObject which should be deleted
            user (CmdbUser | None): The CmdbUser requesting deletion
            permission (AccessControlPermission | None): The required permission for deletion
            object_type (CmdbType | None): The object's already-resolved CmdbType. When given, the
                internal type lookup is skipped - lets bulk callers that already hold a type map
                avoid one ``get_object_type`` query per object (no functional change: the same
                type is used for the deactivated-check and the ACL verification)

        Raises:
            AccessDeniedError: If the object's type is deactivated or the user lacks permission
            ObjectsManagerDeleteError: If any issue occurs during retrieval or deletion

        Returns:
            bool: True if the CmdbObject was successfully deleted, False otherwise
        """
        try:
            # get_one (raw) instead of get_object: get_object would fetch the type internally for
            # its own access check, so we'd resolve the type twice. We fetch it once below
            to_delete_object = self.get_one(public_id)

            if not to_delete_object:
                return False

            type_id = CmdbObject.from_data(to_delete_object).type_id

            # Reuse a caller-supplied type when present (bulk-delete N+1 avoidance), else resolve it
            if object_type is None:
                object_type = self.get_object_type(type_id)

            if not object_type:
                raise ObjectsManagerDeleteError("CmdbType of CmdbObject not found in database!")

            if not object_type.active:
                raise AccessDeniedError(
                    f'Objects cannot be removed because type `{object_type.name}` is deactivated.'
                )

            verify_access(object_type, user, permission)

            return self.delete({'public_id': public_id})
        except AccessDeniedError as err:
            raise err
        except (ObjectsManagerGetError, BaseManagerDeleteError, CmdbObjectInitFromDataError) as err:
            raise ObjectsManagerDeleteError(str(err)) from err
        except Exception as err:
            LOGGER.error("[delete_object] Exception: %s, Type: %s", err, type(err))
            raise ObjectsManagerDeleteError(str(err)) from err


    def delete_with_follow_up(
            self, public_id: int,
            user: CmdbUser | None = None,
            permission: AccessControlPermission | None = None,
            object_type: CmdbType | None = None
        ) -> bool:
        """
        Deletes a CmdbObject by its public_id after verifying access and type status and also deletes
        RiskAssessments using this Object!

        Args:
            public_id (int): public_id of the CmdbObject which should be deleted
            user (CmdbUser | None): The CmdbUser requesting deletion
            permission (AccessControlPermission | None): The required permission for deletion
            object_type (CmdbType | None): The object's already-resolved CmdbType, forwarded to
                ``delete_object`` to skip its internal type lookup (see ``delete_object``)

        Raises:
            AccessDeniedError: If the object's type is deactivated or the user lacks permission
            ObjectsManagerDeleteError: If any issue occurs during retrieval or deletion

        Returns:
            bool: True if the CmdbObject was successfully deleted, False otherwise
        """
        self.delete_object_from_risk_assessment_cascade(public_id)

        return self.delete_object(public_id, user, permission, object_type)


    def delete_all_object_references(self, public_ids: int | list[int]) -> None:
        """
        Scrubs references to one or more deleted CmdbObjects from every other CmdbObject

        Clears the value of any 'ref' or 'ref-section-field' field that points at one of the given
        public_ids, in both the regular ``fields`` and the ``multi_data_sections`` rows, using two
        bulk ``update_many_raw`` writes (regular fields, then MDS rows). A cleared reference becomes
        an empty string. An empty list is a no-op

        Args:
            public_ids (int | list[int]): A single object public_id or a list of them whose
                references should be removed from all other objects

        Raises:
            ObjectsManagerUpdateError: If no public_ids are provided (falsy scalar), or when either
                bulk write fails
        """
        try:
            if isinstance(public_ids, list):
                # An empty list is a no-op rather than an error (nothing to scrub)
                if not public_ids:
                    return

                ids_filter: dict[str, list[int]] = {"$in": public_ids}
            elif public_ids:
                ids_filter: int = public_ids
            else:
                raise ObjectsManagerUpdateError("No public ids provided to delete from references!")

            # Both plain ref fields and ref-section fields hold object references
            ref_field_types: list[str] = [FieldType.REFERENCE.value, FieldType.REF_SECTION.value]

            # Remove from normal fields
            filter_query: dict[str, Any] = {
                "fields": {
                    "$elemMatch": {
                        "type": {"$in": ref_field_types},
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
                    "f.type": {"$in": ref_field_types},
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
                        "type": {"$in": ref_field_types},
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
                    "f.type": {"$in": ref_field_types},
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


    def set_location_field_for_objects(self, object_ids: list[int], parent_id: int | None) -> None:
        """
        Sets the location-type field value on the given CmdbObjects to a parent location id

        An object's location field stores the public_id of its parent CmdbLocation (its placement),
        mirrored onto the object's CmdbLocation node's `parent`. This bulk-updates that value in
        place for every listed object - used when the objects' location nodes are re-parented (e.g.
        their parent location was deleted and its children were promoted) so the mirrored object
        field keeps pointing at the correct parent. Passing None clears the placement. The location
        field is identified by its type (a CmdbType has at most one location field)

        Args:
            object_ids (list[int]): public_ids of the CmdbObjects whose location field should be set
            parent_id (int | None): The new parent CmdbLocation id, or None to clear the placement

        Raises:
            ObjectsManagerUpdateError: If the update fails
        """
        if not object_ids:
            return

        try:
            self.update_many_raw(
                filter_query={
                    "public_id": {"$in": object_ids},
                    "fields": {"$elemMatch": {"type": FieldType.LOCATION.value}},
                },
                update={"$set": {"fields.$[f].value": parent_id}},
                array_filters=[{"f.type": FieldType.LOCATION.value}],
            )
        except Exception as err:
            LOGGER.error("[set_location_field_for_objects] Exception: %s, Type: %s", err, type(err))
            raise ObjectsManagerUpdateError(str(err)) from err


    def clear_location_field_for_objects(self, object_ids: list[int]) -> None:
        """
        Clears the location-type field value on the given CmdbObjects

        Convenience wrapper around set_location_field_for_objects with no placement (None). Used when
        surviving objects' location nodes are removed and the objects should no longer reference any
        parent location

        Args:
            object_ids (list[int]): public_ids of the CmdbObjects whose location field should be cleared
        """
        self.set_location_field_for_objects(object_ids, None)

# ------------------------------------------------- HELPER FUNCTIONS ------------------------------------------------- #

    def delete_object_from_risk_assessment_cascade(self, deleted_object_id: int) -> None:
        """
        Deletes all RiskAssessments and their ControlMeasureAssignments that reference an Object

        Performed in three steps:
        1. Find all RiskAssessments whose 'object_id_ref_type' is OBJECT and whose 'object_id'
           matches the deleted object's public_id
        2. Delete those RiskAssessments
        3. Delete all ControlMeasureAssignments referencing the deleted RiskAssessments

        Args:
            deleted_object_id (int): The public_id of the deleted CmdbObject
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
            self.delete_many_from_other_collection(
                IsmsRiskAssessment.COLLECTION,
                {'public_id': {'$in': risk_assessment_ids}}
            )

            # Delete all ControlMeasureAssignments referencing those RiskAssessments
            self.delete_many_from_other_collection(
                IsmsControlMeasureAssignment.COLLECTION,
                {'risk_assessment_id': {'$in': risk_assessment_ids}}
            )


    def delete_objects_from_risk_assessment_cascade(self, deleted_object_ids: list[int]) -> None:
        """
        Batched variant of ``delete_object_from_risk_assessment_cascade`` for a list of objects

        Deletes every RiskAssessment referencing ANY of the given objects, plus all their
        ControlMeasureAssignments, using a single ``$in`` query per collection instead of the
        per-object round-trips that calling the single-object cascade in a loop would issue.
        The net effect is identical to invoking the single-object cascade for each id

        Args:
            deleted_object_ids (list[int]): public_ids of the deleted CmdbObjects
        """
        if not deleted_object_ids:
            return

        # Find all RiskAssessments referencing any of these Objects in one query
        risk_assessment_query: dict[str, Any] = {
            'object_id_ref_type': ObjectReferenceType.OBJECT,
            'object_id': {'$in': deleted_object_ids},
        }

        matching_risk_assessments: list[dict[str, Any]] = list(self.dbm.find(
            IsmsRiskAssessment.COLLECTION,
            self.db_name,
            risk_assessment_query,
            projection={'public_id': 1},
        ))

        if not matching_risk_assessments:
            return

        risk_assessment_ids: list[int] = [ra['public_id'] for ra in matching_risk_assessments]

        # Delete the RiskAssessments
        self.delete_many_from_other_collection(
            IsmsRiskAssessment.COLLECTION,
            {'public_id': {'$in': risk_assessment_ids}},
        )

        # Delete all ControlMeasureAssignments referencing those RiskAssessments
        self.delete_many_from_other_collection(
            IsmsControlMeasureAssignment.COLLECTION,
            {'risk_assessment_id': {'$in': risk_assessment_ids}},
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

            # sort all findings according to sort and order. The key wraps the value in a
            # (is-None, value) tuple so objects whose sort attribute is missing/None sort
            # consistently to one end instead of raising a TypeError on a None-vs-value
            # comparison (Python 3); objects that DO carry the attribute keep their natural order
            descending_order = order == -1

            def _sort_key(obj: CmdbObject) -> tuple[bool, Any]:
                value: Any = getattr(obj, sort, None)
                return (value is None, value)

            obj_result.results.sort(key=_sort_key, reverse=descending_order)

            # just keep the given limit of objects if limit > 0
            if limit > 0:
                list_length = limit + skip

                # if the list_length is longer than the object_list then just set it to len(object_list)
                list_length = min(list_length, len(obj_result.results))

                obj_result.results = obj_result.results[skip:list_length]

            return obj_result
        except Exception as err:
            LOGGER.error("[__merge_mds_references] Exception: %s, Type: %s", err, type(err))
            raise ObjectsManagerMdsReferencesError(str(err)) from err


    def _compose_summary_line(
        self,
        target_object: dict[str, Any],
        target_object_type: Any,
        with_type: bool = True,
    ) -> str:
        """
        Composes the summary line for a CmdbObject that has already been loaded

        Pure composition over already-loaded data: the object as a dict and its CmdbType
        instance. The 'type label + public_id' prefix is built first, then the configured
        summary fields are appended in declaration order (separator '-' before the first
        field, '|' between fields). If anything goes wrong while walking the configured
        fields the helper falls back to the default prefix line and logs at debug level -
        a partially broken type definition should not block the caller. Centralizing this
        composition lets `get_summary_line` and `get_summary_lines_lookup` share one body

        A summary field the object has no value for contributes NOTHING - neither text nor a
        separator. Interpolating it would put the literal word 'None' in front of a user (an object
        whose summary field is unset used to read '#264 - None'), and emitting the separator alone
        would leave a line trailing off as '#264 - '. Only a genuinely absent value is skipped:
        `0`, `False` and other falsy-but-present values are real data and are rendered. The
        separator therefore tracks the first field actually EMITTED, not the first one configured,
        so an unset first field does not push a stray '|' to the front of the line

        Args:
            target_object (dict[str, Any]): The CmdbObject document (as_dict=True shape)
            target_object_type: The CmdbType instance of the object
            with_type (bool): If True the type label is included in the prefix

        Returns:
            str: The composed summary line
        """
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

            line: dict
            for line in summary_fields:
                field_name = line.get('name')
                field_value = next(
                    (field['value'] for field in target_object['fields'] if field['name'] == field_name), None
                )

                if field_value is None or field_value == '':
                    continue

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

            return self._compose_summary_line(target_object, target_object_type, with_type=with_type)
        except Exception as err:
            raise ObjectsManagerSummaryLineError(err) from err


    def _load_types_lookup(self, type_ids: list[int]) -> dict[int, CmdbType]:
        """
        Batch-loads the CmdbTypes whose public_id is in ``type_ids`` and returns them by id

        One ``get_many_from_other_collection`` call followed by per-row deserialization. Rows
        that fail to deserialize are skipped with a debug-level log so a single drifted type
        document does not break the entire batch

        Args:
            type_ids (list[int]): The CmdbType public_ids to resolve

        Returns:
            dict[int, CmdbType]: {type_id: CmdbType} for every type that loaded successfully
        """
        if not type_ids:
            return {}

        type_docs: list[dict[str, Any]] = self.get_many_from_other_collection(
            CmdbType.COLLECTION, public_id={'$in': type_ids},
        )
        lookup: dict[int, CmdbType] = {}

        for type_doc in type_docs:
            try:
                type_instance: CmdbType = CmdbType.from_data(type_doc)
            except Exception as err:
                LOGGER.debug(
                    "Failed to load CmdbType with ID: %s. Error: %s",
                    type_doc.get('public_id'), err,
                )
                continue

            lookup[type_instance.public_id] = type_instance

        return lookup


    def get_summary_lines_lookup(
        self,
        public_ids: list[int],
        with_type: bool = True,
        object_docs: list[dict[str, Any]] | None = None,
    ) -> dict[int, str]:
        """
        Batch-resolves summary lines for many CmdbObjects in a single round-trip pair

        Used by callers that need summary lines for a known list of public_ids and would
        otherwise issue O(N) per-object lookups via ``get_summary_line``. Issues at most two
        bulk queries: one ``find_objects`` over the requested ids (skipped entirely when the
        caller already holds the documents and passes them via ``object_docs``), then one
        ``get_types_lookup`` over the distinct type ids referenced by those objects. Summary
        lines are composed locally via ``_compose_summary_line`` so the wire-format matches
        ``get_summary_line`` byte-for-byte. Duplicates in ``public_ids`` are collapsed before
        the bulk fetch

        Objects that cannot be resolved (deleted, no longer matching their type id, etc.) are
        absent from the returned dict - callers should treat a missing key as "no summary
        line available" rather than as a hard error

        Args:
            public_ids (list[int]): public_ids to resolve; duplicates are allowed
            with_type (bool): If True the type label is included in each prefix
            object_docs (list[dict[str, Any]] | None): Already-loaded full CmdbObject
                documents covering the requested ids; when given, the per-id fetch is
                skipped and docs outside ``public_ids`` are ignored

        Returns:
            dict[int, str]: {public_id: summary_line} for every public_id whose object and
                type both resolved
        """
        if not public_ids:
            return {}

        unique_ids: list[int] = list(set(public_ids))

        if object_docs is not None:
            id_set: set[int] = set(unique_ids)
            object_docs = [doc for doc in object_docs if doc.get('public_id') in id_set]
        else:
            object_docs = self.find_objects(
                criteria={'public_id': {'$in': unique_ids}},
                as_dict=True,
            )

        types_lookup: dict[int, CmdbType] = self._load_types_lookup(list({
            doc.get('type_id') for doc in object_docs if isinstance(doc.get('type_id'), int)
        }))

        result: dict[int, str] = {}

        for doc in object_docs:
            doc_id: Any = doc.get('public_id')
            doc_type_id: Any = doc.get('type_id')

            if not isinstance(doc_id, int):
                continue

            doc_type: CmdbType | None = types_lookup.get(doc_type_id) if isinstance(doc_type_id, int) else None

            if doc_type is None:
                continue

            result[doc_id] = self._compose_summary_line(doc, doc_type, with_type=with_type)

        return result
