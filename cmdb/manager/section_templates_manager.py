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
Implementation of the SectionTemplatesManager

The manager owns CRUD for CmdbSectionTemplates plus the propagation of *global* section
template changes onto every CmdbType that uses the template and onto those types' CmdbObjects:

- CRUD: insert / iterate / get / update / delete a single CmdbSectionTemplate document.
- Usage reporting: how many types / objects reference a global template.
- Change propagation (``handle_section_template_changes``): when a global template's label or
  field set changes, the matching section is re-applied to every consuming CmdbType (label,
  section field list, type.fields definitions, summary) and the change is materialized on the
  types' CmdbObjects - added fields are seeded with the field definition's default, deleted
  fields are stripped.
- Teardown: removing a global template (or a single type's use of it) from types, summaries
  and objects.

Every field - regular or MDS - is recorded in the CmdbObject's flat ``fields`` array, which is
the canonical field list the frontend renders from. A multi-data section ('multi-data-section',
MDS) field additionally carries its per-row values under ``multi_data_sections[].values[].data``.
Object-level propagation therefore always writes to ``fields`` and, for MDS sections, also to the
MDS rows (see ``set_new_global_template_fields``).

Schema dict keys are referenced through the CmdbObjectKey / CmdbObjectFieldKey /
CmdbObjectMdsKey / CmdbObjectMdsRowKey / FieldKey enums instead of bare string literals; raw
MongoDB operators ('$set', '$push', ...) stay as literals.
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.database import MongoDatabaseManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.types_manager import TypesManager
from cmdb.manager.objects_manager import ObjectsManager
from cmdb.manager.base_manager import BaseManager

from cmdb.models.user_model import CmdbUser
from cmdb.models.type_model import CmdbType, TypeFieldSection, TypeMultiDataSection, SectionType, FieldKey
from cmdb.models.object_model import (
    CmdbObjectKey,
    CmdbObjectFieldKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
)
from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
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

# Identity key shared by every CmdbDAO collection (the section template collection has no
# domain-specific key enum of its own)
PUBLIC_ID_FIELD: str = 'public_id'

# Key of the CmdbType document array listing the names of the global templates a type uses;
# queried as a plain field on the types collection
GLOBAL_TEMPLATE_IDS_FIELD: str = 'global_template_ids'


# -------------------------------------------------------------------------------------------------------------------- #
#                                            SectionTemplatesManager - CLASS                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class SectionTemplatesManager(BaseManager):
    """
    Handles the interaction between the SectionTemplates API and the database, including the
    propagation of global section template changes onto consuming CmdbTypes and CmdbObjects

    Extends: BaseManager
    """

    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        """
        Initializes the SectionTemplatesManager and its collaborator managers

        Composes a TypesManager and an ObjectsManager because global-template propagation has to
        read and mutate CmdbTypes and CmdbObjects alongside the template collection

        Args:
            dbm (MongoDatabaseManager): Database connection
            database (str | None): Target database name; None selects the connection's default
        """
        self.types_manager = TypesManager(dbm, database)
        self.objects_manager = ObjectsManager(dbm, database)

        super().__init__(CmdbSectionTemplate.COLLECTION, dbm, database)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

    def insert_section_template(self, data: dict[str, Any]) -> int:
        """
        Inserts a new CmdbSectionTemplate

        Args:
            data (dict[str, Any]): Initialisation data for the CmdbSectionTemplate

        Raises:
            SectionTemplatesManagerInsertError: Raised when inserting into the database fails

        Returns:
            int: public_id of the new CmdbSectionTemplate
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
                user: CmdbUser | None = None,
                permission: AccessControlPermission | None = None) -> IterationResult[CmdbSectionTemplate]:
        """
        Performs an aggregation on the database

        Args:
            builder_params (BuilderParameters): Contains input to identify the target of action
            user (CmdbUser | None): User requesting this action. Defaults to None
            permission (AccessControlPermission | None): Permission to check for the user. Defaults to None

        Raises:
            SectionTemplatesManagerIterationError: Raised when building the IterationResult fails

        Returns:
            IterationResult[CmdbSectionTemplate]: Result which matches the BuilderParameters
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


    def get_section_template(self, public_id: int) -> CmdbSectionTemplate | None:
        """
        Retrieves a CmdbSectionTemplate from the database with the given public_id

        Args:
            public_id (int): public_id of the CmdbSectionTemplate which should be retrieved

        Raises:
            SectionTemplatesManagerGetError: Raised if the CmdbSectionTemplate could not be retrieved

        Returns:
            CmdbSectionTemplate | None: The requested CmdbSectionTemplate, or None when it does not exist
        """
        try:
            found_template: CmdbSectionTemplate | None = None
            section_template = self.get_one(public_id)

            if section_template:
                found_template = CmdbSectionTemplate(**section_template)

            return found_template
        except Exception as err:
            raise SectionTemplatesManagerGetError(str(err)) from err


    def get_global_template_usage_count(self, template_name: str, is_global: bool) -> dict[str, int]:
        """
        Counts the types and objects using a (global) CmdbSectionTemplate

        A non-global template is used by exactly one type and is never propagated, so it reports
        zero. The type ids are resolved with a ``distinct`` projection and the objects with a count
        query, so neither the CmdbTypes nor the CmdbObjects are materialised

        Args:
            template_name (str): Name of the CmdbSectionTemplate
            is_global (bool): Whether the CmdbSectionTemplate is global

        Returns:
            dict[str, int]: {'types': <count>, 'objects': <count>} for the template
        """
        counts: dict[str, int] = {
            'types': 0,
            'objects': 0,
        }

        if not is_global:
            return counts

        type_ids: list[int] = self.types_manager.get_distinct(
            PUBLIC_ID_FIELD, {GLOBAL_TEMPLATE_IDS_FIELD: template_name},
        )

        if not type_ids:
            return counts

        counts['types'] = len(type_ids)
        counts['objects'] = self.objects_manager.count_documents({CmdbObjectKey.TYPE_ID: {"$in": type_ids}})

        return counts

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

    def update_section_template(
        self,
        public_id: int,
        updated_section_template: CmdbSectionTemplate | dict[str, Any]
    ) -> None:
        """
        Persists changes to a single CmdbSectionTemplate document

        Does not propagate the change to consuming types/objects - the caller runs
        ``handle_section_template_changes`` for that

        Args:
            public_id (int): public_id of the CmdbSectionTemplate to update
            updated_section_template (CmdbSectionTemplate | dict[str, Any]): New template state,
                either a model instance or its json/dict form

        Raises:
            SectionTemplatesManagerUpdateError: Raised when the update fails
        """
        try:
            if isinstance(updated_section_template, CmdbSectionTemplate):
                updated_section_template = CmdbSectionTemplate.to_json(updated_section_template)

            self.update(criteria={PUBLIC_ID_FIELD: public_id}, data=updated_section_template)
        except Exception as err:
            LOGGER.error("[update_section_template] Exception: %s. Type: %s", err, type(err))
            raise SectionTemplatesManagerUpdateError(str(err)) from err

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_section_template(self, public_id: int) -> bool:
        """
        Deletes a single CmdbSectionTemplate document by public_id

        Only removes the template document itself; stripping the template from consuming types
        and objects is done separately via ``cleanup_global_section_templates``

        Args:
            public_id (int): public_id of the CmdbSectionTemplate to delete

        Raises:
            SectionTemplatesManagerDeleteError: Raised when the deletion fails

        Returns:
            bool: True when a document was deleted
        """
        try:
            return self.delete({PUBLIC_ID_FIELD: public_id})
        except Exception as err:
            LOGGER.error("[delete_section_template] Exception: %s. Type: %s", err, type(err))
            raise SectionTemplatesManagerDeleteError(str(err)) from err

# -------------------------------------------------------------------------------------------------------------------- #
#                                            GLOBAL TEMPLATE PROPAGATION                                               #
# -------------------------------------------------------------------------------------------------------------------- #

    def handle_section_template_changes(
        self,
        new_params: dict[str, Any],
        current_template: CmdbSectionTemplate
    ) -> None:
        """
        Propagates a global section template change to every CmdbType that uses it

        No-ops for non-global templates and for payloads without a template name. The label and
        field-set diffs are computed once, then applied per consuming type via
        ``_apply_template_changes_to_type``

        Args:
            new_params (dict[str, Any]): The new values for the section template (the update payload)
            current_template (CmdbSectionTemplate): The pre-update template state
        """
        if not current_template.is_global:
            return

        template_name: Any = new_params.get('name')

        if not template_name:
            return

        current_params: dict[str, Any] = CmdbSectionTemplate.to_json(current_template)
        new_section_label: str = self.get_section_label_diff(new_params, current_params)
        field_diffs: dict[str, Any] = self.get_fields_diff(new_params, current_params)

        for a_type in self.get_types_using_template(template_name):
            self._apply_template_changes_to_type(a_type, new_params, field_diffs, new_section_label, current_template)


    def _apply_template_changes_to_type(
        self,
        a_type: CmdbType,
        new_params: dict[str, Any],
        field_diffs: dict[str, Any],
        new_section_label: str,
        current_template: CmdbSectionTemplate,
    ) -> None:
        """
        Applies one global template change to a single consuming CmdbType and its objects

        Updates the type's section label and field list, refreshes the field definitions on
        ``type.fields``, strips deleted fields from the summary, then materializes the diff on
        the type's CmdbObjects (deleted fields removed, added fields seeded with their default)
        and persists the type. Silently skips a type that no longer carries the section

        Args:
            a_type (CmdbType): The consuming type to update
            new_params (dict[str, Any]): The update payload (carries 'name', 'label', 'fields')
            field_diffs (dict[str, Any]): {'added': [field defs], 'deleted': [field names]}
            new_section_label (str): The changed section label, or '' when unchanged
            current_template (CmdbSectionTemplate): The pre-update template (for section type/name)
        """
        template_name: str = new_params['name']
        new_fields: list[dict[str, Any]] = new_params.get('fields', [])

        section: TypeFieldSection | TypeMultiDataSection | None = a_type.get_section(template_name)

        if not section:
            return

        if new_section_label:
            section.label = new_section_label

        deleted: set[str] = set(field_diffs['deleted'])
        section_field_names: set[str] = {f[FieldKey.NAME] for f in new_fields}

        # Strip deleted fields from the type summary
        a_type.render_meta.summary.fields = [
            field_name
            for field_name in a_type.render_meta.summary.fields
            if field_name not in deleted
        ]

        # Replace the section's field-name list with the new set
        section.fields = [f[FieldKey.NAME] for f in new_fields]

        # Swap the updated section back into the type's section layout
        for i, existing_section in enumerate(a_type.render_meta.sections):
            if existing_section.name == section.name:
                a_type.render_meta.sections[i] = section
                break

        # Refresh the section's field definitions on the type (drop old + deleted, add new)
        a_type.fields = [
            f for f in a_type.fields
            if f[FieldKey.NAME] not in deleted and f[FieldKey.NAME] not in section_field_names
        ]
        a_type.fields.extend(new_fields)

        # Materialize the diff on the type's objects
        self.cleanup_global_section_objects(
            a_type.public_id,
            field_diffs['deleted'],
            current_template.type,
            current_template.name,
        )
        self.set_new_global_template_fields(
            a_type.public_id,
            field_diffs['added'],
            current_template.type,
            current_template.name,
        )

        self.types_manager.update_type(a_type.public_id, a_type)


    def get_section_label_diff(self, new_params: dict[str, Any], current_params: dict[str, Any]) -> str:
        """
        Returns the section label when it changed between the two template versions

        Args:
            new_params (dict[str, Any]): Changes to the current global section template
            current_params (dict[str, Any]): Current version of the global section template

        Returns:
            str: The new label when it changed, else an empty string
        """
        new_label: Any = new_params.get('label')

        return new_label if new_label != current_params.get('label') else ""


    def get_fields_diff(self, new_params: dict[str, Any], current_params: dict[str, Any]) -> dict[str, Any]:
        """
        Diffs the template field sets, reporting added field definitions and deleted field names

        Field-property changes on a field that exists in both versions need no separate handling:
        the consuming type's definitions are fully replaced from ``new_params`` by
        ``_apply_template_changes_to_type``

        Args:
            new_params (dict[str, Any]): The new version of the template
            current_params (dict[str, Any]): The current version of the template

        Returns:
            dict[str, Any]: {'added': list[field def], 'deleted': list[field name]}
        """
        new_fields = {f[FieldKey.NAME]: f for f in new_params.get('fields', [])}
        old_names = {f[FieldKey.NAME] for f in current_params.get('fields', [])}

        new_names = set(new_fields.keys())

        return {
            'added': [new_fields[name] for name in new_names - old_names],
            'deleted': list(old_names - new_names),
        }


    def get_types_using_template(self, template_name: str) -> list[CmdbType]:
        """
        Retrieves the types using the given global template

        Args:
            template_name (str): Name of the global template

        Returns:
            list[CmdbType]: All types referencing the given global template
        """
        return self.types_manager.find_types({GLOBAL_TEMPLATE_IDS_FIELD: template_name})

# -------------------------------------------------------------------------------------------------------------------- #
#                                            OBJECT-LEVEL FIELD MUTATIONS                                              #
# -------------------------------------------------------------------------------------------------------------------- #

    def set_new_global_template_fields(
        self,
        type_id: int,
        new_fields: list[dict[str, Any]],
        section_type: str,
        section_name: str
    ) -> None:
        """
        Seeds newly added template fields onto the CmdbObjects of a type

        Every field - regardless of section kind - is added to the object's flat ``fields``
        array, which is the canonical field list the frontend renders from. An MDS section field
        is additionally added to each existing row's ``data`` so per-row values exist too. Each
        seeded entry takes the field definition's default value (the 'value' key)

        Args:
            type_id (int): public_id of the type whose objects should be seeded
            new_fields (list[dict[str, Any]]): The added field definitions
            section_type (str): The section kind (SectionType.SECTION / SectionType.MDS_SECTION)
            section_name (str): The section's name (the MDS section_id for MDS sections)

        Raises:
            ValueError: If new_fields is non-empty but not a list of dicts
        """
        if not new_fields:
            return

        if not isinstance(new_fields[0], dict):
            raise ValueError("new_fields must be list[dict]")

        self._add_flat_fields_to_objects(type_id, new_fields)

        if section_type == SectionType.MDS_SECTION:
            self._add_mds_fields_to_objects(type_id, new_fields, section_name)


    def _add_flat_fields_to_objects(self, type_id: int, new_fields: list[dict[str, Any]]) -> None:
        """
        Adds each new field to the flat ``fields`` array of the type's objects that lack it

        Used for every section kind - the flat ``fields`` array is the canonical field list the
        frontend reads, so MDS fields are recorded here too (their per-row values are seeded
        separately by ``_add_mds_fields_to_objects``). One ``$push`` update per field, scoped to
        objects whose ``fields`` array lacks that name, so no objects are materialised. The
        seeded value is the field definition's default

        Args:
            type_id (int): public_id of the type whose objects should gain the fields
            new_fields (list[dict[str, Any]]): The added field definitions
        """
        name_path: str = f"{CmdbObjectKey.FIELDS.value}.{CmdbObjectFieldKey.NAME.value}"

        for field_def in new_fields:
            entry: dict[str, Any] = {
                CmdbObjectFieldKey.NAME: field_def[FieldKey.NAME],
                CmdbObjectFieldKey.TYPE: field_def[FieldKey.TYPE],
                CmdbObjectFieldKey.VALUE: field_def.get(FieldKey.VALUE, None),
            }

            self.objects_manager.update_many_raw(
                filter_query={
                    CmdbObjectKey.TYPE_ID: type_id,
                    name_path: {"$ne": field_def[FieldKey.NAME]},
                },
                update={"$push": {CmdbObjectKey.FIELDS: entry}},
            )


    def _add_mds_fields_to_objects(
        self,
        type_id: int,
        new_fields: list[dict[str, Any]],
        section_name: str,
    ) -> None:
        """
        Adds each new MDS-section field to every existing row of the matching MDS section

        Only rows whose ``data`` lacks a field gain it (seeded with the field's default); rows
        and objects already carrying it are left untouched. Objects with the section but no rows
        get nothing, matching the per-row storage model

        One server-side ``$push`` per field (no objects loaded), scoped via positional array filters
        to the matching section (``$[s]``) and only the rows whose ``data`` lacks the field name
        (``$[v]``). Positional array filters are a MongoDB 3.6 feature

        Args:
            type_id (int): public_id of the type whose objects should gain the fields
            new_fields (list[dict[str, Any]]): The added field definitions
            section_name (str): The MDS section_id to seed
        """
        mds_path: str = CmdbObjectKey.MULTI_DATA_SECTIONS.value
        section_id_key: str = CmdbObjectMdsKey.SECTION_ID.value
        values_key: str = CmdbObjectMdsKey.VALUES.value
        data_key: str = CmdbObjectMdsRowKey.DATA.value
        name_key: str = CmdbObjectFieldKey.NAME.value

        for field_def in new_fields:
            field_name: str = field_def[FieldKey.NAME]
            entry: dict[str, Any] = {
                CmdbObjectFieldKey.NAME: field_name,
                CmdbObjectFieldKey.TYPE: field_def[FieldKey.TYPE],
                CmdbObjectFieldKey.VALUE: field_def.get(FieldKey.VALUE, None),
            }

            self.objects_manager.update_many_raw(
                filter_query={
                    CmdbObjectKey.TYPE_ID: type_id,
                    f"{mds_path}.{section_id_key}": section_name,
                },
                update={"$push": {f"{mds_path}.$[s].{values_key}.$[v].{data_key}": entry}},
                array_filters=[
                    {f"s.{section_id_key}": section_name},
                    {f"v.{data_key}.{name_key}": {"$ne": field_name}},
                ],
            )

# -------------------------------------------------------------------------------------------------------------------- #
#                                                     CLEANUP                                                          #
# -------------------------------------------------------------------------------------------------------------------- #

    def cleanup_global_section_objects(
        self,
        type_id: int,
        section_field_names: list[str],
        section_type: str,
        section_name: str,
        delete_mode: bool = False
    ) -> None:
        """
        Removes the given section fields from the CmdbObjects of a type

        Always strips the named fields from the flat ``fields`` array (a no-op for objects that
        don't carry them). For an MDS section it additionally either drops the whole MDS section
        container (delete_mode) or removes just the named fields from every row

        Args:
            type_id (int): public_id of the type whose objects should be cleaned
            section_field_names (list[str]): Field names to remove
            section_type (str): The section kind (SectionType.SECTION / SectionType.MDS_SECTION)
            section_name (str): The section's name (the MDS section_id for MDS sections)
            delete_mode (bool): When True and the section is MDS, drop the whole section container
                instead of just its fields. Defaults to False
        """
        self.cleanup_section_fields(type_id, section_field_names)

        if section_type == SectionType.MDS_SECTION:
            if delete_mode:
                self.delete_mds_section_from_objects(type_id, section_name)
            else:
                self.cleanup_mds_fields(type_id, section_field_names, section_name)


    def cleanup_section_fields(self, type_id: int, section_field_names: list[str]) -> None:
        """
        Removes the named flat fields from every CmdbObject of a type via a single ``$pull``

        Args:
            type_id (int): public_id of the type whose objects should be cleaned
            section_field_names (list[str]): Field names to remove from the flat ``fields`` array
        """
        if not section_field_names:
            return

        self.objects_manager.update_many_pull(
            {CmdbObjectKey.TYPE_ID: type_id},
            {CmdbObjectKey.FIELDS: {CmdbObjectFieldKey.NAME: {"$in": section_field_names}}},
        )


    def cleanup_mds_fields(self, type_id: int, section_field_names: list[str], section_name: str) -> None:
        """
        Removes the named fields from every row of an MDS section on a type's objects

        A single server-side ``$pull`` (no objects loaded), scoped via a positional array filter to
        the matching section (``$[s]``); it drops every ``data`` entry across all rows (``$[]``)
        whose name is in ``section_field_names``. Positional array filters are a MongoDB 3.6 feature

        Args:
            type_id (int): public_id of the type whose objects should be cleaned
            section_field_names (list[str]): Field names to remove from each MDS row
            section_name (str): The MDS section_id to clean
        """
        if not section_field_names:
            return

        mds_path: str = CmdbObjectKey.MULTI_DATA_SECTIONS.value
        section_id_key: str = CmdbObjectMdsKey.SECTION_ID.value
        values_key: str = CmdbObjectMdsKey.VALUES.value
        data_key: str = CmdbObjectMdsRowKey.DATA.value
        name_key: str = CmdbObjectFieldKey.NAME.value

        self.objects_manager.update_many_raw(
            filter_query={
                CmdbObjectKey.TYPE_ID: type_id,
                f"{mds_path}.{section_id_key}": section_name,
            },
            update={"$pull": {
                f"{mds_path}.$[s].{values_key}.$[].{data_key}": {name_key: {"$in": section_field_names}}
            }},
            array_filters=[{f"s.{section_id_key}": section_name}],
        )


    def delete_mds_section_from_objects(self, type_id: int, section_name: str) -> None:
        """
        Removes an entire multi-data-section container from all objects of a type

        Drops the whole section (all rows and their data), not just individual fields, via a
        single ``$pull`` on ``multi_data_sections``

        Args:
            type_id (int): public_id of the type whose objects should be cleaned
            section_name (str): The MDS section_id to remove
        """
        self.objects_manager.update_many_pull(
            {CmdbObjectKey.TYPE_ID: type_id},
            {CmdbObjectKey.MULTI_DATA_SECTIONS: {CmdbObjectMdsKey.SECTION_ID: section_name}},
        )


    def cleanup_global_section_templates(self, template_name: str, delete_mode: bool = False) -> None:
        """
        Removes a global section template from every type that uses it, and from their objects

        For each consuming type: drops the template name from ``global_template_ids``, removes the
        section's field definitions from ``type.fields`` and the summary, removes the section from
        the layout, cleans the objects, and persists the type

        Args:
            template_name (str): Name of the global section template
            delete_mode (bool): Forwarded to object cleanup; when True drops a whole MDS section
                container instead of just its fields. Defaults to False
        """
        for a_type in self.get_types_using_template(template_name):
            if template_name in a_type.global_template_ids:
                a_type.global_template_ids.remove(template_name)

            type_template_section: TypeFieldSection | TypeMultiDataSection | None = a_type.get_section(template_name)

            if not type_template_section:
                continue

            template_field_names: set[str] = set(type_template_section.get_fields())

            a_type.fields = [
                field for field in a_type.fields
                if field[FieldKey.NAME] not in template_field_names
            ]

            a_type.render_meta.summary.fields = [
                field_name for field_name in a_type.render_meta.summary.fields
                if field_name not in template_field_names
            ]

            a_type.render_meta.sections = [
                section for section in a_type.render_meta.sections
                if section.name != template_name
            ]

            self.cleanup_global_section_objects(
                a_type.public_id,
                list(template_field_names),
                type_template_section.type,
                template_name,
                delete_mode,
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
        Removes a global section template from a specific type and cleans up all related data

        Looks the template's section up on the type to discover which fields it contributed and
        what kind of section it is. When the caller has already wiped the section from the type
        (e.g. via a blind update_type that persisted the frontend's payload before invoking this
        cleanup), it can pass 'expected_field_names' and 'expected_section_type' as a pre-update
        snapshot so cleanup can still strip the orphaned field definitions from type.fields /
        type.render_meta.summary.fields and remove the matching values from the type's CmdbObjects

        Idempotent: silently no-ops when the type does not exist, when the section is missing AND
        no hints were supplied, or when nothing on the type matches the field names to remove

        Args:
            type_id (int): public_id of the type
            template_name (str): Name of the global section template
            expected_field_names (list[str] | None): Field names the template contributed,
                captured from the pre-update snapshot. Required when the section has already been
                removed from the type. Defaults to None
            expected_section_type (str | None): The section's 'type' string ('section' or
                'multi-data-section'), captured from the same snapshot. Required alongside
                'expected_field_names' so cleanup routes correctly. Defaults to None
        """
        # --- 1. Load type ---
        a_type: CmdbType = self.types_manager.get_type_instance(type_id)

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
        a_type.global_template_ids = [
            tid for tid in (a_type.global_template_ids or [])
            if tid != template_name
        ]

        a_type.fields = [
            field for field in a_type.fields
            if field[FieldKey.NAME] not in template_field_names
        ]

        a_type.render_meta.summary.fields = [
            field_name for field_name in a_type.render_meta.summary.fields
            if field_name not in template_field_names
        ]

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
            template_name,
        )


    def delete_global_section_from_objects(
        self,
        type_id: int,
        section_field_names: list[str],
        section_type: str,
        section_name: str
    ) -> None:
        """
        Removes a global section template's fields from the objects of a type

        Strips the named fields from the flat ``fields`` array; for an MDS section it then drops
        the whole MDS section container as well

        Args:
            type_id (int): public_id of the type whose objects should be cleaned
            section_field_names (list[str]): Field names belonging to the section
            section_type (str): The section kind (SectionType.SECTION / SectionType.MDS_SECTION)
            section_name (str): The section's name (used for MDS container removal)
        """
        # --- 1. Remove flat fields from objects ---
        if section_field_names:
            self.objects_manager.update_many_pull(
                criteria={CmdbObjectKey.TYPE_ID: type_id},
                update={CmdbObjectKey.FIELDS: {CmdbObjectFieldKey.NAME: {"$in": section_field_names}}},
            )

        # --- 2. Remove MDS section completely (if applicable) ---
        if section_type == SectionType.MDS_SECTION:
            self.delete_mds_section_from_objects(type_id, section_name)
