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
Implementation of CmdbMultiRender
"""
from logging import Logger, getLogger
from typing import Any
from copy import deepcopy
from dateutil.parser import parse

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import (
    ObjectsManager,
    UsersManager,
    TypesManager,
)

from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import (
    CmdbType,
    TypeReference,
    TypeExternalLink,
    TypeFieldSection,
    TypeReferenceSection,
    TypeMultiDataSection,
)
from cmdb.models.user_model import CmdbUser
from cmdb.framework.rendering.render_constants import ANONYMOUS_NAME
from cmdb.framework.rendering.render_result import RenderResult

from cmdb.errors.manager.objects_manager import ObjectsManagerGetError
from cmdb.errors.models.cmdb_type import CmdbTypeFieldNotFoundError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                CmdbMultiRender - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class CmdbMultiRender:
    """
    Responsible for rendering multiple CmdbObjects and type data into a specified format
    """
    def __init__(
        self,
        to_render_objects: list[CmdbObject],
        render_user: CmdbUser,
        ref_render: bool = False
    ) -> None:
        """
        Initializes CmdbMultiRender

        Args:
            to_render_objects (list[CmdbObject]): All CmdbObjects which should be rendered
            render_user (CmdbUser): The user who is requesting the render
            ref_render (bool, optional): Flag to enable reference rendering. Defaults to False
        """
        self.to_render_objects: list[CmdbObject] = to_render_objects
        self.render_user: CmdbUser = render_user

        self.objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, self.render_user)
        self.types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, self.render_user)
        self.users_manager: UsersManager = ManagerProvider.get_manager(ManagerType.USERS, self.render_user)

        self.ref_render: bool = ref_render

        # Caching and result
        self.objects_cache: dict[int, CmdbObject] = self.get_all_linked_objects()
        self.types_cache: dict[int, CmdbType] = self.get_all_linked_types()
        self.users_cache: dict[int, CmdbUser] = self.get_all_linked_users()


    def result(self, level: int = 3, single_object: bool = False) -> list[RenderResult] | RenderResult:
        """TODO: document"""
        render_results: list[RenderResult] = []

        for obj in self.to_render_objects:
            obj_type: CmdbType | None = self.types_cache.get(obj.get_type_id())

            if not obj_type:
                LOGGER.error("[render] Type for Object with type_id:%s not found!", obj.get_type_id())
                continue

            result = RenderResult()
            result.object_information = deepcopy(self.__generate_object_information(obj))
            result.type_information = deepcopy(self.__generate_type_information(obj_type))
            result.fields = deepcopy(self.__set_fields(obj, obj_type, level))
            result.sections = deepcopy(self.__get_type_sections(obj_type))
            result: RenderResult = self.__set_summaries(result, obj, obj_type)
            result.externals = deepcopy(self.__set_externals(obj, obj_type))
            result.multi_data_sections = deepcopy(obj.multi_data_sections)

            render_results.append(result)

        if single_object:
            return render_results[0]

        return render_results


    def __generate_object_information(self, obj: CmdbObject) -> dict[str, Any]:
        """
        Generate object-specific information for rendering using cached users.

        Args:
            obj (CmdbObject): The object to generate info for.

        Returns:
            dict[str, Any]: Object information dictionary
        """
        object_info: dict[str, Any] = {
            "object_id": obj.public_id,
            "creation_time": obj.creation_time,
            "last_edit_time": obj.last_edit_time,
            "author_id": obj.author_id,
            "author_name": self.get_user_name(obj.author_id),
            "editor_id": obj.editor_id,
            "editor_name": self.get_user_name(obj.editor_id, True),
            "active": obj.active,
            "version": obj.version,
            "special_type": obj.special_type,
        }

        return object_info


    def __generate_type_information(self, type_instance: CmdbType) -> dict[str, Any]:
        """
        Generate type-specific information for rendering using cached types and users.

        Args:
            type_instance (CmdbType): The CmdbType of the rendered object

        Returns:
            dict[str, Any]: Type information dictionary
        """
        # --- Ensure icon exists ---
        try:
            icon = type_instance.render_meta.icon
        except (AttributeError, KeyError):
            icon = ""

        # --- Build type information dictionary ---
        type_info: dict[str, Any] = {
            "type_id": type_instance.public_id,
            "type_name": type_instance.name,
            "type_label": type_instance.label,
            "creation_time": type_instance.creation_time,
            "author_id": type_instance.author_id,
            "author_name": self.get_user_name(type_instance.author_id),
            "icon": icon,
            "active": type_instance.active,
            "version": type_instance.version,
            "acl": type_instance.acl.to_json(type_instance.acl)
        }

        return type_info


    def __get_type_sections(self, type_instance: CmdbType) -> list[dict[str, Any]]:
        """
        Set sections for the render result

        Args:
            render_result (RenderResult): The current render result to update

        Returns:
            list[dict[str, Any]]: The sections of an object
        """
        try:
            sections: list[dict[str, Any]] = [
                section.to_json(section) for section in type_instance.render_meta.sections
            ]
        except Exception as err:
            LOGGER.error("[__get_type_sections] Exception: %s. Type: %s.", err, type(err), exc_info=True)
            sections = []

        return sections


    def __set_fields(
        self,
        object_instance: CmdbObject,
        type_instance: CmdbType,
        level: int
    ) -> list[dict[str, Any]]:
        """
        Set the fields for the render result based on the level

        Args:
            render_result (RenderResult): The current render result to update
            level (int): The level of field detail

        Returns:
            RenderResult: The updated render result with fields
        """
        return self.__merge_fields_value(object_instance, type_instance, level-1)


    def __set_externals(
        self,
        object_instance: CmdbObject,
        type_instance: CmdbType
    ) -> list[dict[str, Any]]:
        """TODO: document"""
        if not type_instance.has_externals():
            return []

        externals: list[dict[str, Any]] = []

        for ext_link in type_instance.get_externals():
            ext = type_instance.get_external(ext_link.name)
            if not ext:
                LOGGER.debug("[__set_externals] ExternalLink for %s not found!", ext_link.name)
                continue

            try:
                field_values = self._collect_field_values(ext, object_instance)
                if field_values is None:
                    continue

                ext.fill_href(field_values)
                externals.append(TypeExternalLink.to_json(ext))

            except Exception as err:
                LOGGER.debug(
                    "[__set_externals] Exception: %s . Type: %s",
                    err,
                    type(err).__name__
                )

        return externals


    def __set_summaries(
        self,
        render_result: RenderResult,
        object_instance: CmdbObject,
        type_instance: CmdbType
    ) -> RenderResult:
        """
        Sets the summaries and summary line for the render result

        Args:
            render_result (RenderResult): The current render result object to update

        Returns:
            RenderResult: Updated render result with summaries and summary line filled
        """
        default_line = f'{type_instance.label} #{object_instance.public_id}'

        if not type_instance.has_summaries():
            render_result.summaries = []
            render_result.summary_line = default_line
            return render_result

        try:
            summary_list = [
                dict(item) for item in type_instance.get_summary().fields
            ]

            render_result.summaries = summary_list

            render_result.summary_line = " | ".join(
                str(line.get("value", "")) for line in summary_list
            ) or default_line

        except Exception:
            render_result.summaries = []
            render_result.summary_line = default_line

        return render_result

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    def get_user_name(self, user_id: int = None, for_editor: bool = False) -> str:
        """TODO: document"""
        if not user_id:
            return None if for_editor else ANONYMOUS_NAME

        user: CmdbUser | None = self.users_cache.get(user_id)

        return user.get_display_name() if user else ANONYMOUS_NAME


    def get_all_linked_users(self) -> dict[int, CmdbUser]:
        """TODO: document"""
        user_ids: set[int] = set()

        # Collect authors and editors from provided objects
        for obj in self.to_render_objects:
            if obj.author_id:
                user_ids.add(obj.author_id)
            if obj.editor_id:
                user_ids.add(obj.editor_id)

        # Collect all authors from the types
        for type_instance in self.types_cache.values():
            if type_instance.author_id:
                user_ids.add(type_instance.author_id)

        if not user_ids:
            return {}

        linked_users: dict[int, CmdbUser] = self.users_manager.get_user_lookup(list(user_ids))

        return linked_users


    def get_all_linked_types(self) -> dict[int, CmdbType]:
        """TODO: document"""
        type_ids: set[int] = set()

        for obj in self.to_render_objects:
            type_ids.add(obj.get_type_id())

        # types from referenced objects
        if hasattr(self, "objects_cache"):
            for obj in self.objects_cache.values():
                type_ids.add(obj.get_type_id())

        if not type_ids:
            return {}

        linked_types: dict[int, CmdbType] = self.types_manager.get_types_lookup(list(type_ids))

        return linked_types


    def get_all_linked_objects(self) -> dict[int, CmdbObject]:
        """
        Collect all referenced objects (ref + ref-section-field) and return as lookup.

        Returns:
            dict[int, CmdbObject]: Lookup of object_id -> CmdbObject
        """
        if not self.ref_render:
            return {}

        reference_ids: set[int] = set()

        # Collect referenced object IDs
        for obj in self.to_render_objects:
            for field in obj.fields:
                field_type = field.get("type")

                if not field_type:
                    LOGGER.debug(
                        "Field-Type in Object: %s not found for field name: %s !",
                        obj.public_id,
                        field.get('name')
                    )
                    type_instance: CmdbType = self.types_manager.get_type(obj.get_public_id(), False)

                    if not type_instance:
                        LOGGER.debug("Type of Object: %s not found!", obj.public_id)
                        continue

                    target_field = type_instance.get_field(field['name'])

                    field_type = target_field['type']


                if field_type in ("ref", "ref-section-field") and field.get("value"):
                    reference_ids.add(int(field["value"]))

        if not reference_ids:
            return {}

        # Fetch objects in bulk
        try:
            objects_data: dict[int, CmdbObject] = self.objects_manager.get_objects_lookup(list(reference_ids))

            return objects_data
        except Exception as err:
            LOGGER.error("Error fetching referenced objects: %s", err, exc_info=True)
            return {}


    def _collect_field_values(
        self,
        ext: TypeExternalLink,
        obj: CmdbObject
    ) -> list[Any] | None:
        """Extract and validate field values required for an external link."""

        if not ext.link_requires_fields():
            return []

        if not ext.has_fields():
            raise ValueError(f"No fields assigned to ExternalLink: {ext.name}")

        values: list[Any] = []

        for field_name in ext.fields:
            value = obj.public_id if field_name == "object_id" else obj.get_value(field_name)

            if value in (None, ''):
                LOGGER.debug(
                    "[__set_externals] Missing value for field '%s' in ExternalLink '%s'",
                    field_name,
                    ext.name
                )
                return None

            values.append(value)

        return values


    def __merge_reference_section_fields(
            self,
            ref_section_field: dict,
            ref_section_fields: list,
            level: int
    ) -> list:
        """
        Recursively merges fields from a referenced section into the current section fields list.

        This method handles fields of type 'ref-section-field' by retrieving the referenced object,
        rendering its fields, and recursively merging their contents.

        Args:
            ref_section_field (dict): The reference section field to process
            ref_type (CmdbType): The type information of the current referenced object
            ref_section_fields (list): A list to accumulate merged fields
            level (int): The depth level for rendering referenced objects

        Returns:
            list: The updated list of merged reference section fields
        """
        if ref_section_field and ref_section_field.get('type', '') == 'ref-section-field':
            try:
                instance = self.objects_manager.get_object(ref_section_field.get('value'))
                instance = CmdbObject.from_data(instance)

                render = CmdbMultiRender(list(instance), self.render_user, True)
                fields = render.result(level)[0].fields
                res = next((x for x in fields if x['name'] == ref_section_field.get('name', '')), None)

                if res and ref_section_field.get('type', '') == 'ref-section-field':
                    self.__merge_reference_section_fields(res, ref_section_fields, level)

                    for field in res['references']['fields']:
                        merged_field_content = self.__merge_field_content_section(field, instance)
                        if merged_field_content and merged_field_content.get('type', '') == 'ref-section-field':
                            self.__merge_reference_section_fields(merged_field_content, ref_section_fields, level)
                        else:
                            ref_section_fields.append(merged_field_content)
            except (Exception, TypeError, ObjectsManagerGetError) as err:
                LOGGER.info(err)

        return ref_section_fields


    def __merge_references(self, current_field: dict[str, Any]) -> dict[str, Any]:
        """
        Merges reference data for a given field if it exists

        Args:
            field (dict[str, Any]): The field to check and merge references for

        Returns:
            dict[str, Any]: The reference data if present
        """
        reference = TypeReference(type_id=0, object_id=0, type_label='', line='')

        if current_field['value']:
            ref_object: CmdbObject | None = self.objects_cache.get(int(current_field['value']))

            if not ref_object:
                return TypeReference.to_json(reference)

            try:
                ref_type: CmdbType | None = self.types_cache.get(ref_object.get_type_id())

                if not ref_type:
                    return TypeReference.to_json(reference)

                _summary_fields = []
                _nested_summaries = current_field.get('summaries', [])
                _nested_summary_line = ref_type.get_nested_summary_line(_nested_summaries)
                _nested_summary_fields = _nested_summaries

                try:
                    _nested_summary_fields = ref_type.get_nested_summary_fields(_nested_summaries)
                except CmdbTypeFieldNotFoundError as error:
                    LOGGER.warning('Summary setting refers to non-existent field(s), Error %s',error)

                reference.type_id = ref_type.get_public_id()
                reference.object_id = int(current_field['value'])
                reference.type_label = ref_type.label
                reference.icon = ref_type.get_icon()
                reference.prefix = ref_type.has_nested_prefix(_nested_summaries)

                _summary_fields = _nested_summary_fields \
                    if (_nested_summary_line or _nested_summary_fields) else ref_type.get_summary().fields

                summaries = []
                summary_values = []

                for field in _summary_fields:
                    summary_value = str([x for x in ref_object.fields if x['name'] == field['name']][0]['value'])
                    summaries.append({"value": summary_value, "type": field.get('type')})
                    summary_values.append(summary_value)

                reference.summaries = summaries

                try:
                    # fill the summary line with summaries value data
                    reference.line = _nested_summary_line

                    if not reference.line_requires_fields():
                        reference.summaries = []

                    if _nested_summary_line:
                        reference.fill_line(summary_values)
                except Exception:
                    pass

                return TypeReference.to_json(reference)
            except Exception:
                return TypeReference.to_json(reference)


    def __merge_field_content_section(self, t_field: dict[str, Any], object_instance: CmdbObject) -> dict:
        """
        Merge field content with the given CmdbObject data

        Args:
            t_field (dict[str, Any]): The field to merge
            object_instance (CmdbObject): The object containing the data

        Returns:
            dict[str, Any]: The merged field content
        """
        obj_field: dict[str, Any] = [x for x in object_instance.fields if x['name'] == t_field['name']][0]

        if obj_field['name'] == t_field['name'] and t_field.get('value'):
            t_field['default'] = t_field['value']

        t_field['value'] = obj_field['value']

        # handle dates that are stored as strings
        if t_field['type'] == 'date' and isinstance(t_field['value'], str) and t_field['value']:
            t_field['value'] = parse(t_field['value'], fuzzy=True)

        if self.ref_render and (t_field['type'] == 'ref' or t_field['type'] == 'location') and t_field['value']:
            t_field['reference'] = self.__merge_references(t_field)

        return t_field


    def __merge_fields_value(
        self,
        object_instance: CmdbObject,
        type_instance: CmdbType,
        level: int = 3
    ) -> list[dict[str, Any]]:
        """
        Merge all field values with references extended

        Args:
            level (int): The level of rendering detail

        Returns:
            list[dict]: A list of merged fields with reference data
        """
        field_map = []
        if level == 0:
            return field_map

        for idx, section in enumerate(type_instance.render_meta.sections):
            if isinstance(section, (TypeFieldSection, TypeMultiDataSection)):
                for sf_name in section.fields:
                    field = {}
                    try:
                        field: dict[str, Any] = type_instance.get_field(sf_name)
                        field = self.__merge_field_content_section(field, object_instance)

                        if (field['type'] in ('ref','location')) and (not self.ref_render or 'summaries' not in field):
                            ref_field_name: str = field['name']
                            field: dict[str, Any] = type_instance.get_field(ref_field_name)
                            reference_id: int = object_instance.get_value(ref_field_name)
                            field['value'] = reference_id

                            if field['type'] == 'ref':
                                reference_object: CmdbObject = self.objects_cache.get(reference_id)
                                ref_type: CmdbType = self.types_cache.get(reference_object.type_id)

                                field['reference'] = {
                                    'type_id': ref_type.public_id,
                                    'type_name': ref_type.name,
                                    'type_label': ref_type.label,
                                    'object_id': reference_id,
                                    'summaries': []
                                }

                                for ref_section_field_name in ref_type.get_fields():
                                    try:
                                        ref_section_field = ref_type.get_field(ref_section_field_name['name'])
                                        ref_field = self.__merge_field_content_section(
                                            ref_section_field,
                                            reference_object
                                        )
                                    except Exception:
                                        continue
                                    field['reference']['summaries'].append(ref_field)

                            if field['type'] == 'location':
                                field['reference'] = {
                                    'type_id': '',
                                    'type_name': '',
                                    'type_label': '',
                                    'object_id': reference_id,
                                    'summaries': []
                                }

                    except Exception:
                        field['value'] = None

                    field_map.append(field)

            elif isinstance(section, TypeReferenceSection):
                try:
                    ref_field_name: str = f'{section.name}-field'
                    ref_field: dict[str, Any] = type_instance.get_field(ref_field_name)
                except CmdbTypeFieldNotFoundError as err:
                    LOGGER.debug("[__merge_fields_value] CmdbTypeFieldNotFoundError: %s", err)
                    continue

                try:
                    reference_id: int = object_instance.get_value(ref_field_name)
                    ref_field['value'] = reference_id
                    reference_object: CmdbObject = self.objects_cache.get(reference_id)
                except Exception:
                    reference_object = None

                try:
                    ref_type: CmdbType = self.types_cache.get(section.reference.type_id)
                    if not ref_type:
                        continue

                    ref_section = ref_type.get_section(section.reference.section_name)
                    ref_field['references'] = {
                        'type_id': ref_type.public_id,
                        'type_name': ref_type.name,
                        'type_label': ref_type.label,
                        'type_icon': ref_type.get_icon(),
                        'fields': []
                    }
                except Exception:
                    continue

                if not ref_section:
                    continue

                if not section.reference.selected_fields or len(section.reference.selected_fields) == 0:
                    selected_ref_fields = ref_section.fields
                    section.reference.selected_fields = selected_ref_fields
                    type_instance.render_meta.sections[idx] = section
                else:
                    selected_ref_fields = [f for f in ref_section.fields if f in section.reference.selected_fields]

                for ref_section_field_name in selected_ref_fields:
                    try:
                        ref_section_field = ref_type.get_field(ref_section_field_name)
                        if reference_object:
                            ref_section_field = self.__merge_field_content_section(ref_section_field, reference_object)
                            if level > 0:
                                ref_section_fields = self.__merge_reference_section_fields(
                                                                ref_section_field,
                                                                [],
                                                                level
                                                           )
                                ref_section_field.get('references', {'fields': []})['fields'] = ref_section_fields
                    except Exception:
                        continue
                    ref_field['references']['fields'].append(ref_section_field)

                field_map.append(ref_field)

        return field_map


    def get_mds_reference(self, field_value: int) -> dict:
        """
        Generate a reference for the MDS

        Args:
            field_value (int): The field value to generate the reference for

        Returns:
            dict: The generated reference as a dictionary
        """
        return self.__merge_references({"value": field_value})
