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
Handles interaction between the database and CmdbTypes

The manager owns the CmdbType documents only. What a type edit changes in the type's objects - the
multi-data-section rows (`cmdb.manager.types_mds_helper`) and the flat field list - is worked out from
the two type states by pure helpers and written by ``ObjectsManager.apply_raw_updates`` as server-side
statements, driven by ``types_helper.apply_type_update_side_effects``: a manager does not drive another
manager, and no object has to be read for it.
"""
import json
from logging import Logger, getLogger
from typing import Any
from bson import json_util
from pymongo.results import UpdateResult

from cmdb.database import MongoDatabaseManager
from cmdb.database.json_codec import object_hook

from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.base_manager import BaseManager

from cmdb.models.type_model import (
    CmdbType,
    FieldKey,
    FieldType,
    TypeSchemaKey,
)
from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.user_model import CmdbUser
from cmdb.models.special_type_model.special_type_enum import SpecialType

from cmdb.framework.results import IterationResult
from cmdb.security.acl.builder import build_permitted_types_criteria
from cmdb.security.acl.permission import AccessControlPermission

from cmdb.errors.manager.types_manager import (
    TypesManagerGetError,
    TypesManagerUpdateError,
    TypesManagerDeleteError,
    TypesManagerInsertError,
    TypesManagerInitError,
    TypesManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 TypesManager - CLASS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TypesManager(BaseManager):
    """
    Manages the CRUD functions of CmdbTypes

    Error policy: every public method converts ANY failure below it - the BaseManager errors it
    expects as well as anything unforeseen - into the matching TypesManager* error, logging it on the
    way out and chaining the original with `raise ... from err`. Callers therefore only ever have to
    handle the domain errors, and no caller has to know which layer failed

    Extends: BaseManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        """
        Set the database connection for the TypesManager

        Args:
            dbm (MongoDatabaseManager): Database interaction manager
            database (str): Name of the database to which the 'dbm' should connect. Only used in CLOUD_MODE

        Raises:
            TypesManagerInitError: If the TypesManager could not be initialised
        """
        try:
            super().__init__(CmdbType.COLLECTION, dbm, database)
        except Exception as err:
            raise TypesManagerInitError(str(err)) from err

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

    def insert_type(self, new_type: CmdbType | dict[str, Any]) -> int:
        """
        Insert a CmdbType into the database

        Args:
            new_type (CmdbType | dict): Raw data of the CmdbType

        Raises:
            TypesManagerInsertError: When a CmdbType could not be inserted into the database

        Returns:
            int: The public_id of the created CmdbType
        """
        try:
            return self.insert(self._as_stored_type_dict(new_type))
        except Exception as err:
            LOGGER.error("[insert_type] Exception: %s. Type: %s", err, type(err))
            raise TypesManagerInsertError(str(err)) from err


    @staticmethod
    def _as_stored_type_dict(type_or_dict: CmdbType | dict[str, Any]) -> dict[str, Any]:
        """
        Normalises a CmdbType or raw dict into the stored-document form for insert/update

        A CmdbType is serialised via ``to_json``; a raw dict is passed through a BSON-aware JSON
        round-trip (``json_util.default`` -> ``object_hook``) so any BSON/datetime values are coerced
        into the shape the collection expects. Shared by ``insert_type`` and ``update_type`` so the
        two never drift apart

        Args:
            type_or_dict (CmdbType | dict[str, Any]): The type to normalise

        Returns:
            dict[str, Any]: The type as a stored-document dict
        """
        if isinstance(type_or_dict, CmdbType):
            return CmdbType.to_json(type_or_dict)

        return json.loads(json.dumps(type_or_dict, default=json_util.default), object_hook=object_hook)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def get_new_type_public_id(self) -> int:
        """
        Gets the next counter for the public_id of a CmdbType from database and increases it

        Raises:
            TypesManagerGetError: If the next public_id could not be retrieved

        Returns:
            int: The next public_id for CmdbType
        """
        try:
            return self.get_next_public_id(inc_id=True)
        except Exception as err:
            LOGGER.error("[get_new_type_public_id] Exception: %s. Type: %s", err, type(err))
            raise TypesManagerGetError(str(err)) from err


    def get_type(self, public_id: int) -> dict[str, Any] | None:
        """
        Gets a single CmdbType by its public_id as its raw stored document

        Use `get_type_instance` when a CmdbType object is needed instead - the two are kept apart so
        the return type follows from the method called rather than from a boolean argument

        Args:
            public_id (int): public_id of the CmdbType

        Raises:
            TypesManagerGetError: If the CmdbType could not be retrieved

        Returns:
            dict[str, Any] | None: The requested CmdbType document, or None if no type has that id
        """
        try:
            return self.get_one(public_id)
        except Exception as err:
            LOGGER.error("[get_type] Exception: %s. Type: %s", err, type(err))
            raise TypesManagerGetError(str(err)) from err


    def get_type_instance(self, public_id: int) -> CmdbType | None:
        """
        Gets a single CmdbType by its public_id as a hydrated CmdbType

        The CmdbType counterpart of `get_type`; a missing type is still reported as None rather than
        raising, so callers keep the same not-found handling either way

        Args:
            public_id (int): public_id of the CmdbType

        Raises:
            TypesManagerGetError: If the CmdbType could not be retrieved or could not be hydrated

        Returns:
            CmdbType | None: The requested CmdbType, or None if no type has that id
        """
        try:
            target_type: dict[str, Any] | None = self.get_one(public_id)

            return CmdbType.from_data(target_type) if target_type else None
        except Exception as err:
            LOGGER.error("[get_type_instance] Exception: %s. Type: %s", err, type(err))
            raise TypesManagerGetError(str(err)) from err


    def iterate(
        self,
        builder_params: BuilderParameters,
        user: CmdbUser | None = None,
        permission: AccessControlPermission | list[AccessControlPermission] | None = None
    ) -> IterationResult[CmdbType]:
        """
        Retrieves multiple CmdbTypes

        Pass ``user`` and ``permission`` to restrict the listing to the types that user's group may
        access; omit them and every type is returned, which is what the callers that have already
        checked access themselves rely on.

        The access-control rule is merged into the **criteria** rather than appended as pipeline
        stages the way an object listing does it, and both differences matter:

        * An object's ACL lives on another collection, so ``build_acl_pipeline`` has to resolve the
          denied type ids in a separate query first. A **types** listing queries the collection the
          ACL is stored on, so the same rule is one ``$nor`` over this collection - no extra query
        * ``iterate_query`` runs a second aggregation for the total and builds it from the criteria
          alone, so a rule that lives only in the pipeline would filter the rows and leave the count
          beside them unfiltered (the bug **T211** records for the object listing)

        Args:
            builder_params (BuilderParameters): Filter for which CmdbTypes should be retrieved
            user (CmdbUser | None): CmdbUser the request is made for. Defaults to None
            permission (AccessControlPermission | list[AccessControlPermission] | None): The
                permission the user's group must hold on a type for it to appear. Several
                permissions mean **all** of them, matching `$all`. Defaults to None

        Raises:
            TypesManagerIterationError: When the iteration failed

        Returns:
            IterationResult[CmdbTypes]: All CmdbTypes matching the filter
        """
        try:
            if user and permission:
                builder_params.add_criteria(build_permitted_types_criteria(int(user.group_id), permission))

            aggregation_result, total = self.iterate_query(builder_params)

            iteration_result: IterationResult[CmdbType] = IterationResult(
                aggregation_result,
                total,
                CmdbType
            )

            return iteration_result
        except Exception as err:
            raise TypesManagerIterationError(str(err)) from err


    def find_types(self, criteria: dict[str, Any]) -> list[CmdbType]:
        """
        Get a list of CmdbTypes by a filter

        Args:
            criteria: Filter which should be applied during the search

        Returns:
            list[CmdbType]: list of CmdbTypes matching the criteria
        """
        try:
            found_types = self.find(criteria=criteria)

            return [CmdbType.from_data(found_type) for found_type in found_types]
        except Exception as err:
            LOGGER.error("[find_types] Exception: %s. Type: %s", err, type(err))
            raise TypesManagerGetError(str(err)) from err


    def get_types_lookup(self, public_ids: list[int]) -> dict[int, CmdbType]:
        """
        Builds a public_id -> CmdbType lookup table for the given CmdbType public_ids

        Performs a single bulk query (``public_id $in public_ids``) so callers can resolve
        many type references without one round-trip per id

        Args:
            public_ids (list[int]): public_ids of the CmdbTypes to fetch

        Raises:
            TypesManagerGetError: If the underlying fetch fails

        Returns:
            dict[int, CmdbType]: Mapping of public_id to its CmdbType (missing ids are absent)
        """
        all_types: list[CmdbType] = self.find_types(
            criteria={TypeSchemaKey.PUBLIC_ID.value: {'$in': public_ids}},
        )

        return {object_type.public_id: object_type for object_type in all_types}


    def get_all_types(self, direction: int = CmdbDAO.DAO_DESCENDING) -> list[CmdbType]:
        """
        Retrieves all CmdbTypes from the collection

        This method fetches multiple CmdbType from the collection and maps each raw result
        (in dictionary form) into an instance of the CmdbType class

        Args:
            direction (int): public_id sort direction, CmdbDAO.DAO_ASCENDING (1) or
                             CmdbDAO.DAO_DESCENDING (-1, the BaseManager default)

        Raises:
            TypesManagerGetError: If there is an error while fetching or processing types

        Returns:
            list[CmdbType]: A list of CmdbType instances created from the raw data
        """
        try:
            raw_types: list[dict[str, Any]] = self.get_many(direction=direction)

            return [CmdbType.from_data(raw_type) for raw_type in raw_types]
        except Exception as err:
            LOGGER.error("[get_all_types] Exception: %s. Type: %s", err, type(err))
            raise TypesManagerGetError(str(err)) from err


    def get_types_by(
        self,
        sort: str = 'public_id',
        direction: int = CmdbDAO.DAO_DESCENDING,
        **requirements: Any,
    ) -> list[CmdbType]:
        """
        Retrieves CmdbTypes from the collection based on specified requirements

        This method fetches types matching the provided criteria (through `requirements`)
        and sorts the results according to the specified field (default is `public_id`)

        `direction` is declared explicitly rather than left to `**requirements` so it binds to the
        sort order instead of silently becoming a query filter field

        Args:
            sort (str): The field by which to sort the results (default is `public_id`)
            direction (int): Sort direction, CmdbDAO.DAO_ASCENDING (1) or CmdbDAO.DAO_DESCENDING
                             (-1, the BaseManager default)
            **requirements: Additional filtering criteria passed as keyword arguments

        Raises:
            TypesManagerGetError: If there is an error while fetching or processing types

        Returns:
            list[CmdbType]: A list of CmdbTypes that match the given requirements
        """
        try:
            raw_data = self.get_many(sort=sort, direction=direction, **requirements)

            return [CmdbType.from_data(data) for data in raw_data]
        except Exception as err:
            LOGGER.error("[get_types_by] Exception: %s. Type: %s", err, type(err))
            raise TypesManagerGetError(str(err)) from err


# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

    def update_type(self, public_id: int, update_type: CmdbType | dict[str, Any]) -> UpdateResult:
        """
        Update an existing CmdbType in the database

        The document identity is pinned to `public_id`, so a payload carrying a different public_id
        can never rewrite the stored id. Updating an id that does not exist is a no-op - the
        underlying update does not upsert - which is why the UpdateResult is returned: callers that
        need to tell "updated" from "no such type" read its `matched_count` instead of issuing a
        separate existence query

        Args:
            public_id (int): The public_id of the CmdbType which should be updated
            update_type (CmdbType | dict[str, Any]): The new type data

        Raises:
            TypesManagerUpdateError: If there is an error during the update process

        Returns:
            UpdateResult: The outcome of the update, including the matched and modified counts
        """
        try:
            update_data: dict[str, Any] = self._as_stored_type_dict(update_type)
            update_data[TypeSchemaKey.PUBLIC_ID.value] = public_id

            return self.update(criteria={TypeSchemaKey.PUBLIC_ID.value: public_id}, data=update_data)
        except Exception as err:
            LOGGER.error("[update_type] Exception: %s. Type: %s", err, type(err))
            raise TypesManagerUpdateError(str(err)) from err

    def update_type_field(self, public_id: int, field: str, value: Any) -> UpdateResult:
        """
        Sets ONE top-level field of a CmdbType, leaving every other key untouched

        Use this for a presentation-level key such as ``ci_explorer_label`` or ``ci_explorer_color``.
        Unlike update_type it writes a targeted `$set` instead of the whole document, so a concurrent
        edit of the type's fields or sections can not be overwritten. It must never be used for
        ``fields`` / ``render_meta``, whose changes have to run through update_type and its cascades

        Args:
            public_id (int): public_id of the CmdbType to update
            field (str): The top-level document key to set
            value (Any): The value to store

        Raises:
            TypesManagerUpdateError: If the update fails

        Returns:
            UpdateResult: The outcome of the update, including the matched and modified counts
        """
        try:
            return self.update(criteria={TypeSchemaKey.PUBLIC_ID.value: public_id}, data={field: value})
        except Exception as err:
            LOGGER.error("[update_type_field] Exception: %s. Type: %s", err, type(err))
            raise TypesManagerUpdateError(str(err)) from err

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_type(self, public_id: int) -> bool:
        """
        Delete an existing CmdbType by its public_id

        The acknowledgement is returned rather than discarded, so a caller can tell a deletion from a
        no-op the same way `update_type`'s UpdateResult lets it tell an update from an unknown id

        Args:
            public_id (int): public_id of the CmdbType which should be deleted

        Raises:
            TypesManagerDeleteError: If the CmdbType could not be deleted

        Returns:
            bool: True when a CmdbType was deleted, False when no type carried that public_id
        """
        try:
            return self.delete({TypeSchemaKey.PUBLIC_ID.value: public_id})
        except Exception as err:
            LOGGER.error("[delete_type] Exception: %s. Type: %s", err, type(err))
            raise TypesManagerDeleteError(str(err)) from err

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    @staticmethod
    def _special_type_value(special_type: SpecialType | str) -> str:
        """
        Reads a SpecialType marker as the plain string a document stores

        The marker reaches this manager both ways: as a `SpecialType` member from code that knows
        which one it wants (the Rack and Cable paths), and as a **string** from a payload - the
        special-type route's query parameter, a type-import entry and the type-create guard all pass
        the value they validated with `SpecialType.is_valid`. Both have to answer the same query

        Args:
            special_type (SpecialType | str): The marker to query for

        Returns:
            str: The marker as stored in a CmdbType document
        """
        return special_type.value if isinstance(special_type, SpecialType) else special_type


    def check_special_type_exists(self, special_type: SpecialType | str) -> bool:
        """
        Reports whether any CmdbType already carries the given SpecialType marker

        Args:
            special_type (SpecialType | str): The SpecialType marker to look for, as a member or as
                the string a payload carries

        Raises:
            TypesManagerGetError: If the lookup fails

        Returns:
            bool: True if a CmdbType with this 'special_type' exists, False otherwise
        """
        try:
            matching_type: dict[str, Any] | None = self.get_one_by(
                {TypeSchemaKey.SPECIAL_TYPE.value: self._special_type_value(special_type)}
            )

            return bool(matching_type)
        except Exception as err:
            LOGGER.error("[check_special_type_exists] Exception: %s. Type: %s", err, type(err))
            raise TypesManagerGetError(str(err)) from err


    def get_type_ids_of_special_type(self, special_type: SpecialType | str) -> list[int]:
        """
        Retrieves the public_ids of every CmdbType carrying the given SpecialType marker

        One distinct query on the indexed public_id, so no type document is loaded. There is normally a
        single type per marker, but the list form keeps a caller correct on an installation that somehow
        grew two - and lets the ids be dropped straight into an '$in' / '$nin'

        Args:
            special_type (SpecialType | str): The SpecialType marker to look for, as a member or as
                the string a payload carries

        Raises:
            TypesManagerGetError: If the lookup fails

        Returns:
            list[int]: The public_ids of the matching CmdbTypes, empty when the marker is unused
        """
        try:
            return [
                type_id
                for type_id in self.get_distinct(
                    TypeSchemaKey.PUBLIC_ID.value,
                    {TypeSchemaKey.SPECIAL_TYPE.value: self._special_type_value(special_type)},
                )
                if isinstance(type_id, int)
            ]
        except Exception as err:
            LOGGER.error("[get_type_ids_of_special_type] Exception: %s. Type: %s", err, type(err))
            raise TypesManagerGetError(str(err)) from err


    def get_type_ids_with_location_field(self) -> list[int]:
        """
        Retrieves the public_ids of every CmdbType that declares a location-typed field

        The match is on the field's TYPE, never on its name, the same way the whole location machinery
        matches - so a type whose location field is not called 'dg_location' still counts. One distinct
        query, so no type document is loaded, and the result drops straight into an '$in'

        Raises:
            TypesManagerGetError: If the lookup fails

        Returns:
            list[int]: The public_ids of the matching CmdbTypes, empty when no type carries a location
                       field
        """
        try:
            return [
                type_id
                for type_id in self.get_distinct(
                    TypeSchemaKey.PUBLIC_ID.value,
                    {TypeSchemaKey.FIELDS.value: {'$elemMatch': {FieldKey.TYPE.value: FieldType.LOCATION.value}}},
                )
                if isinstance(type_id, int)
            ]
        except Exception as err:
            LOGGER.error("[get_type_ids_with_location_field] Exception: %s. Type: %s", err, type(err))
            raise TypesManagerGetError(str(err)) from err


    def get_existing_type_ids(self, public_ids: list[int]) -> set[int]:
        """
        Reports which of the given public_ids belong to an existing CmdbType

        Answers "do these types exist?" with a single distinct query on the indexed public_id, so no
        type document is loaded. Use this instead of get_types_lookup when only the existence of the
        referenced types matters, e.g. when checking cross-type references for dangling ids

        Args:
            public_ids (list[int]): The CmdbType public_ids to look for

        Raises:
            TypesManagerGetError: If the lookup fails

        Returns:
            set[int]: The subset of public_ids an existing CmdbType carries (empty when none match)
        """
        if not public_ids:
            return set()

        try:
            found_ids: list[Any] = self.get_distinct(
                TypeSchemaKey.PUBLIC_ID.value,
                {TypeSchemaKey.PUBLIC_ID.value: {'$in': public_ids}},
            )

            return set(found_ids)
        except Exception as err:
            LOGGER.error("[get_existing_type_ids] Exception: %s. Type: %s", err, type(err))
            raise TypesManagerGetError(str(err)) from err
