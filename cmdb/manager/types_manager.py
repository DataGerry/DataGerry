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
from logging import Logger, getLogger
from typing import Any
from pymongo.results import UpdateResult

from cmdb.database import MongoDatabaseManager
from cmdb.database.json_codec import EXTENDED_JSON_DECODE_ERRORS, bson_round_trip

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
from cmdb.security.acl.builder import build_permitted_types_criteria, resolve_denied_type_ids
from cmdb.security.acl.permission import AccessControlPermission

from cmdb.errors.manager import (
    BaseManagerDeleteError,
    BaseManagerGetError,
    BaseManagerInitError,
    BaseManagerInsertError,
    BaseManagerIterationError,
    BaseManagerUpdateError,
)
from cmdb.errors.manager.types_manager import (
    TypesManagerGetError,
    TypesManagerUpdateError,
    TypesManagerDeleteError,
    TypesManagerInsertError,
    TypesManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# What a stored type document that no longer fits the model raises, on the way in and on the way out
TYPE_DOCUMENT_ERRORS: tuple[type[Exception], ...] = (CmdbType.INIT_FROM_DATA_ERROR, CmdbType.TO_JSON_ERROR)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 TypesManager - CLASS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TypesManager(BaseManager):
    """
    Manages the CRUD functions of CmdbTypes

    Error policy: a public method catches what its calls raise - the call's BaseManager* error, the
    CmdbType's declared (de)serialisation errors (``TYPE_DOCUMENT_ERRORS``) and, around the BSON round trip
    of a raw dict, a wrapper value that cannot be decoded (``EXTENDED_JSON_DECODE_ERRORS``) - and converts it
    into the matching TypesManager* error, logging it and chaining the original with ``raise ... from err``.
    Anything else - a programming error - propagates as itself, so a route answers it 500 instead of the
    400 a database failure gets. The two transient database errors are never caught here either

    Extends: BaseManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        """
        Set the database connection for the TypesManager

        Args:
            dbm (MongoDatabaseManager): Database interaction manager
            database (str): Name of the database to which the 'dbm' should connect. Only used in CLOUD_MODE
        """
        super().__init__(CmdbType.COLLECTION, dbm, database)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

    def insert_type(self, new_type: CmdbType | dict[str, Any]) -> int:
        """
        Insert a CmdbType into the database

        Args:
            new_type (CmdbType | dict): Raw data of the CmdbType

        Raises:
            TypesManagerInsertError: When the type cannot be written out, or a CmdbType could not be inserted into
                the database

        Returns:
            int: The public_id of the created CmdbType
        """
        document: dict[str, Any] = self._stored_type_dict_or_raise(new_type, TypesManagerInsertError)

        try:
            return self.insert(document)
        except BaseManagerInsertError as err:
            LOGGER.error("[insert_type] BaseManagerInsertError: %s", err)
            raise TypesManagerInsertError(err) from err


    @staticmethod
    def _as_stored_type_dict(type_or_dict: CmdbType | dict[str, Any]) -> dict[str, Any]:
        """
        Normalises a CmdbType or raw dict into the stored-document form for insert/update

        A CmdbType is serialised via ``to_json``; a raw dict is passed through the BSON round trip
        (``bson_round_trip``) so any BSON/datetime values are coerced into the shape the collection expects.
        Shared by ``insert_type`` and ``update_type`` so the two never drift apart

        Args:
            type_or_dict (CmdbType | dict[str, Any]): The type to normalise

        Raises:
            CmdbTypeToJsonError: When the CmdbType cannot be written out
            EXTENDED_JSON_DECODE_ERRORS: When the raw dict carries a wrapper value that cannot be decoded

        Returns:
            dict[str, Any]: The type as a stored-document dict
        """
        if isinstance(type_or_dict, CmdbType):
            return CmdbType.to_json(type_or_dict)

        return bson_round_trip(type_or_dict)


    def _stored_type_dict_or_raise(
            self,
            type_or_dict: CmdbType | dict[str, Any],
            error: type[Exception]) -> dict[str, Any]:
        """
        The stored-document form of a type, a failure to build it raised as the write's own error

        Scoped to the conversion: a type that cannot be written out, or a wrapper value in a raw dict that cannot
        be decoded, is the caller's - a programming error in the conversion still propagates as itself

        Args:
            type_or_dict (CmdbType | dict[str, Any]): The type to normalise
            error (type[Exception]): The write's TypesManager* error

        Raises:
            error: When the document cannot be built

        Returns:
            dict[str, Any]: The type as a stored-document dict
        """
        try:
            return self._as_stored_type_dict(type_or_dict)
        except (CmdbType.TO_JSON_ERROR, *EXTENDED_JSON_DECODE_ERRORS) as err:
            LOGGER.error("[%s] Unwritable type document: %s. Type: %s", error.__name__, err, type(err))
            raise error(err) from err

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
        except BaseManagerGetError as err:
            LOGGER.error("[get_new_type_public_id] BaseManagerGetError: %s", err)
            raise TypesManagerGetError(err) from err


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
        except BaseManagerGetError as err:
            LOGGER.error("[get_type] BaseManagerGetError: %s", err)
            raise TypesManagerGetError(err) from err


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
        except (BaseManagerGetError, *TYPE_DOCUMENT_ERRORS) as err:
            LOGGER.error("[get_type_instance] Exception: %s. Type: %s", err, type(err))
            raise TypesManagerGetError(err) from err


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
          beside them unfiltered

        Args:
            builder_params (BuilderParameters): Filter for which CmdbTypes should be retrieved
            user (CmdbUser | None): CmdbUser the request is made for. Defaults to None
            permission (AccessControlPermission | list[AccessControlPermission] | None): The
                permission the user's group must hold on a type for it to appear. Several
                permissions mean **all** of them, matching `$all`. Defaults to None

        Raises:
            TypesManagerIterationError: When the iteration failed

        Returns:
            IterationResult[CmdbType]: All CmdbTypes matching the filter
        """
        if user and permission:
            builder_params.add_criteria(build_permitted_types_criteria(int(user.group_id), permission))

        try:
            aggregation_result, total = self.iterate_query(builder_params)

            iteration_result: IterationResult[CmdbType] = IterationResult(
                aggregation_result,
                total,
                CmdbType
            )

            return iteration_result
        except (BaseManagerIterationError, *TYPE_DOCUMENT_ERRORS) as err:
            LOGGER.error("[iterate] Exception: %s. Type: %s", err, type(err))
            raise TypesManagerIterationError(err) from err


    def get_denied_type_ids(self, user: CmdbUser, permission: AccessControlPermission) -> list[int]:
        """
        The public_ids of the CmdbTypes the user's group may not access with the permission

        The one projected read ``resolve_denied_type_ids`` makes, raised as this manager's error - for a caller
        that needs the denial itself, to narrow a read and to mask the rows it returns with one lookup

        Args:
            user (CmdbUser): The CmdbUser the request is made for
            permission (AccessControlPermission): The permission the user's group must hold

        Raises:
            TypesManagerGetError: If the denied types could not be read

        Returns:
            list[int]: public_ids of the denied CmdbTypes; empty when the group may access every type
        """
        try:
            return resolve_denied_type_ids(user, permission)
        except (BaseManagerGetError, BaseManagerInitError) as err:
            LOGGER.error("[get_denied_type_ids] Exception: %s. Type: %s", err, type(err))
            raise TypesManagerGetError(err) from err


    def find_types(self, criteria: dict[str, Any]) -> list[CmdbType]:
        """
        Get a list of CmdbTypes by a filter, in ``get_types_by``'s default order

        Args:
            criteria (dict[str, Any]): Filter which should be applied during the search

        Raises:
            TypesManagerGetError: If the CmdbTypes could not be retrieved or one could not be read

        Returns:
            list[CmdbType]: list of CmdbTypes matching the criteria
        """
        return self.get_types_by(criteria=criteria)


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
        if not public_ids:
            return {}

        all_types: list[CmdbType] = self.find_types(
            criteria={TypeSchemaKey.PUBLIC_ID.value: {'$in': public_ids}},
        )

        return {object_type.public_id: object_type for object_type in all_types}


    def get_types_by(
        self,
        sort: str = 'public_id',
        direction: int = CmdbDAO.DAO_DESCENDING,
        *,
        criteria: dict[str, Any] | None = None,
    ) -> list[CmdbType]:
        """
        Retrieves CmdbTypes matching the criteria, sorted by the given field (default is `public_id`)

        The filter is one keyword-only dict, so it can never be confused with the sort options

        Args:
            sort (str): The field by which to sort the results (default is `public_id`)
            direction (int): Sort direction, CmdbDAO.DAO_ASCENDING (1) or CmdbDAO.DAO_DESCENDING
                             (-1, the BaseManager default)
            criteria (dict[str, Any] | None): The filter, as one dict. None reads every CmdbType

        Raises:
            TypesManagerGetError: If there is an error while fetching or processing types

        Returns:
            list[CmdbType]: A list of CmdbTypes that match the criteria
        """
        try:
            raw_data = self.get_many(sort=sort, direction=direction, criteria=criteria)

            return [CmdbType.from_data(data) for data in raw_data]
        except (BaseManagerGetError, *TYPE_DOCUMENT_ERRORS) as err:
            LOGGER.error("[get_types_by] Exception: %s. Type: %s", err, type(err))
            raise TypesManagerGetError(err) from err


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
            TypesManagerUpdateError: When the type cannot be written out, or the update failed

        Returns:
            UpdateResult: The outcome of the update, including the matched and modified counts
        """
        update_data: dict[str, Any] = self._stored_type_dict_or_raise(update_type, TypesManagerUpdateError)
        update_data[TypeSchemaKey.PUBLIC_ID.value] = public_id

        try:
            return self.update(criteria={TypeSchemaKey.PUBLIC_ID.value: public_id}, data=update_data)
        except BaseManagerUpdateError as err:
            LOGGER.error("[update_type] BaseManagerUpdateError: %s", err)
            raise TypesManagerUpdateError(err) from err


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
        except BaseManagerUpdateError as err:
            LOGGER.error("[update_type_field] BaseManagerUpdateError: %s", err)
            raise TypesManagerUpdateError(err) from err

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
        except BaseManagerDeleteError as err:
            LOGGER.error("[delete_type] BaseManagerDeleteError: %s", err)
            raise TypesManagerDeleteError(err) from err

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
            # An existence check the server can stop at the first match - no type document is loaded
            return self.count_documents(
                {TypeSchemaKey.SPECIAL_TYPE.value: self._special_type_value(special_type)}, limit=1,
            ) > 0
        except BaseManagerGetError as err:
            LOGGER.error("[check_special_type_exists] BaseManagerGetError: %s", err)
            raise TypesManagerGetError(err) from err


    def _distinct_type_ids(self, criteria: dict[str, Any]) -> list[int]:
        """
        The public_ids of the CmdbTypes matching the criteria, read with one distinct query

        Only integer ids are answered: a drifted document whose public_id is no int cannot be dropped into an
        '$in' / '$nin' of type ids

        Args:
            criteria (dict[str, Any]): The filter selecting the types

        Raises:
            TypesManagerGetError: If the lookup fails

        Returns:
            list[int]: The matching public_ids
        """
        try:
            found_ids: list[Any] = self.get_distinct(TypeSchemaKey.PUBLIC_ID.value, criteria)
        except BaseManagerGetError as err:
            LOGGER.error("[_distinct_type_ids] BaseManagerGetError: %s", err)
            raise TypesManagerGetError(err) from err

        return [type_id for type_id in found_ids if isinstance(type_id, int)]


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
        return self._distinct_type_ids({TypeSchemaKey.SPECIAL_TYPE.value: self._special_type_value(special_type)})


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
        return self._distinct_type_ids(
            {TypeSchemaKey.FIELDS.value: {'$elemMatch': {FieldKey.TYPE.value: FieldType.LOCATION.value}}},
        )


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

        return set(self._distinct_type_ids({TypeSchemaKey.PUBLIC_ID.value: {'$in': public_ids}}))
