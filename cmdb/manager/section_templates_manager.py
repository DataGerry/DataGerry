# DATAGERRY - OpenSource Enterprise CMDB
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
This module contains the implementation of the SectionTemplatesManager
"""
from logging import Logger, getLogger
from typing import Any

from deepdiff import DeepDiff

from cmdb.database import MongoDatabaseManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.types_manager import TypesManager
from cmdb.manager.objects_manager import ObjectsManager
from cmdb.manager.base_manager import BaseManager

from cmdb.models.user_model import CmdbUser
from cmdb.models.type_model import CmdbType, TypeFieldSection
from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.models.object_model import CmdbObject
from cmdb.framework.results import IterationResult
from cmdb.security.acl.permission import AccessControlPermission

from cmdb.errors.manager.section_templates_manager import (
    SectionTemplatesManagerInsertError,
    SectionTemplatesManagerIterationError,
    SectionTemplatesManagerGetError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                            SectionTemplatesManager - CLASS                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class SectionTemplatesManager(BaseManager):
    """
    The SectionTemplatesManager handles the interaction between the SectionTemplates-API and the Database
    Extends: BaseManager
    """

    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        """
        Set the database connection and the queue for sending events

        Args:
            dbm (MongoDatabaseManager): Database connection
        """
        # TODO: REFACTOR-FIX (Remove dependencies to the managers)
        self.types_manager = TypesManager(dbm, database)
        self.objects_manager = ObjectsManager(dbm, database)

        super().__init__(CmdbSectionTemplate.COLLECTION, dbm, database)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

    def insert_section_template(self, data: dict[str, Any]) -> int:
        """
        Insert new CMDBSectionTemplate

        Args:
            data: init data
            user: current user who requested the action
            permission: Required permission for this action
        Raises:
            SectionTemplatesManagerInsertError: Raised when inserting into database fails
        Returns:
            Public ID of the new section template in database
        """
        try:
            new_section_template = CmdbSectionTemplate(**data)

            return self.insert(new_section_template.__dict__)
        except Exception as err:
            LOGGER.debug('[insert_section_template] Error while inserting section template - error: %s', err)
            raise SectionTemplatesManagerInsertError(err) from err

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def iterate(self,
                builder_params: BuilderParameters,
                user: CmdbUser = None,
                permission: AccessControlPermission = None) -> IterationResult[CmdbSectionTemplate]:
        """
        Performs an aggregation on the database

        Args:
            builder_params (BuilderParameters): Contains input to identify the target of action
            user (CmdbUser, optional): User requesting this action
            permission (AccessControlPermission, optional): Permission which should be checked for the user
        Raises:
            SectionTemplatesManagerIterationError: Raised when something goes wrong during the building of the
                                                   IterationResult
        Returns:
            IterationResult[CmdbSectionTemplate]: Result which matches the Builderparameters
        """
        try:
            aggregation_result, total = self.iterate_query(builder_params, user, permission)

            iteration_result: IterationResult[CmdbSectionTemplate] = IterationResult(
                aggregation_result,
                total,
                CmdbSectionTemplate
            )

            return iteration_result
        except Exception as err:
            raise SectionTemplatesManagerIterationError(err) from err


    def get_section_template(self, public_id: int) -> CmdbSectionTemplate:
        """
        Retrives a CmdbSectionTemplate from the database with the given public_id

        Args:
            public_id (int): public_id of the CmdbSectionTemplate which should be retrieved
        Raises:
            SectionTemplatesManagerGetError: Raised if the CmdbSectionTemplate could not ne retrieved
        Returns:
            CmdbSectionTemplate: The requested CmdbSectionTemplate if it exists, else None
        """
        try:
            found_template: CmdbSectionTemplate = None
            section_template = self.get_one(public_id)

            if section_template:
                found_template = CmdbSectionTemplate(**section_template)

            return found_template
        except Exception as err:
            raise SectionTemplatesManagerGetError(str(err)) from err


    def get_global_template_usage_count(self, template_name: str, is_global: bool) -> dict[str, int]:
        """
        Retrieves the number of types and objects which are using this Template (if it is global)

        Args:
            template_name (str): Name of CmdbSectionTemplate
            is_global (bool): If this CmdbSectionTemplate is global
        Returns:
            dict[str, int]: Counts of types and objects which use this CmdbSectionTemplate
        """
        counts: dict[str, int] = {
            'types': 0,
            'objects': 0
        }

        if not is_global:
            return counts

        type_filter: dict = {
            "global_template_ids":template_name
        }

        found_types: list[CmdbType] = self.types_manager.find_types(type_filter)

        if len(found_types) == 0:
            return counts

        counts['types'] = len(found_types)
        objects_count: int = 0

        a_type: CmdbType
        for a_type in found_types:
            objects: list[CmdbObject] = self.objects_manager.get_objects_by(type_id=a_type.public_id)
            objects_count += len(objects)

        counts['objects'] = objects_count

        return counts

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   HELPER FUNCTIONS                                                   #
# -------------------------------------------------------------------------------------------------------------------- #

    def handle_section_template_changes(self, new_params: dict, current_template: CmdbSectionTemplate) -> None:
        """
        Handles changes to global section templates and updates all used instances
        
        Args:
            params (dict): The new values for the section template
        """
        updated_field_names: list[str] = []

        for new_field in new_params['fields']:
            updated_field_names.append(new_field['name'])

        new_section_label: str = self.get_section_label_diff(new_params, CmdbSectionTemplate.to_json(current_template))
        field_diffs = self.get_fields_diff(new_params, CmdbSectionTemplate.to_json(current_template))

        types_to_change: list[CmdbType] = self.get_types_using_template(new_params['name'])

        for a_type in types_to_change:

            to_change_global_section: TypeFieldSection = a_type.get_section(new_params['name'])

            # Change label if it was changed
            if len(new_section_label) > 0:
                to_change_global_section.label = new_section_label

            # Remove deleted fields from type summary
            a_type.render_meta.summary.fields = [field_name for field_name in a_type.render_meta.summary.fields
                                                  if field_name not in field_diffs['deleted']]

            # Replace the old section fields with new section fields
            to_change_global_section.fields = []

            for a_field in new_params['fields']:
                to_change_global_section.fields.append(a_field['name'])

            # Update the section on the type
            for i, a_section in enumerate(a_type.render_meta.sections):

                if a_section.name == to_change_global_section.name:
                    a_type.render_meta.sections[i] = to_change_global_section
                    break

            # Remove deleted fields from type fields since they are not in the new fields
            a_type.fields = [field for field in a_type.fields if field['name'] not in field_diffs['deleted']]

            # Remove also the other section fields and add all as new fields
            a_type.fields = [field for field in a_type.fields if field['name'] not in updated_field_names]

            for new_field in new_params['fields']:
                a_type.fields.append(new_field)

            # Delete all deleted fields from objects
            self.cleanup_global_section_objects(a_type.public_id, field_diffs['deleted'])

            # Add all new created fields to objects
            new_field_names: list[str] = []

            for new_field in field_diffs['added']:
                new_field_names.append(new_field['name'])

            self.set_new_global_template_fields(a_type.public_id, new_field_names)

            #Update the type changes for the type
            self.types_manager.update_type(a_type.public_id, a_type)


    def get_section_label_diff(self, new_params: dict, current_params: dict) -> str:
        """
        Checks if the label of the global section template got changed
        
        Args:
            new_params (dict): Changes to current global section template
            current_params (dict): Current version of the global section template

        Returns:
            str: The new label if it is changed else empty string
        """
        diff: str = ""
        if new_params['label'] != current_params['label']:
            diff = new_params['label']

        return diff


    def get_fields_diff(self, new_params: dict, current_params: dict) -> dict:
        """
        Checks all fields of the template for differences

        Args:
            new_params (dict): The new version of the template
            current_params (dict): The current version of the template

        Returns:
            dict: All added, deleted and changed fields
        """
        deleted_fields: list[str] = []
        added_fields: list = []
        changed_fields: list = []

        processed_field_names: list[str] = []
        # Check for deleted fields
        for old_field in current_params['fields']:
            found: bool = False

            for new_field in new_params['fields']:

                if old_field['name'] == new_field['name']:
                    found = True
                    break

            # The old field is not found in new params, so it has to be deleted
            if not found:
                processed_field_names.append(old_field['name'])
                deleted_fields.append(old_field['name'])


        # Check for added fields
        for new_field in new_params['fields']:
            found: bool = False

            for old_field in current_params['fields']:

                if old_field['name'] == new_field['name']:
                    found = True
                    break

            if not found:
                processed_field_names.append(new_field['name'])
                added_fields.append(new_field)

        # Check remaining fields if there are any changes
        remaining_fields: list = [field for field in new_params['fields'] if field['name'] not in processed_field_names]

        for remaining_field in remaining_fields:
            for old_field in current_params['fields']:
                # Find the changes
                if remaining_field['name'] == old_field['name']:
                    difference = DeepDiff(old_field, remaining_field)
                    if len(difference) > 0:
                        changed_fields.append(remaining_field)

        return {
            'added': added_fields,
            'deleted': deleted_fields,
            'changed': changed_fields
        }


    def get_types_using_template(self, template_name: str) -> list[CmdbType]:
        """
        Retrives types which are using the current global template

        Args:
            template_name (str): Name of the global template

        Returns:
            list[CmdbType]: All types using the given global template
        """
        type_filter: dict = {
            "global_template_ids":template_name
        }

        return self.types_manager.find_types(type_filter)


    def cleanup_global_section_objects(self, type_id: int, section_field_names: list[str]) -> None:
        """
        Retrives all objects with the given type_id and deletes all fields provided

        Args:
            type_id (int): ID of the type for which the objects should be cleaned
            section_field_names (list[str]): list of all fields which should be deleted 
        """
        section_objects: list = self.objects_manager.get_objects_by(type_id=type_id)

        # remove section fields and update the objects
        an_object: CmdbObject
        for an_object in section_objects:
            an_object.fields = [field for field in an_object.fields if field['name'] not in section_field_names]

            self.objects_manager.update_object(an_object.public_id, an_object)


    def set_new_global_template_fields(self, type_id: int, new_field_names: list[str]) -> None:
        """
        Sets all new fields on every object

        Args:
            type_id (int): ID of the CmdbType
            new_field_names (list[str]): List of names of new fields
        """
        section_objects: list = self.objects_manager.get_objects_by(type_id=type_id)

        an_object: CmdbObject
        for an_object in section_objects:

            for a_field_name in new_field_names:
                an_object.fields.append({
                    'name': a_field_name,
                    'value': None
                })

            self.objects_manager.update_object(an_object.public_id, an_object)


    def cleanup_global_section_templates(self, template_name: str) -> None:
        """
        Removes the global section template from types, summaries and objects

        Args:
            template_name (str): The name of the global section template
        """
        found_types: list[CmdbType] = self.get_types_using_template(template_name)

        a_type: CmdbType
        for a_type in found_types:
            #remove the template_name from the type
            a_type.global_template_ids.remove(template_name)

            #remove the section from render_meta.sections
            type_template_section: TypeFieldSection = a_type.get_section(template_name)

            a_type.render_meta.sections = [section for section in a_type.render_meta.sections
                                           if section.name != type_template_section.name]

            #remove the fields in render_meta.sections.fields from type.fields
            template_section_field_names: list[str] = type_template_section.get_fields()

            a_type.fields = [field for field in a_type.fields if field['name'] not in template_section_field_names]

            #remove all fields from summary
            a_type.render_meta.summary.fields = [field_name for field_name in a_type.render_meta.summary.fields
                                                  if field_name not in template_section_field_names]

            #remove the fields from all objects which used this global section template
            self.cleanup_global_section_objects(a_type.public_id, template_section_field_names)

            #Update the type changes for the type
            self.types_manager.update_type(a_type.public_id, a_type)
