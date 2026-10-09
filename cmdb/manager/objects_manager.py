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

The persistence layer of ``framework.objects`` - every object read, write, delete and reference lookup
in the product goes through it. Three rules govern the methods here:

**Every write is guarded by the object's CmdbType, and the guard runs first.** ``guard_writable_type``
is the one place that checks the type exists, is active, and that the caller's ACL grants the
permission; insert, update and delete all call it, and ``delete_with_follow_up`` calls it *before* the
ISMS cascade so a refused delete cannot destroy the object's risk assessments. It is public because a
caller with side effects of its own must ask it too: the object delete routes remove the location node,
the rack and port state and - in bulk - the risk assessments before the manager deletes, so they run
the guard for every target first, and a refused delete answers 403 with nothing touched.

**A read may skip what the caller cannot see, a write may not.** ``get_objects_by`` and
``group_objects_by_value`` drop the objects whose type ACL denies the user and return the rest, so a
list is filtered rather than refused - the counts they produce are therefore the caller's counts, not
the collection's. Every other method raises ``AccessDeniedError``.

**The ACL is only applied when a user and a permission are passed.** Several internal callers pass
neither on purpose (a cascade cleaning up after a delete, the CI Explorer's neighbour reads); a route
that omits them is a bug

What is not a read or write of ``framework.objects`` itself lives in manager-free modules beside it:
``objects_reference_helper`` (the reference queries and the MDS merge), ``objects_summary_helper`` (the
summary line), ``objects_propagation_helper`` (the field statements a Type edit pushes down) and
``risk_assessment_cascade_helper`` (the ISMS cascade, shared with ``ObjectGroupsManager``)
"""
from logging import Logger, getLogger
import copy
import json
from typing import Any

from bson import json_util
from pymongo.results import UpdateResult
from pymongo.command_cursor import CommandCursor

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_constants import PUBLIC_ID_FIELD
from cmdb.database.json_codec import object_hook
from cmdb.utils import Builder
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.base_manager import BaseManager

from cmdb.models.object_model import (
    CmdbObject,
    CmdbObjectKey,
    CmdbObjectFieldKey,
    ObjectWriteVerb,
)
from cmdb.models.object_group_model import ObjectReferenceType
from cmdb.models.type_model import CmdbType
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.user_model import CmdbUser
from cmdb.security.acl.builder import build_denied_types_condition, resolve_denied_type_ids
from cmdb.security.acl.helpers import verify_access
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.framework.results import IterationResult
from cmdb.manager.objects_reference_helper import (
    build_reference_match_queries,
    filter_mds_results_referencing,
    merge_mds_references,
)
from cmdb.manager.objects_summary_helper import compose_summary_line
from cmdb.manager.risk_assessment_cascade_helper import delete_risk_assessments_of
from cmdb.manager.objects_propagation_helper import RawUpdate

from cmdb.errors.manager import (
    BaseManagerGetError,
    BaseManagerIterationError,
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
)
from cmdb.errors.database import DocumentLockTimeoutError, DocumentNetworkError
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
            raise ObjectsManagerInitError(err) from err

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

    def guard_writable_type(
            self,
            type_id: int,
            user: CmdbUser | None,
            permission: AccessControlPermission | None,
            missing_type_error: type[Exception],
            action: str,
            object_type: CmdbType | None = None) -> CmdbType:
        """
        Resolves an object's CmdbType and refuses the write when it may not be performed

        The three checks every write shares, in one place: the type has to exist, it has to be
        active, and the user's ACL has to grant the permission. Every write method calls it; a caller
        that has side effects of its own before the write calls it first as well, so a refused write
        changes nothing

        Args:
            type_id (int): public_id of the object's CmdbType
            user (CmdbUser | None): The CmdbUser performing the write, or None to skip the ACL
            permission (AccessControlPermission | None): The permission required, or None
            missing_type_error (type[Exception]): The error to raise when the type is gone - each
                                                  caller reports its own operation
            action (str): The verb for the deactivated-type message (an `ObjectWriteVerb`)
            object_type (CmdbType | None): An already-resolved type, which a bulk caller holding a
                                           type map passes to skip one lookup per object

        Raises:
            AccessDeniedError: If the type is deactivated or the ACL denies the permission
            Exception: 'missing_type_error' when no CmdbType carries the type_id

        Returns:
            CmdbType: The resolved (and permitted) CmdbType
        """
        if object_type is None:
            object_type = self.get_object_type(type_id)

        if not object_type:
            raise missing_type_error("CmdbType of CmdbObject not found in database!")

        if not object_type.active:
            raise AccessDeniedError(
                f'Objects cannot be {action} because type `{object_type.name}` is deactivated.'
            )

        verify_access(object_type, user, permission)

        return object_type


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
            DocumentLockTimeoutError: If the write timed out on a lock - transient, retryable
            DocumentNetworkError: If the database was unreachable - transient, retryable

        Returns:
            int: The public_id of the created CmdbObject
        """
        try:
            new_object: CmdbObject = CmdbObject.from_data(data)

            self.guard_writable_type(
                new_object.type_id, user, permission, ObjectsManagerInsertError, ObjectWriteVerb.CREATED.value,
            )

            return self.insert(CmdbObject.to_json(new_object))
        except AccessDeniedError as err:
            raise err
        except (DocumentLockTimeoutError, DocumentNetworkError) as err:
            # Propagated unchanged, the same rule MongoDatabaseManager.insert applies one layer down:
            # re-wrapping these as an insert error hides the one thing that distinguishes them - they
            # are transient and the request can simply be retried. The app's error handlers answer them
            # with 423 / 503 (`responses/error_handlers.py`)
            raise err
        except Exception as err:
            LOGGER.error("[insert_object] Exception: %s. Type: %s", err, type(err))
            raise ObjectsManagerInsertError(err) from err


    def apply_raw_updates(self, updates: list[RawUpdate]) -> int:
        """
        Runs a list of server-side ``update_many`` statements against ``framework.objects``, in order

        What carries a CmdbType's field changes into its objects (see `objects_propagation_helper`): each
        statement is applied inside MongoDB, so no object is read and none is written back from memory.
        No ACL is applied - the statements are a consequence of a type or section-template write the
        caller already authorised, and they must reach every object of the type

        Args:
            updates (list[RawUpdate]): The statements to run

        Raises:
            ObjectsManagerUpdateError: If a statement fails; the ones before it have been applied, and
                each is idempotent, so running the list again completes it

        Returns:
            int: How many documents the statements modified, summed
        """
        modified: int = 0

        try:
            for raw_update in updates:
                result: UpdateResult = self.update_many_raw(
                    filter_query=raw_update.filter_query,
                    update=raw_update.update,
                    array_filters=raw_update.array_filters,
                )
                modified += result.modified_count

            return modified
        except Exception as err:
            LOGGER.error("[apply_raw_updates] Exception: %s. Type: %s", err, type(err))
            raise ObjectsManagerUpdateError(err) from err

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
            raise ObjectsManagerGetError(err) from err


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
            raise ObjectsManagerIterationError(err) from err


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
            raise ObjectsManagerIterationError(err) from err


    def get_objects_by(
        self,
        sort: str = "public_id",
        direction: int = -1,
        user: CmdbUser | None = None,
        permission: AccessControlPermission | None = None,
        *,
        criteria: dict[str, Any] | None = None,
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
            criteria (dict[str, Any] | None): The filter, as one dict. None reads every CmdbObject

        Raises:
            ObjectsManagerGetError: If an error occurs while retrieving or processing the objects

        Returns:
            List[CmdbObject]: A list of CmdbObjects the user has access to
        """
        try:
            valid_objects = []

            objects = self.get_many(sort=sort, direction=direction, criteria=criteria)
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
            raise ObjectsManagerGetError(err) from err


    def group_objects_by_value(
        self,
        value: str,
        match: dict[str, Any] | None = None,
        user: CmdbUser | None = None,
        permission: AccessControlPermission | None = None
    ) -> list[dict[str, Any]]:
        """
        Groups objects based on a specific field value and filters them by the provided criteria,
        ensuring the user has the necessary access permissions for each object.

        This method performs an aggregation operation to group documents by a specific field 
        and then sorts the grouped results by their count in descending order. The resulting
        objects are verified for user access before being returned.

        Args:
            value (str): The field by which to group the objects (e.g., 'type_id')
            match (dict[str, Any] | None): Filtering criteria to apply to the documents before grouping
            user (CmdbUser | None): The user making the request
            permission (AccessControlPermission | None): The required permissions for the user

        Raises:
            ObjectsManagerIterationError: If the iteration fails

        Returns:
            list[dict[str, Any]]: A list of objects grouped by the specified field, containing the documents 
                        that meet the selection criteria and pass the access control checks
        """
        try:
            grouped_objects = []
            aggregation_pipeline = []

            if match:
                aggregation_pipeline.append(Builder.match_(match))

            aggregation_pipeline.append(Builder.group_(f'${value}', {
                'result': {'$first': '$$ROOT'},
                'count': {'$sum': 1},
            }))

            aggregation_pipeline.append(Builder.sort_('count', -1))

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
            raise ObjectsManagerIterationError(err) from err


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
            raise ObjectsManagerGetTypeError(err) from err
        except Exception as err:
            LOGGER.error("[get_object_type] Exception: %s, Type: %s", err, type(err))
            raise ObjectsManagerGetTypeError(err) from err


    @staticmethod
    def apply_acl_to_criteria(
            criteria: dict[str, Any],
            user: CmdbUser | None,
            permission: AccessControlPermission | None) -> dict[str, Any]:
        """
        Narrows a find criteria to the CmdbTypes the user's group may access

        An ACL lives on the CmdbType, so the filter is an exclusion of denied `type_id`s (see
        `cmdb.security.acl.builder`). It is combined with `$and` rather than merged: most callers
        already filter on `type_id` themselves, and a merge would silently replace their filter with
        this one.

        Args:
            criteria (dict[str, Any]): The caller's filter
            user (CmdbUser | None): The requesting user, or None to read unscoped
            permission (AccessControlPermission | None): The required permission, or None

        Returns:
            dict[str, Any]: The criteria, narrowed when scoping applies and unchanged otherwise
        """
        if user is None or permission is None:
            return criteria

        return ObjectsManager.narrow_criteria_by_denied_types(criteria, resolve_denied_type_ids(user, permission))


    @staticmethod
    def narrow_criteria_by_denied_types(
            criteria: dict[str, Any],
            denied_type_ids: list[int] | None) -> dict[str, Any]:
        """
        Narrows a find criteria to exclude an already-resolved set of denied CmdbTypes

        The half of the ACL that needs no database access, so a caller performing several reads for
        one request resolves the denied types once (`resolve_denied_type_ids`) and narrows each query
        with the result, instead of paying that lookup per query

        Args:
            criteria (dict[str, Any]): The caller's filter
            denied_type_ids (list[int] | None): public_ids of the denied CmdbTypes, or None/empty
                when nothing is denied

        Returns:
            dict[str, Any]: The criteria, narrowed when something is denied and unchanged otherwise
        """
        if not denied_type_ids:
            return criteria

        return {'$and': [criteria, build_denied_types_condition(denied_type_ids)]}


    def find_objects(
            self,
            criteria: dict[str, Any],
            as_dict: bool = False,
            projection: dict[str, Any] | None = None,
            user: CmdbUser | None = None,
            permission: AccessControlPermission | None = None,
            skip: int = 0,
            limit: int = 0,
            sort: list[tuple[str, int]] | None = None,
        ) -> list[CmdbObject] | list[dict[str, Any]]:
        """
        Get a list of CmdbObjects by a filter

        **The ACL is opt-in here, unlike `get_object` and `iterate_items` where it is a positional
        part of the read.** Passing `user` and `permission` narrows the result to the types the
        caller's group may access; omitting them reads unscoped.

        That default is deliberate rather than lazy: some readers MUST be unscoped. The IPAM
        validators check a candidate against every existing object, not only the visible ones,
        because the invariant they enforce is global - an ACL-filtered check would report an
        overlapping CIDR as valid and the write would then accept it.
        A reader that presents data to a user should pass both; a reader that enforces an invariant
        must not.

        Args:
            criteria: Filter which should be applied during the search
            as_dict (bool = False): If True the list will contain dictionaries instead of CmdbObjects
            projection (dict[str, Any] | None): Optional Mongo projection limiting the returned
                fields. Only valid together with as_dict=True - a partial document cannot be
                deserialized into a CmdbObject
            user (CmdbUser | None): The requesting user, when the read should be ACL-scoped
            permission (AccessControlPermission | None): The permission the user's group must hold;
                scoping happens only when both this and `user` are given
            skip (int): Matching documents passed over first; page with a ``sort``, natural order is not stable
            limit (int): The most documents answered; 0 (the default) means no limit
            sort (list[tuple[str, int]] | None): The order as (key, direction) pairs; None is the natural order

        Raises:
            ObjectsManagerGetError: When the retrieval of CmdbObjects failed, or when a
                projection is combined with as_dict=False

        Returns:
            list[CmdbObject] | list[dict[str, Any]]: list of CmdbObjects matching the criteria
        """
        if projection is not None and not as_dict:
            raise ObjectsManagerGetError("'projection' requires as_dict=True!")

        criteria = self.apply_acl_to_criteria(criteria, user, permission)

        paging: dict[str, Any] = {key: val for key, val in (('skip', skip), ('limit', limit), ('sort', sort)) if val}

        try:
            if projection is not None:
                # Preserve the default '_id' exclusion the projection-less path applies in
                # MongoDatabaseManager.find, unless the caller addressed '_id' explicitly
                safe_projection: dict[str, Any] = {'_id': 0, **projection}
                found_objects: list[dict[str, Any]] = list(
                    self.find(criteria=criteria, projection=safe_projection, **paging))
            else:
                found_objects = list(self.find(criteria=criteria, **paging))

            if as_dict:
                return found_objects

            return [CmdbObject.from_data(found_object) for found_object in found_objects]
        except Exception as err:
            LOGGER.error("[find_objects] Exception: %s. Type: %s", err, type(err))
            raise ObjectsManagerGetError(err) from err


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
            raise ObjectsManagerGetError(err) from err


    def aggregate_objects(self, pipeline: list[dict[str, Any]], **kwargs: Any) -> CommandCursor:
        """
        Executes an aggregation pipeline on the database to process and retrieve CmdbObjects

        This method wraps the `aggregate` function, applying the given aggregation pipeline 
        and handling potential iteration errors

        Args:
            pipeline (list[dict[str, Any]]): A list of aggregation stages to be executed on the database
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


    def aggregate_objects_within_time_limit(
            self,
            pipeline: list[dict[str, Any]],
            time_limit_ms: int) -> list[dict[str, Any]]:
        """
        Runs an aggregation on the CmdbObjects under a server-side time budget and reads every result

        Args:
            pipeline (list[dict[str, Any]]): The aggregation stages
            time_limit_ms (int): The server-side time budget, in milliseconds

        Raises:
            ObjectsManagerIterationError: If the aggregation failed - wrapping a DocumentQueryTimeLimitError
                when it ran past its time budget

        Returns:
            list[dict[str, Any]]: Every result of the aggregation
        """
        try:
            return self.aggregate_within_time_limit(pipeline, time_limit_ms)
        except BaseManagerIterationError as err:
            raise ObjectsManagerIterationError(err) from err


    def count_objects(
            self,
            criteria: dict[str, Any],
            user: CmdbUser | None = None,
            permission: AccessControlPermission | None = None,
        ) -> int:
        """
        Counts the CmdbObjects matching a filter, ACL-scoped exactly as ``find_objects`` is - the total of a page

        Args:
            criteria (dict[str, Any]): Filter which should be applied
            user (CmdbUser | None): The requesting user, when the count should be ACL-scoped
            permission (AccessControlPermission | None): The permission the group must hold; scoping needs both

        Raises:
            ObjectsManagerGetError: When the count failed
        Returns:
            int: The number of matching CmdbObjects
        """
        criteria = self.apply_acl_to_criteria(criteria, user, permission)

        try:
            return self.count_documents(criteria)
        except Exception as err:
            LOGGER.error("[count_objects] Exception: %s. Type: %s", err, type(err))
            raise ObjectsManagerGetError(err) from err


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
            Builder.group_(f"${CmdbObjectKey.TYPE_ID.value}", {"count": {"$sum": 1}})
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
                                      query_filter: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Retrieves all CmdbObjects whose multi-data sections (MDS) reference a given object

        This method constructs an aggregation pipeline to find CmdbObject that contain reference 
        fields pointing to the specified `referenced_object`

        Args:
            referenced_object (CmdbObject): The CmdbObject being referenced
            query_filter (dict[str, Any] | list[dict[str, Any]]): Additional query filters to apply in the pipeline. 
                                              Can be a dictionary (single filter) or a list of filters

        Raises:
            ObjectsManagerIterationError: If the iteration fails

        Returns:
            list[dict[str, Any]]: A list of CmdbObjects that reference the given `referenced_object` in their 
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
            query_pipeline.append(Builder.match_(Builder.and_([
                {"fields.type": FieldType.REFERENCE.value},
                {"fields.ref_types": object_type_id},
            ])))

            # Filter the public_id's of these types
            query_pipeline.append(Builder.project_({"public_id": 1, "_id": 0}))

            # Get all objects of these types
            query_pipeline.append(Builder.lookup_(from_collection='framework.objects',
                                                  local_field='public_id',
                                                  foreign_field='type_id',
                                                  as_field='type_objects'))

            # Filter out types which don't have any objects
            query_pipeline.append(Builder.match_({"type_objects.0": {"$exists": True}}))

            # Spread out the arrays
            query_pipeline.append(Builder.unwind_({'path': '$type_objects'}))

            # Filter the objects which actually have any multi section data
            query_pipeline.append(Builder.match_({"type_objects.multi_data_sections.0": {"$exists": True}}))

            # Remove the public_id field
            query_pipeline.append(Builder.project_({"type_objects": 1}))

            # Spread out as a list
            query_pipeline.append(Builder.replace_root_('$type_objects'))

            query_pipeline.append(Builder.project_({"_id": 0}))

            results = list(self.aggregate_from_other_collection(CmdbType.COLLECTION, query_pipeline))

            # The manager owns the read: the ref-field names are resolved per TYPE in one query, so the
            # pure filter below decides per ROW without a type fetch of its own
            result_type_ids: list[int] = list({
                result.get(CmdbObjectKey.TYPE_ID.value)
                for result in results
                if isinstance(result.get(CmdbObjectKey.TYPE_ID.value), int)
            })

            return filter_mds_results_referencing(
                results,
                referenced_object.public_id,
                self._ref_field_names_by_type(result_type_ids),
            )
        except Exception as err:
            LOGGER.error("[get_mds_references_for_object] Exception: %s, Type: %s", err, type(err))
            raise ObjectsManagerIterationError(err) from err


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


    def references(
        self,
        object_: CmdbObject,
        criteria: dict[str, Any] | list[dict[str, Any]],
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
            criteria (dict[str, Any] | list[dict[str, Any]]): A filter (or list of pipeline stages) to apply
                when querying for references
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
            query.append(Builder.match_(Builder.or_(build_reference_match_queries(object_))))
            query.append(Builder.match_({'fields.value': object_.public_id}))

            builder_params = BuilderParameters(criteria=query, sort=sort, order=order)

            # limit and skip will be handled when merged with the MDS results in '__merge_mds_references()'
            result = self.iterate(builder_params, user, permission)
            mds_result = self.get_mds_references_for_object(object_, criteria)

            merge_result = merge_mds_references(mds_result, result, limit, skip, sort, order)

            return merge_result
        except ObjectsManagerMdsReferencesError as err:
            raise ObjectsManagerIterationError(err) from err
        except ObjectsManagerIterationError as err:
            raise err
        except Exception as err:
            LOGGER.error("[references] Exception: %s, Type: %s", err, type(err))
            raise ObjectsManagerIterationError(err) from err


    def get_objects_lookup(
            self, public_ids: list[int], denied_type_ids: list[int] | None = None) -> dict[int, CmdbObject]:
        """
        Batch-loads the CmdbObjects for the given public_ids and returns them keyed by public_id

        Issues a single query over all ids instead of one lookup per id. The ACL is opt-in, as in `find_objects`,
        and takes the denied types already resolved once by the caller (`resolve_denied_type_ids`)

        Args:
            public_ids (list[int]): The CmdbObject public_ids to load
            denied_type_ids (list[int] | None): public_ids of the CmdbTypes left out; None or empty reads unscoped

        Returns:
            dict[int, CmdbObject]: Mapping of public_id to its CmdbObject for every id that resolved
        """
        criteria: dict[str, Any] = self.narrow_criteria_by_denied_types(
            {CmdbObjectKey.PUBLIC_ID.value: {"$in": public_ids}}, denied_type_ids)
        all_objects: list[CmdbObject] = self.find_objects(criteria=criteria)

        return {obj.public_id: obj for obj in all_objects}

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

    def update_object(self,
                      public_id: int,
                      data: CmdbObject | dict[str, Any],
                      user: CmdbUser | None = None,
                      permission: AccessControlPermission | None = None,
                      partial: bool = False) -> None:
        """
        Updates a CmdbObject in the database

        Args:
            public_id (int): public_id of the CmdbObject which should be updated
            data: (CmdbObject | dict[str, Any]): The new data for the CmdbObject
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

            self.guard_writable_type(
                type_id, user, permission, ObjectsManagerUpdateError, ObjectWriteVerb.UPDATED.value,
            )

            self.update({CmdbObjectKey.PUBLIC_ID.value: public_id}, instance)
        except AccessDeniedError as err:
            raise err
        except Exception as err:
            LOGGER.error("[update_object] Exception: %s, Type: %s", err, type(err))
            raise ObjectsManagerUpdateError(err) from err

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
                avoid one ``get_object_type`` query per object (the same type is used for the
                deactivated-check and the ACL verification)

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

            # A caller-supplied type skips the lookup (bulk-delete N+1 avoidance)
            self.guard_writable_type(
                type_id, user, permission, ObjectsManagerDeleteError, ObjectWriteVerb.REMOVED.value, object_type,
            )

            return self.delete({CmdbObjectKey.PUBLIC_ID.value: public_id})
        except AccessDeniedError as err:
            raise err
        except Exception as err:
            # One arm, one log line: every failure is logged before it is re-wrapped, so the likely
            # failures are as visible to an operator as the rest
            LOGGER.error("[delete_object] Exception: %s, Type: %s", err, type(err))
            raise ObjectsManagerDeleteError(err) from err


    def delete_with_follow_up(
            self, public_id: int,
            user: CmdbUser | None = None,
            permission: AccessControlPermission | None = None,
            object_type: CmdbType | None = None
        ) -> bool:
        """
        Deletes a CmdbObject together with the IsmsRiskAssessments that reference it

        **Access is verified before anything is deleted.** A cascade running first would leave the
        permission check second - inside ``delete_object`` - so a delete the caller was not allowed
        to make, or one whose type had been deactivated, would answer 403 with the object's risk
        assessments and their control-measure assignments already gone. The object would survive;
        its risk history would not.

        The cost of the ordering is one extra read of the object: this method resolves its type to
        run the guard, and ``delete_object`` reads it again to delete it. A refused delete that
        destroys ISMS data is worth more than a round trip.

        A missing object is answered False without cascading - there is nothing to authorise and
        nothing to delete

        Args:
            public_id (int): public_id of the CmdbObject which should be deleted
            user (CmdbUser | None): The CmdbUser requesting deletion
            permission (AccessControlPermission | None): The required permission for deletion
            object_type (CmdbType | None): The object's already-resolved CmdbType, used for the guard
                here and forwarded to ``delete_object`` (see there)

        Raises:
            AccessDeniedError: If the object's type is deactivated or the user lacks permission
            ObjectsManagerDeleteError: If any issue occurs during retrieval or deletion

        Returns:
            bool: True if the CmdbObject was successfully deleted, False otherwise
        """
        try:
            to_delete_object: dict[str, Any] | None = self.get_one(public_id)
        except Exception as err:
            LOGGER.error("[delete_with_follow_up] Exception: %s, Type: %s", err, type(err))
            raise ObjectsManagerDeleteError(err) from err

        if not to_delete_object:
            return False

        object_type = self.guard_writable_type(
            CmdbObject.from_data(to_delete_object).type_id,
            user,
            permission,
            ObjectsManagerDeleteError,
            ObjectWriteVerb.REMOVED.value,
            object_type,
        )

        self.delete_objects_from_risk_assessment_cascade([public_id])

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

                ids_filter: int | dict[str, list[int]] = {"$in": public_ids}
            elif public_ids:
                ids_filter = public_ids
            else:
                raise ObjectsManagerUpdateError("No public ids provided to delete from references!")

            # Regular fields first, then the rows of every multi-data-section
            for rows_path, value_path in (
                ("fields", "fields.$[f].value"),
                ("multi_data_sections.values.data", "multi_data_sections.$[].values.$[].data.$[f].value"),
            ):
                self.update_many_raw(**self._reference_scrub(rows_path, value_path, ids_filter))
        except Exception as err:
            LOGGER.error("[delete_all_object_references] Exception: %s, Type: %s", err, type(err))
            raise ObjectsManagerUpdateError(err) from err


    @staticmethod
    def _reference_scrub(rows_path: str, value_path: str, ids_filter: Any) -> dict[str, Any]:
        """
        Builds one ``update_many_raw`` that empties the reference rows pointing at the given ids

        A row is a reference when its ``type`` is a plain reference or a reference-section field - both
        hold an object id. The same element match selects the documents and, as the array filter ``f``,
        the rows inside them

        Args:
            rows_path (str): Where the rows sit (``fields``, or the MDS rows' ``data``)
            value_path (str): The positional path of a matching row's ``value``, through ``$[f]``
            ids_filter (Any): The ``value`` filter - one public_id, or an ``$in`` clause

        Returns:
            dict[str, Any]: The ``filter_query``, ``update`` and ``array_filters`` keyword arguments
        """
        ref_field_types: list[str] = [FieldType.REFERENCE.value, FieldType.REF_SECTION.value]

        return {
            "filter_query": {rows_path: {"$elemMatch": {"type": {"$in": ref_field_types}, "value": ids_filter}}},
            "update": {"$set": {value_path: ""}},
            "array_filters": [{"f.type": {"$in": ref_field_types}, "f.value": ids_filter}],
        }


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
            raise ObjectsManagerUpdateError(err) from err


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

# --------------------------------------------------- ISMS CASCADE --------------------------------------------------- #

    def delete_objects_from_risk_assessment_cascade(self, deleted_object_ids: list[int]) -> None:
        """
        Deletes every IsmsRiskAssessment of any of the given CmdbObjects, and their assignments

        One ``$in`` query per collection, however many objects. Only assessments of OBJECTS are touched -
        an assessment of a CmdbObjectGroup sharing a public_id is the group's (see
        ``risk_assessment_cascade_helper``, which the group delete shares)

        Args:
            deleted_object_ids (list[int]): public_ids of the deleted CmdbObjects; empty is a no-op

        Raises:
            BaseManagerDeleteError: If deleting the assessments or the assignments fails
        """
        if not deleted_object_ids:
            return

        delete_risk_assessments_of(
            self.dbm, self.db_name, ObjectReferenceType.OBJECT, {'$in': deleted_object_ids},
        )

# --------------------------------------------------- SUMMARY LINES -------------------------------------------------- #

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
            CmdbType.COLLECTION, criteria={PUBLIC_ID_FIELD: {'$in': type_ids}},
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

        The one summary-line read of this manager: callers that need lines for a known list of
        public_ids would otherwise issue one read per object. Issues at most two bulk queries: one
        ``find_objects`` over the requested ids (skipped entirely when the caller already holds the
        documents and passes them via ``object_docs``), then one ``_load_types_lookup`` over the
        distinct type ids referenced by those objects. Each line is composed locally by
        ``objects_summary_helper.compose_summary_line``. Duplicates in ``public_ids`` are collapsed
        before the bulk fetch

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

            result[doc_id] = compose_summary_line(doc, doc_type, with_type=with_type)

        return result
