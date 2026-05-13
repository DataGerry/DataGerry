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

from pymongo import UpdateOne
# from deepdiff import DeepDiff

from cmdb.database import MongoDatabaseManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.types_manager import TypesManager
from cmdb.manager.objects_manager import ObjectsManager
from cmdb.manager.base_manager import BaseManager

from cmdb.models.user_model import CmdbUser
from cmdb.models.type_model import CmdbType, TypeFieldSection, TypeMultiDataSection, SectionType
from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.models.object_model import CmdbObject
from cmdb.framework.results import IterationResult
from cmdb.security.acl.permission import AccessControlPermission

from cmdb.errors.manager.section_templates_manager import (
    SectionTemplatesManagerInsertError,
    SectionTemplatesManagerIterationError,
    SectionTemplatesManagerGetError,
    SectionTemplatesManagerUpdateError,
    SectionTemplatesManagerDeleteError,
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

        found_types: list[CmdbType] = self.types_manager.find_types({"global_template_ids":template_name})

        if len(found_types) == 0:
            return counts

        counts['types'] = len(found_types)

        type_ids: list[int] = [a_type.public_id for a_type in found_types]
        matching_objects: list[dict[str, Any]] = self.objects_manager.find(criteria={"type_id": {"$in": type_ids}})

        counts['objects'] = len(matching_objects)

        return counts

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

    def update_section_template(
        self,
        public_id: int,
        updated_section_template: CmdbSectionTemplate | dict[str, Any]
    ) -> None:
        """TODO: document"""
        try:
            if isinstance(updated_section_template, CmdbSectionTemplate):
                updated_section_template: dict[str, Any] = CmdbSectionTemplate.to_json(updated_section_template)

            self.update(criteria={'public_id': public_id}, data=updated_section_template)
        except Exception as err:
            LOGGER.error("[update_section_template] Exception: %s. Type: %s", err, type(err))
            raise SectionTemplatesManagerUpdateError(str(err)) from err

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_section_template(self, public_id: int) -> bool:
        """TODO: document"""
        try:
            return self.delete({'public_id': public_id})
        except Exception as err:
            LOGGER.error("[delete_section_template] Exception: %s. Type: %s", err, type(err))
            raise SectionTemplatesManagerDeleteError(str(err)) from err

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   HELPER FUNCTIONS                                                   #
# -------------------------------------------------------------------------------------------------------------------- #

    def handle_section_template_changes(
        self,
        new_params: dict[str, Any],
        current_template: CmdbSectionTemplate
    ) -> None:
        """
        Handles changes to global section templates and updates all used instances
        
        Args:
            params (dict[str, Any]): The new values for the section template
        """
        # Only affects global section templates
        if not current_template.is_global:
            return

        new_section_label: str = self.get_section_label_diff(new_params, CmdbSectionTemplate.to_json(current_template))
        field_diffs: dict[str, Any] = self.get_fields_diff(new_params, CmdbSectionTemplate.to_json(current_template))

        types_to_change: list[CmdbType] = self.get_types_using_template(new_params['name'])

        for a_type in types_to_change:
            to_change_global_section: TypeFieldSection | TypeMultiDataSection = a_type.get_section(new_params['name'])

            if not to_change_global_section:
                continue

            if new_section_label:
                to_change_global_section.label = new_section_label

            deleted: set[str] = set(field_diffs['deleted'])
            # Remove deleted fields from type summary
            a_type.render_meta.summary.fields = [
                field_name
                for field_name in a_type.render_meta.summary.fields
                if field_name not in deleted
            ]

            # Replace the old section fields with new section fields
            to_change_global_section.fields = [
                f['name'] for f in new_params['fields']
            ]

            # Update the section on the type
            sections = a_type.render_meta.sections

            for i, section in enumerate(sections):
                if section.name == to_change_global_section.name:
                    sections[i] = to_change_global_section
                    break

            section_fields: set[str] = {f['name'] for f in new_params['fields']}

            a_type.fields = [
                f for f in a_type.fields
                if f['name'] not in deleted and f['name'] not in section_fields
            ]

            a_type.fields.extend(new_params['fields'])

            # Delete all deleted fields from objects
            self.cleanup_global_section_objects(
                a_type.public_id,
                field_diffs['deleted'],
                current_template.type,
                current_template.name
            )


            self.set_new_global_template_fields(
                a_type.public_id,
                field_diffs['added'],
                current_template.type,
                current_template.name
            )

            # Update the type changes for the type
            self.types_manager.update_type(a_type.public_id, a_type)


    def get_section_label_diff(self, new_params: dict[str, Any], current_params: dict[str, Any]) -> str:
        """
        Checks if the label of the global section template got changed
        
        Args:
            new_params (dict[str, Any]): Changes to current global section template
            current_params (dict[str, Any]): Current version of the global section template

        Returns:
            str: The new label if it is changed else empty string
        """
        return new_params['label'] if new_params['label'] != current_params['label'] else ""


    def get_fields_diff(self, new_params: dict, current_params: dict) -> dict[str, Any]:
        """
        Checks all fields of the template for differences

        Args:
            new_params (dict): The new version of the template
            current_params (dict): The current version of the template

        Returns:
            dict[str, Any]: All added, deleted and changed fields
        """
        new_fields = {f['name']: f for f in new_params['fields']}
        old_fields = {f['name']: f for f in current_params['fields']}

        new_names = set(new_fields.keys())
        old_names = set(old_fields.keys())

        # Added & deleted
        added_names = new_names - old_names
        deleted_names = old_names - new_names
        # common_names = new_names & old_names

        added_fields = [new_fields[name] for name in added_names]
        deleted_fields = list(deleted_names)

        # Changed
        # changed_fields = []
        # for name in common_names:
        #     if DeepDiff(old_fields[name], new_fields[name]):
        #         changed_fields.append(new_fields[name])

        return {
            'added': added_fields,
            'deleted': deleted_fields,
            # 'changed': changed_fields
        }


    def get_types_using_template(self, template_name: str) -> list[CmdbType]:
        """
        Retrives types which are using the current global template

        Args:
            template_name (str): Name of the global template

        Returns:
            list[CmdbType]: All types using the given global template
        """
        return self.types_manager.find_types({"global_template_ids": template_name})


    def cleanup_global_section_objects(
        self,
        type_id: int,
        section_field_names: list[str],
        section_type: str,
        section_mame: str,
        delete_mode: bool = False
    ) -> None:
        """
        Retrives all objects with the given type_id and deletes all fields provided

        Args:
            type_id (int): ID of the type for which the objects should be cleaned
            section_field_names (list[str]): list of all fields which should be deleted 
        """
        self.cleanup_section_fields(type_id, section_field_names)

        if section_type == SectionType.MDS_SECTION:
            if delete_mode:
                self.delete_mds_section_from_objects(type_id, section_mame)
            else:
                self.cleanup_mds_fields(type_id, section_field_names, section_mame)


    def delete_mds_section_from_objects(
        self,
        type_id: int,
        section_name: str
    ) -> None:
        """
        Removes an entire multi-data-section from all objects of a given type.

        This deletes the full section container including all values and data entries.

        Args:
            type_id (int): ID of the CmdbType
            section_name (str): Name of the multi-data-section to remove
        """
        criteria: dict = {
            "type_id": type_id
        }

        update: dict = {
            "multi_data_sections": {
                "section_id": section_name
            }
        }

        self.objects_manager.update_many_pull(criteria, update)



    def cleanup_section_fields(self, type_id: int, section_field_names: list[str]) -> None:
        """TODO: document"""
        if not section_field_names:
            return

        self.objects_manager.update_many_pull(
            {"type_id": type_id},
            {
                "fields": {
                    "name": {"$in": section_field_names}
                }
            }
        )


    def cleanup_mds_fields(self, type_id: int, section_field_names: list[str], section_name: str) -> None:
        """TODO: document"""
        field_names_set = set(section_field_names)

        # Fetch only relevant objects
        objects: list[CmdbObject] = self.objects_manager.get_objects_by(
            type_id=type_id,
            **{
                "multi_data_sections.section_id": section_name
            }
        )

        bulk_ops = []

        # TODO: continue here
        for obj in objects:
            updated = False

            for mds in obj.multi_data_sections:
                if mds['section_id'] != section_name:
                    continue

                for entry in mds.get('values', []):
                    original_len = len(entry['data'])

                    entry['data'] = [
                        field for field in entry['data']
                        if field['name'] not in field_names_set
                    ]

                    if len(entry['data']) != original_len:
                        updated = True

            if updated:
                bulk_ops.append(
                    UpdateOne(
                        {"public_id": obj.public_id},
                        {"$set": {"multi_data_sections": obj.multi_data_sections}}
                    )
                )

        if bulk_ops:
            self.objects_manager.bulk_write(bulk_ops)


    def set_new_global_template_fields(
        self,
        type_id: int,
        new_fields: list[dict],
        section_type: str,
        section_name: str
    ) -> None:
        """TODO: document"""
        if not new_fields:
            return

        if new_fields and not isinstance(new_fields[0], dict):
            raise ValueError("new_fields must be list[dict]")

        # ---- 1. HANDLE FLAT FIELDS SAFELY ----
        objects = self.objects_manager.get_objects_by(type_id=type_id)

        bulk_ops = []

        for obj in objects:
            existing_names = {f["name"] for f in obj.fields}

            fields_to_add = [
                {
                    "name": f["name"],
                    "type": f["type"],
                    "value": f.get("default", None)
                }
                for f in new_fields
                if f["name"] not in existing_names
            ]

            if fields_to_add:
                obj.fields.extend(fields_to_add)

                bulk_ops.append(
                    UpdateOne(
                        {"public_id": obj.public_id},
                        {"$set": {"fields": obj.fields}}
                    )
                )

        if bulk_ops:
            self.objects_manager.bulk_write(bulk_ops)

        # ---- 2. HANDLE MDS ----
        if section_type != SectionType.MDS_SECTION:
            return

        objects = self.objects_manager.get_objects_by(
            type_id=type_id,
            multi_data_sections={
                "$elemMatch": {"section_id": section_name}
            }
        )

        bulk_ops = []

        for obj in objects:
            updated = False

            for mds in obj.multi_data_sections:
                if mds["section_id"] != section_name:
                    continue

                for entry in mds.get("values", []):
                    existing_names = {f["name"] for f in entry["data"]}

                    for f in new_fields:
                        if f["name"] not in existing_names:
                            entry["data"].append({
                                "name": f["name"],
                                "type": f["type"],
                                "value": f.get("default", None)
                            })
                            updated = True

            if updated:
                bulk_ops.append(
                    UpdateOne(
                        {"public_id": obj.public_id},
                        {"$set": {"multi_data_sections": obj.multi_data_sections}}
                    )
                )

        if bulk_ops:
            self.objects_manager.bulk_write(bulk_ops)


    def cleanup_global_section_templates(self, template_name: str, delete_mode: bool = False) -> None:
        """
        Removes the global section template from types, summaries and objects

        Args:
            template_name (str): The name of the global section template
        """
        found_types: list[CmdbType] = self.get_types_using_template(template_name)

        for a_type in found_types:
            if template_name in a_type.global_template_ids:
                a_type.global_template_ids.remove(template_name)

            type_template_section: TypeFieldSection | TypeMultiDataSection | None = a_type.get_section(template_name)
            if not type_template_section:
                continue

            template_field_names = set(type_template_section.get_fields())

            # remove from type fields
            a_type.fields = [
                field for field in a_type.fields
                if field['name'] not in template_field_names
            ]

            # remove from summary
            a_type.render_meta.summary.fields = [
                field_name for field_name in a_type.render_meta.summary.fields
                if field_name not in template_field_names
            ]

            # remove section
            a_type.render_meta.sections = [
                section for section in a_type.render_meta.sections
                if section.name != template_name
            ]

            # remove from objects (flat + mds)
            self.cleanup_global_section_objects(
                a_type.public_id,
                list(template_field_names),
                type_template_section.type,
                template_name,
                delete_mode
            )

            self.types_manager.update_type(a_type.public_id, a_type)


    def cleanup_global_section_from_type(
        self,
        type_id: int,
        template_name: str,
        expected_field_names: list[str] | None = None,
        expected_section_type: str | None = None,
    ) -> None:
        """
        Removes a global section template from a specific type and cleans up
        all related fields and object data

        Looks the template's section up on the type to discover which fields it
        contributed and what kind of section it is. When the caller has already
        wiped the section from the type (e.g. via a blind update_type that
        persisted the frontend's payload before invoking this cleanup), it can
        pass 'expected_field_names' and 'expected_section_type' as a pre-update
        snapshot so cleanup can still strip the orphaned field definitions from
        type.fields / type.render_meta.summary.fields and remove the matching
        values from the type's CmdbObjects

        Idempotent: silently no-ops when the type does not exist, when the
        section is missing AND no hints were supplied, or when nothing on the
        type matches the field names to remove

        Args:
            type_id (int): ID of the type
            template_name (str): Name of the global section template
            expected_field_names (list[str] | None): Field names the template
                contributed, captured from the pre-update snapshot. Required
                when the section has already been removed from the type
            expected_section_type (str | None): The 'type' string of the section
                ('section' or 'multi-data-section'), captured from the same
                snapshot. Required alongside 'expected_field_names' so
                delete_global_section_from_objects routes correctly
        """
        # --- 1. Load type ---
        a_type: CmdbType = self.types_manager.get_type(type_id, as_dict=False)

        if not a_type:
            return

        # --- 2. Resolve field names and section type (from the type if still present,
        #        otherwise from the caller-supplied snapshot) ---
        type_template_section: TypeFieldSection | TypeMultiDataSection | None = a_type.get_section(template_name)

        if type_template_section is not None:
            template_field_names: list[str] = type_template_section.get_fields()
            section_type: str = type_template_section.type
        elif expected_field_names is not None and expected_section_type is not None:
            template_field_names = expected_field_names
            section_type = expected_section_type
        else:
            return

        # --- 3. Clean type schema ---

        # remove from global_template_ids (safe)
        a_type.global_template_ids = [
            tid for tid in (a_type.global_template_ids or [])
            if tid != template_name
        ]

        # remove fields from type.fields
        a_type.fields = [
            field for field in a_type.fields
            if field['name'] not in template_field_names
        ]

        # remove from summary
        a_type.render_meta.summary.fields = [
            field_name for field_name in a_type.render_meta.summary.fields
            if field_name not in template_field_names
        ]

        # remove section from render_meta.sections (idempotent if already gone)
        a_type.render_meta.sections = [
            section for section in a_type.render_meta.sections
            if section.name != template_name
        ]

        # --- 4. Persist updated type ---
        self.types_manager.update_type(a_type.public_id, a_type)

        # --- 5. Clean objects (flat + MDS) ---
        self.delete_global_section_from_objects(
            a_type.public_id,
            template_field_names,
            section_type,
            template_name
        )


    def delete_global_section_from_objects(
        self,
        type_id: int,
        section_field_names: list[str],
        section_type: str,
        section_name: str
    ) -> None:
        """
        Removes all fields of a global section template from objects of a given type.
        If the section is a multi-data-section, the entire MDS container is removed.

        Args:
            type_id (int): ID of the type
            section_field_names (list[str]): Field names belonging to the section
            section_type (str): Type of the section ('section' or 'multi-data-section')
            section_name (str): Name of the section (used for MDS removal)
        """

        # --- 1. Remove flat fields from objects ---
        if section_field_names:
            self.objects_manager.update_many_pull(
                criteria={"type_id": type_id},
                update={
                    "fields": {
                        "name": {"$in": section_field_names}
                    }
                }
            )

        # --- 2. Remove MDS section completely (if applicable) ---
        if section_type == SectionType.MDS_SECTION:
            self.delete_mds_section_from_objects(type_id, section_name)