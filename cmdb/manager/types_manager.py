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

from cmdb.models.type_model import CmdbType, TypeFieldSection
from cmdb.models.object_model import CmdbObject

from cmdb.framework.results import IterationResult, ListResult

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
            if isinstance(new_type, CmdbType):
                type_to_add: dict[str, Any] = CmdbType.to_json(new_type)
            else:
                type_to_add = json.loads(json.dumps(new_type, default=json_util.default), object_hook=object_hook)

            return self.insert(type_to_add)
        except Exception as err:
            LOGGER.error("[insert_type] Exception: %s. Type: %s", err, type(err))
            raise TypesManagerInsertError(str(err)) from err

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


    def get_type(self, public_id: int) -> dict[str, Any] | None:
        """
        Get a single CmdbType by its public_id

        Args:
            public_id (int): public_id of the CmdbType

        Raises:
            TypesManagerGetError: If CmdbType could not be retrieved

        Returns:
            dict | None: Instance of CmdbType with data
        """
        try:
            return self.get_one(public_id)
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

            iteration_result: IterationResult[CmdbType] = IterationResult(aggregation_result,
                                                                          total,
                                                                          CmdbType)

            return iteration_result
        except Exception as err:
            raise TypesManagerIterationError(str(err)) from err


    def find_types(self, criteria: dict) -> ListResult[CmdbType]:
        """
        Get a list of types by a filter query

        Args:
            filter: Filter for matched querys

        Returns:
            ListResult
        """
        try:
            results = self.find(criteria=criteria)

            types: list[CmdbType] = [CmdbType.from_data(result) for result in results]

            return ListResult(types)
        except (BaseManagerGetError, CmdbTypeInitFromDataError) as err:
            raise TypesManagerGetError(str(err)) from err
        except Exception as err:
            LOGGER.error("[find_types] Exception: %s. Type: %s", err, type(err))
            raise TypesManagerGetError(str(err)) from err


    def count_types(self) -> int:
        """
        Counts the total number of CmdbTypes in the collection

        Raises:
            TypesManagerGetError: If counting CmdbTypes failed

        Returns:
            int: The number of CmdbTypes
        """
        try:
            return self.count_documents(self.collection)
        except BaseManagerGetError as err:
            raise TypesManagerGetError(str(err)) from err


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


    def get_objects_for_type(self, target_type_id: int) -> list:
        """
        Retrieves all CmdbObjects associated with a specific CmdbType public_id

        Args:
            target_type_id (int): The public_id of the CmdbType

        Raises:
            TypesManagerGetError: If an error occurs during the fetching or processing of the data

        Returns:
            list: A list of CmdbObjects that belong to the specified CmdbType
        """
        try:
            all_type_objects = self.get_many_from_other_collection(CmdbObject.COLLECTION,
                                                                   type_id=target_type_id)

            found_objects = []

            for obj in all_type_objects:
                found_objects.append(CmdbObject(**obj))

            return found_objects
        except BaseManagerGetError as err:
            raise TypesManagerGetError(str(err)) from err
        except Exception as err:
            LOGGER.error("[get_objects_for_type] Exception: %s. Type: %s", err, type(err))
            raise TypesManagerGetError(str(err)) from err

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

    def update_type(self, public_id: int, update_type: CmdbType | dict) -> None:
        """
        Update an existing CmdbType in the database


        Args:
            public_id (int): The public_id of the CmdbType which should be updated
            update_type (CmdbType | dict): The new type data

        Raises:
            TypesManagerUpdateError: If there is an error during the update process
        """
        try:
            if isinstance(update_type, CmdbType):
                new_version_type = CmdbType.to_json(update_type)
            else:
                new_version_type = json.loads(json.dumps(update_type,
                                                         default=json_util.default),
                                                         object_hook=object_hook)

            self.update(criteria={'public_id': public_id}, data=new_version_type)
        except Exception as err:
            LOGGER.error("[update_type] Exception: %s. Type: %s", err, type(err))
            raise TypesManagerUpdateError(str(err)) from err

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_type(self, public_id: int) -> None:
        """
        Delete a existing CmdbType by its public_id

        Args:
            public_id (int): public_id of the CmdbType which should be deleted
        """
        try:
            self.delete({'public_id': public_id})
        except BaseManagerDeleteError as err:
            raise TypesManagerDeleteError(err) from err

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    def update_multi_data_fields(self, target_type: CmdbType, added_fields: dict, deleted_fields: dict):
        """
        Updates multi-data fields for a specific type of CmdbObjects in the database

        This method updates the multi-data sections of all CmdbObjects of a given CmdbType, adding new fields and 
        removing deleted fields as specified by the `added_fields` and `deleted_fields` dictionaries. The changes 
        are applied to each object that belongs to the specified `target_type`

        Args:
            target_type (CmdbType): The type of CmdbObjects to be updated
            added_fields (dict): A dictionary where keys are section IDs and values are lists of fields to be added
            deleted_fields (dict): A dictionary where keys are section IDs and values are lists of fields to be deleted

        Raises:
            TypesManagerUpdateError: If the update operation fails

        Returns:
            list: A list of updated CmdbObjects
        """
        try:
            all_type_objects = self.get_objects_for_type(target_type.public_id)

            # update the multi-data-sections
            an_object: CmdbObject
            for an_object in all_type_objects:
                for current_mds_section in an_object.multi_data_sections:
                    section_id = current_mds_section["section_id"]
                    fields_to_add = added_fields.get(section_id, [])
                    fields_to_delete = deleted_fields.get(section_id, [])

                    # add new fields and remove deleted fields
                    if fields_to_add:
                        for data_set in current_mds_section["values"]:
                            data_set = self.create_mds_field_entries(fields_to_add, data_set)

                    if fields_to_delete:
                        for data_set in current_mds_section["values"]:
                            data_set = self.delete_mds_field_entries(fields_to_delete, data_set)

            return all_type_objects
        except TypesManagerGetError as err:
            raise TypesManagerUpdateError(str(err)) from err
        except Exception as err:
            LOGGER.error("[update_multi_data_fields] Exception: %s. Type: %s", err, type(err))
            raise TypesManagerUpdateError(str(err)) from err


    def fields_diff(self, initial_fields: list, new_fields: list,  check_added: bool = False) -> list:
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
            list: A list of field names that were either added or deleted based on the value of `check_added`
        """
        if check_added:
            # check which fields were added
            return [field_name for field_name in new_fields if field_name not in initial_fields]

        #check which fields were deleted
        return [field_name for field_name in initial_fields if field_name not in new_fields]


    def create_mds_field_entries(self, fields_to_add: list[str], data_set) -> list:
        """
        Adds new fields to the provided data set

        This method appends new field entries to the "data" section of the provided data set
        Each new field will have a `name` (from the `fields_to_add` list) and an initial `value` of `None`

        Args:
            fields_to_add (list): A list of field names to be added to the data set
            data_set (dict): The data set to which the new fields will be appended. It must contain a key "data",
                             which is a list

        Returns:
            dict: The updated data set with the new field entries added to the "data" list
        """
        for field_name in fields_to_add:
            new_field: dict[str, Any] = {
                "name": field_name,
                "value": None
            }

            data_set["data"].append(new_field)

        return data_set


    def delete_mds_field_entries(self, fields_to_delete: list, data_set: list) -> list:
        """
        Removes specified field entries from the provided data set

        This method searches for fields listed in `fields_to_delete` within the `data_set["data"]` list 
        and removes the corresponding entries. The deletion occurs in reverse order to avoid indexing issues 
        when modifying the list while iterating

        Args:
            fields_to_delete (list): A list of field names to be removed from the data set
            data_set (dict): The data set from which the fields will be removed. It must contain a key "data"
                             with a list of field entries

        Returns:
            dict: The updated data set with the specified fields removed from the "data" list
        """
        to_delete = []

        # get all fields which should be deleted
        for field_name in fields_to_delete:
            index: int = 0

            for entry in data_set["data"]:
                if entry["name"] == field_name:
                    break

                index += 1

            to_delete.append(index)

        # delete from end
        for idx in to_delete[::-1]:
            del data_set["data"][idx]

        return data_set


    def handle_mutli_data_sections(self, target_type: CmdbType, updated_type: dict):
        """
        Handles the updates to multi-data sections in the specified CmdbType by comparing
        the current fields with the updated fields and determining which fields were added or removed

        This method iterates through the sections of the `target_type` and compares them with 
        the updated data. It then calculates the differences in the fields, specifically for
        multi-data sections, and calls `update_multi_data_fields` to apply the changes

        Args:
            target_type (CmdbType): The CmdbType of the object whose multi-data sections will be updated
            updated_type (dict): The updated data of the CmdbType as a dict

        Raises:
            TypesManagerUpdateMDSError: If the update operation fails

        Returns:
            list: A list of updated CmdbObjects after applying the field changes
        """
        try:
            added_fields: dict = {}
            deleted_fields: dict = {}

            a_section: TypeFieldSection
            for a_section in target_type.render_meta.sections:

                if a_section.type == "multi-data-section":
                    for updated_section in updated_type["render_meta"]["sections"]:

                        if a_section.type == updated_section["type"] and a_section.name == updated_section["name"]:
                            # get the field changes for each multi-data-section
                            added_fields[a_section.name] = self.fields_diff(a_section.fields,
                                                                            updated_section["fields"],
                                                                            True)
                            deleted_fields[a_section.name] = self.fields_diff(a_section.fields,
                                                                            updated_section["fields"],
                                                                            False)

            return self.update_multi_data_fields(target_type, added_fields, deleted_fields)
        except TypesManagerUpdateError as err:
            raise TypesManagerUpdateMDSError(str(err)) from err
        except Exception as err:
            LOGGER.error("[handle_mutli_data_sections] Exception: %s. Type: %s", err, type(err), exc_info=True)
            raise TypesManagerUpdateMDSError(str(err)) from err
