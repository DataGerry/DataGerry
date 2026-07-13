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
"""
import json
from logging import Logger, getLogger
from typing import Any
from bson import json_util

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_utils import object_hook

from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.base_manager import BaseManager

from cmdb.models.type_model import (
    CmdbType,
    TypeFieldSection,
    SectionType,
    FieldType,
    FieldKey,
    SectionKey,
    TypeSchemaKey,
)
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.object_model import (
    CmdbObject,
    CmdbObjectKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
    CmdbObjectFieldKey,
)

from cmdb.framework.results import IterationResult

from cmdb.errors.manager import (
    BaseManagerGetError,
    BaseManagerDeleteError,
)
from cmdb.errors.manager.types_manager import (
    TypesManagerGetError,
    TypesManagerUpdateError,
    TypesManagerDeleteError,
    TypesManagerInsertError,
    TypesManagerInitError,
    TypesManagerIterationError,
    TypesManagerUpdateMDSError,
)
from cmdb.errors.models.cmdb_type import (
    CmdbTypeInitFromDataError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 TypesManager - CLASS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TypesManager(BaseManager):
    """
    Manages the CRUD functions of CmdbTypes

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
        except BaseManagerGetError as err:
            raise TypesManagerGetError(str(err)) from err


    def get_type(self, public_id: int, as_dict: bool = True) -> dict[str, Any] | CmdbType | None:
        """
        Get a single CmdbType by its public_id

        Args:
            public_id (int): public_id of the CmdbType
            as_dict(bool = True): If True returns a dictionary else a CmdbType instance

        Raises:
            TypesManagerGetError: If CmdbType could not be retrieved

        Returns:
            dict[str, Any] | CmdbType | None: The requested CmdbType
        """
        try:
            target_type: dict[str, Any] | None = self.get_one(public_id)

            if target_type and not as_dict:
                target_type = CmdbType.from_data(target_type)

            return target_type
        except BaseManagerGetError as err:
            raise TypesManagerGetError(str(err)) from err


    def iterate(self, builder_params: BuilderParameters) -> IterationResult[CmdbType]:
        """
        Retrieves multiple CmdbTypes

        Args:
            builder_params (BuilderParameters): Filter for which CmdbTypes should be retrieved

        Raises:
            TypesManagerIterationError: When the iteration failed

        Returns:
            IterationResult[CmdbTypes]: All CmdbTypes matching the filter
        """
        try:
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
        all_types: list[CmdbType] = self.find_types(criteria={TypeSchemaKey.PUBLIC_ID: {"$in": public_ids}})

        return {object_type.public_id: object_type for object_type in all_types}


    def get_all_types(self) -> list[CmdbType]:
        """
        Retrieves all CmdbTypes from the collection

        This method fetches multiple CmdbType from the collection and maps each raw result
        (in dictionary form) into an instance of the CmdbType class

        Raises:
            TypesManagerGetError: If there is an error while fetching or processing types

        Returns:
            list[CmdbType]: A list of CmdbType instances created from the raw data
        """
        try:
            raw_types: list[dict] = self.get_many()

            return [CmdbType.from_data(type) for type in raw_types]
        except (BaseManagerGetError, CmdbTypeInitFromDataError) as err:
            raise TypesManagerGetError(str(err)) from err
        except Exception as err:
            LOGGER.error("[get_all_types] Exception: %s. Type: %s", err, type(err))
            raise TypesManagerGetError(str(err)) from err


    def get_types_by(self, sort: str = 'public_id', **requirements: Any) -> list[CmdbType]:
        """
        Retrieves CmdbTypes from the collection based on specified requirements

        This method fetches types matching the provided criteria (through `requirements`) 
        and sorts the results according to the specified field (default is `public_id`)

        Args:
            sort (str): The field by which to sort the results (default is `public_id`)
            **requirements: Additional filtering criteria passed as keyword arguments

        Raises:
            TypesManagerGetError: If there is an error while fetching or processing types

        Returns:
            list[CmdbType]: A list of CmdbTypes that match the given requirements
        """
        try:
            raw_data = self.get_many(sort=sort, **requirements)

            return [CmdbType.from_data(data) for data in raw_data]
        except Exception as err:
            LOGGER.error("[get_types_by] Exception: %s. Type: %s", err, type(err))
            raise TypesManagerGetError(str(err)) from err


    def get_objects_for_type(
        self,
        target_type_id: int,
        section_ids: list[str] | None = None,
    ) -> list[CmdbObject]:
        """
        Retrieves the CmdbObjects associated with a specific CmdbType public_id

        Args:
            target_type_id (int): The public_id of the CmdbType
            section_ids (list[str] | None): When given, only objects that carry at least one
                multi_data_section with a matching ``section_id`` are loaded. Lets MDS-propagation
                callers skip every object that has none of the affected sections (which can never
                change) instead of materialising every object of the type

        Raises:
            TypesManagerGetError: If an error occurs during the fetching or processing of the data

        Returns:
            list[CmdbObject]: A list of CmdbObjects that belong to the specified CmdbType
        """
        try:
            if section_ids is None:
                all_type_objects: list[dict[str, Any]] = self.get_many_from_other_collection(
                    CmdbObject.COLLECTION,
                    type_id=target_type_id,
                )
            else:
                mds_section_id_path: str = (
                    f'{CmdbObjectKey.MULTI_DATA_SECTIONS.value}.{CmdbObjectMdsKey.SECTION_ID.value}'
                )
                criteria: dict[str, Any] = {
                    CmdbObjectKey.TYPE_ID.value: target_type_id,
                    mds_section_id_path: {'$in': section_ids},
                }
                all_type_objects = list(self.dbm.find(CmdbObject.COLLECTION, self.db_name, criteria))

            return [CmdbObject.from_data(obj) for obj in all_type_objects]
        except BaseManagerGetError as err:
            raise TypesManagerGetError(str(err)) from err
        except Exception as err:
            LOGGER.error("[get_objects_for_type] Exception: %s. Type: %s", err, type(err))
            raise TypesManagerGetError(str(err)) from err

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

    def update_type(self, public_id: int, update_type: CmdbType | dict[str, Any]) -> None:
        """
        Update an existing CmdbType in the database

        Args:
            public_id (int): The public_id of the CmdbType which should be updated
            update_type (CmdbType | dict[str, Any]): The new type data

        Raises:
            TypesManagerUpdateError: If there is an error during the update process
        """
        try:
            self.update(criteria={'public_id': public_id}, data=self._as_stored_type_dict(update_type))
        except Exception as err:
            LOGGER.error("[update_type] Exception: %s. Type: %s", err, type(err))
            raise TypesManagerUpdateError(str(err)) from err

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_type(self, public_id: int) -> None:
        """
        Delete an existing CmdbType by its public_id

        Args:
            public_id (int): public_id of the CmdbType which should be deleted

        Raises:
            TypesManagerDeleteError: If the CmdbType could not be deleted
        """
        try:
            self.delete({'public_id': public_id})
        except BaseManagerDeleteError as err:
            raise TypesManagerDeleteError(str(err)) from err

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    def check_special_type_exists(self, special_type: SpecialType) -> bool:
        """
        Reports whether any CmdbType already carries the given SpecialType marker

        Args:
            special_type (SpecialType): The SpecialType marker to look for

        Returns:
            bool: True if a CmdbType with this 'special_type' exists, False otherwise
        """
        matching_type: dict[str, Any] | None = self.get_one_by({TypeSchemaKey.SPECIAL_TYPE: special_type})

        return bool(matching_type)


    def update_multi_data_fields(
        self,
        target_type: CmdbType,
        added_fields: dict,
        deleted_fields: dict
    ) -> list[CmdbObject]:
        """
        Updates multi-data fields for CmdbObjects of a given type, returning only changed objects

        Each new field entry is a ``{name, value, type}`` triple. The ``added_fields`` /
        ``deleted_fields`` dicts are keyed by the MDS ``section_id``, which by contract equals the
        matching type section's ``name`` (that is how ``handle_multi_data_sections`` builds them).
        Only objects that carry at least one of the affected sections are loaded - an object with
        none of them can never change - so the fetch scales with the affected objects, not the whole
        type

        Args:
            target_type (CmdbType): The type whose objects are being updated
            added_fields (dict): Section IDs mapped to the list of field names to add
            deleted_fields (dict): Section IDs mapped to the list of field names to delete

        Returns:
            list[CmdbObject]: List of objects that were actually modified
        """
        try:
            # Objects lacking every affected section are guaranteed no-ops, so never load them
            affected_section_ids: list[str] = list(set(added_fields) | set(deleted_fields))
            all_type_objects: list[CmdbObject] = self.get_objects_for_type(
                target_type.public_id, section_ids=affected_section_ids,
            )
            updated_objects: list[CmdbObject] = []

            # Precompute mapping from field name to type for fast lookup
            field_type_map = {f[FieldKey.NAME]: f[FieldKey.TYPE] for f in target_type.fields}

            # update the multi-data-sections
            for cur_object in all_type_objects:
                obj_changed: bool = False

                for current_mds_section in cur_object.multi_data_sections:
                    section_id = current_mds_section[CmdbObjectMdsKey.SECTION_ID]

                    # Get fields to add/delete for this section
                    fields_to_add = added_fields.get(section_id, [])
                    fields_to_delete = deleted_fields.get(section_id, [])

                    if not fields_to_add and not fields_to_delete:
                        continue  # nothing to change for this section

                    # Add new fields
                    if fields_to_add:
                        self.create_mds_field_entries(fields_to_add, current_mds_section, field_type_map)
                        obj_changed = True

                    # Delete removed fields
                    if fields_to_delete:
                        self.delete_mds_field_entries(fields_to_delete, current_mds_section)
                        obj_changed = True

                if obj_changed:
                    updated_objects.append(cur_object)

            return updated_objects
        except TypesManagerGetError as err:
            raise TypesManagerUpdateError(str(err)) from err
        except Exception as err:
            LOGGER.error("[update_multi_data_fields] Exception: %s. Type: %s", err, type(err))
            raise TypesManagerUpdateError(str(err)) from err


    def fields_diff(
        self,
        initial_fields: list[str],
        new_fields: list[str],
        check_added: bool = False
    ) -> list[str]:
        """
        Compares two lists of fields and returns the differences

        This method compares the initial list of fields and the new list of fields to identify the differences.
        Depending on the `check_added` flag, it either identifies fields that were added or fields that were deleted

        Args:
            initial_fields (list): The original list of field names
            new_fields (list): The updated list of field names
            check_added (bool): If `True`, returns the fields that were added in the new list
                                If `False`, returns the fields that were removed from the new list

        Returns:
            list[str]: A list of field names that were either added or deleted based on the value of `check_added`
        """
        initial_set: set[str] = set(initial_fields)
        new_set: set[str] = set(new_fields)

        # fields added in new_fields
        if check_added:
            return list(new_set - initial_set)

        # fields removed from initial_fields
        return list(initial_set - new_set)


    def create_mds_field_entries(
        self,
        fields_to_add: list[str],
        mds_section: dict[str, Any],
        field_type_map: dict[str, str]
    ) -> None:
        """
        Adds new field entries to every row of an MDS section, in-place

        An MDS section stores its captured rows under ``values``; each row holds its field
        entries under ``data`` as ``{name, value, type}`` triples (see CmdbObjectMdsKey /
        CmdbObjectMdsRowKey). A newly added type field is appended to each existing row with a
        ``None`` value so the row keeps one entry per defined field. Existing entries are left
        untouched, so re-running is idempotent

        Args:
            fields_to_add (list[str]): Names of the fields to add to each row
            mds_section (dict): The MDS section dict (with a ``values`` list of rows) to update
            field_type_map (dict): Mapping of field name to field type for quick lookup
        """
        for row in mds_section.get(CmdbObjectMdsKey.VALUES, []):
            row.setdefault(CmdbObjectMdsRowKey.DATA, [])
            existing_names: set[str] = {entry[CmdbObjectFieldKey.NAME] for entry in row[CmdbObjectMdsRowKey.DATA]}

            for field_name in fields_to_add:
                if field_name in existing_names:
                    continue  # idempotent: never duplicate an entry already present in the row

                field_type: str = field_type_map.get(field_name, FieldType.TEXT)  # fallback 'text'
                row[CmdbObjectMdsRowKey.DATA].append({
                    CmdbObjectFieldKey.NAME: field_name,
                    CmdbObjectFieldKey.VALUE: None,
                    CmdbObjectFieldKey.TYPE: field_type
                })


    def delete_mds_field_entries(
        self,
        fields_to_delete: list[str],
        mds_section: dict[str, Any]
    ) -> None:
        """
        Removes the named field entries from every row of an MDS section, in-place

        Args:
            fields_to_delete (list[str]): Names of the fields to drop from each row
            mds_section (dict): The MDS section dict (with a ``values`` list of rows) to update
        """
        for row in mds_section.get(CmdbObjectMdsKey.VALUES, []):
            if CmdbObjectMdsRowKey.DATA not in row:
                continue

            # Filter out fields to delete
            row[CmdbObjectMdsRowKey.DATA] = [
                entry for entry in row[CmdbObjectMdsRowKey.DATA]
                if entry[CmdbObjectFieldKey.NAME] not in fields_to_delete
            ]


    def handle_multi_data_sections(self, old_type: CmdbType, updated_type: dict[str, Any]) -> list[CmdbObject]:
        """
        Handles the updates to multi-data sections in the specified CmdbType by comparing
        the current fields with the updated fields and determining which fields were added or removed

        This method iterates through the sections of the `old_type` and compares them with 
        the updated data. It then calculates the differences in the fields, specifically for
        multi-data sections, and calls `update_multi_data_fields` to apply the changes

        Args:
            old_type (CmdbType): The CmdbType of the object whose multi-data sections will be updated
            updated_type (dict[str, Any]): The updated data of the CmdbType as a dict

        Raises:
            TypesManagerUpdateMDSError: If the update operation fails

        Returns:
            list: A list of updated CmdbObjects after applying the field changes
        """
        try:
            added_fields: dict[str, list[str]] = {}
            deleted_fields: dict[str, list[str]] = {}

            a_section: TypeFieldSection
            for a_section in old_type.render_meta.sections:
                if a_section.type != SectionType.MDS_SECTION:
                    continue

                # Find the matching section in updated_type
                updated_sections: list[dict[str, Any]] = [
                    s for s in updated_type[TypeSchemaKey.RENDER_META][TypeSchemaKey.SECTIONS]
                    if s[SectionKey.TYPE] == a_section.type and s[SectionKey.NAME] == a_section.name
                ]

                if not updated_sections:
                    continue  # section removed

                updated_section: dict[str, Any] = updated_sections[0]

                added: list[str] = self.fields_diff(
                    a_section.fields, updated_section[SectionKey.FIELDS], check_added=True
                )
                deleted: list[str] = self.fields_diff(
                    a_section.fields, updated_section[SectionKey.FIELDS], check_added=False
                )

                # Keyed by the type section's name, which by contract equals the objects' MDS
                # section_id - update_multi_data_fields looks these up by section_id
                if added:
                    added_fields[a_section.name] = added
                if deleted:
                    deleted_fields[a_section.name] = deleted

            if not added_fields and not deleted_fields:
                return []

            return self.update_multi_data_fields(old_type, added_fields, deleted_fields)
        except TypesManagerUpdateError as err:
            raise TypesManagerUpdateMDSError(str(err)) from err
        except Exception as err:
            LOGGER.error("[handle_multi_data_sections] Exception: %s. Type: %s", err, type(err), exc_info=True)
            raise TypesManagerUpdateMDSError(str(err)) from err
