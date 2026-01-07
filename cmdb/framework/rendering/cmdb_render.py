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
Implementation of CmdbRender
"""
from logging import Logger, getLogger
from typing import Any
from dateutil.parser import parse

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import (
    ObjectsManager,
    UsersManager,
    TypesManager,
)

from cmdb.security.acl.permission import AccessControlPermission
from cmdb.framework.rendering.render_result import RenderResult
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

from cmdb.errors.manager.objects_manager import ObjectsManagerGetError
from cmdb.errors.manager.users_manager import UsersManagerGetError

from cmdb.errors.security import AccessDeniedError
from cmdb.errors.render import ObjectInstanceError, TypeInstanceError, InstanceRenderError
from cmdb.errors.models.cmdb_type import (
    CmdbTypeReferenceLineFillError,
    CmdbTypeFieldNotFoundError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  CmdbRender - CLASS                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class CmdbRender:
    """
    Responsible for rendering CMDB object and type data into a specified format
    """

    AUTHOR_ANONYMOUS_NAME = 'unknown'

    # pylint: disable=R0917
    def __init__(
        self,
        object_instance: CmdbObject,
        type_instance: CmdbType,
        render_user: CmdbUser,
        ref_render: bool = False
    ) -> None:
        """
        Initializes CmdbRender

        Args:
            object_instance (CmdbObject): The CMDB object to render
            type_instance (CmdbType): The CMDB type to render
            render_user (CmdbUser): The user who is requesting the render
            ref_render (bool, optional): Flag to enable reference rendering. Defaults to False
            dbm (MongoDatabaseManager, optional): Database manager. Defaults to None
        """
        self.object_instance: CmdbObject = object_instance
        self.type_instance: CmdbType = type_instance
        self.render_user: CmdbUser = render_user

        self.objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, self.render_user)
        self.types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, self.render_user)
        self.users_manager: UsersManager = ManagerProvider.get_manager(ManagerType.USERS, self.render_user)

        self.ref_render: bool = ref_render


    @property
    def object_instance(self) -> CmdbObject:
        """
        CmdbObject instance representing the object to render
        """
        return self._object_instance


    @object_instance.setter
    def object_instance(self, object_instance: CmdbObject) -> None:
        """
        Set the object_instance property after validation

        Args:
            object_instance (CmdbObject): The object to assign to the property

        Raises:
            ObjectInstanceError: If the passed object is not a CmdbObject
        """
        if not isinstance(object_instance, CmdbObject):
            raise ObjectInstanceError("The passed object is not an CmdbObject!")

        self._object_instance = object_instance


    @property
    def type_instance(self) -> CmdbType:
        """
        CmdbType instance representing the CmdbType of the CmdbObject
        """
        return self._type_instance


    @type_instance.setter
    def type_instance(self, type_instance: CmdbType) -> None:
        """
        Set the type_instance property after validation

        Args:
            type_instance (CmdbType): The type to assign to the property

        Raises:
            TypeInstanceError: If the passed type is not a CmdbType
        """
        if not isinstance(type_instance, CmdbType):
            raise TypeInstanceError("The passed type is not a CmdbType!")

        self._type_instance: CmdbType = type_instance


    def result(self, level: int = 3) -> RenderResult:
        """
        Generate the rendered result for the object

        Args:
            level (int, optional): The depth of the rendering. Defaults to 3

        Returns:
            RenderResult: The rendered result
        """
        return self._generate_result(level)


    def get_mds_reference(self, field_value: int) -> dict:
        """
        Generate a reference for the MDS

        Args:
            field_value (int): The field value to generate the reference for

        Returns:
            dict: The generated reference as a dictionary
        """
        return self.__merge_references({"value": field_value})


    def is_ref_field(self, field_name: str) -> bool:
        """
        Check if the given field is a reference field

        Args:
            field_name (str): The field name to check

        Returns:
            bool: True if the field is a reference, False otherwise
        """
        for field in self.type_instance.fields:
            if field["type"] == "ref" and field["name"] == field_name:
                return True

        return False


    def _generate_result(self, level: int) -> RenderResult:
        """
        Generate a full render result based on the object's data

        Args:
            level (int): The depth of the rendering

        Returns:
            RenderResult: The rendered result
        """
        try:
            render_result: RenderResult = RenderResult()

            render_result = self.__generate_object_information(render_result)
            render_result = self.__generate_type_information(render_result)
            render_result = self.__set_fields(render_result, level)
            render_result = self.__set_sections(render_result)
            render_result = self.__set_summaries(render_result)
            render_result = self.__set_external(render_result)
            render_result = self.__set_multi_data_sections(render_result)

            return render_result
        except Exception as err:
            raise InstanceRenderError(f'Error while generating a RenderResult: {err}') from err


    def __set_multi_data_sections(self, render_result: RenderResult) -> RenderResult:
        """
        Set multi-data sections for the render result

        Args:
            render_result (RenderResult): The current render result to update

        Returns:
            RenderResult: The updated render result with multi-data sections
        """
        render_result.multi_data_sections = self.object_instance.multi_data_sections

        return render_result


    def __generate_object_information(self, render_result: RenderResult) -> RenderResult:
        """
        Generate object-specific information for rendering

        Args:
            render_result (RenderResult): The current render result to update

        Returns:
            RenderResult: The updated render result with object-specific information
        """
        try:
            author_name: str | None = None
            author: CmdbUser | None = self.users_manager.get_user(self.object_instance.author_id)

            if author:
                author_name = author.get_display_name()
            else:
                author_name = CmdbRender.AUTHOR_ANONYMOUS_NAME
        except Exception:
            author_name = CmdbRender.AUTHOR_ANONYMOUS_NAME

        editor_name: str | None = None
        if self.object_instance.editor_id:
            try:
                editor = self.users_manager.get_user(self.object_instance.editor_id)

                if editor:
                    editor_name = editor.get_display_name()
            except UsersManagerGetError:
                editor_name = None

        render_result.object_information = {
            'object_id': self.object_instance.public_id,
            'creation_time': self.object_instance.creation_time,
            'last_edit_time': self.object_instance.last_edit_time,
            'author_id': self.object_instance.author_id,
            'author_name': author_name,
            'editor_id': self.object_instance.editor_id,
            'editor_name': editor_name,
            'active': self.object_instance.active,
            'version': self.object_instance.version
        }

        return render_result


    def __generate_type_information(self, render_result: RenderResult) -> RenderResult:
        """
        Generate type-specific information for rendering

        Args:
            render_result (RenderResult): The current render result to update

        Returns:
            RenderResult: The updated render result with type-specific information
        """
        try:
            author_name: str | None = None
            author: CmdbUser | None = self.users_manager.get_user(self.object_instance.author_id)

            if author:
                author_name = author = author.get_display_name()
            else:
                author_name = CmdbRender.AUTHOR_ANONYMOUS_NAME
        except UsersManagerGetError:
            author_name = CmdbRender.AUTHOR_ANONYMOUS_NAME

        try:
            self.type_instance.render_meta.icon
        except KeyError:
            self.type_instance.render_meta.icon = ''

        render_result.type_information = {
            'type_id': self.type_instance.public_id,
            'type_name': self.type_instance.name,
            'type_label': self.type_instance.label,
            'creation_time': self.type_instance.creation_time,
            'author_id': self.type_instance.author_id,
            'author_name': author_name,
            'icon': self.type_instance.render_meta.icon,
            'active': self.type_instance.active,
            'version': self.type_instance.version,
            'acl': self.type_instance.acl.to_json(self.type_instance.acl)
        }

        return render_result


    def __set_fields(self, render_result: RenderResult, level: int) -> RenderResult:
        """
        Set the fields for the render result based on the level

        Args:
            render_result (RenderResult): The current render result to update
            level (int): The level of field detail

        Returns:
            RenderResult: The updated render result with fields
        """
        render_result.fields = self.__merge_fields_value(level-1)

        return render_result


    def __set_sections(self, render_result: RenderResult) -> RenderResult:
        """
        Set sections for the render result

        Args:
            render_result (RenderResult): The current render result to update

        Returns:
            RenderResult: The updated render result with sections
        """
        try:
            render_result.sections = [section.to_json(section) for section in self.type_instance.render_meta.sections]
        except Exception as err:
            LOGGER.error("[__set_sections] Exception: %s. Type: %s.", err, type(err), exc_info=True)
            render_result.sections = []

        return render_result


    def __merge_field_content_section(self, field: dict, object_: CmdbObject) -> dict:
        """
        Merge field content with the given CMDB object data

        Args:
            field (dict): The field to merge
            object_ (CmdbObject): The object containing the data

        Returns:
            dict: The merged field content
        """
        curr_field = [x for x in object_.fields if x['name'] == field['name']][0]

        if curr_field['name'] == field['name'] and field.get('value'):
            field['default'] = field['value']

        field['value'] = curr_field['value']

        # handle dates that are stored as strings
        if field['type'] == 'date' and isinstance(field['value'], str) and field['value']:
            field['value'] = parse(field['value'], fuzzy=True)

        if self.ref_render and (field['type'] == 'ref' or field['type'] == 'location') and field['value']:
            field['reference'] = self.__merge_references(field)

        return field


    def __merge_fields_value(self, level: int = 3) -> list[dict]:
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

        for idx, section in enumerate(self.type_instance.render_meta.sections):
            if isinstance(section, (TypeFieldSection, TypeMultiDataSection)):
                for section_field in section.fields:
                    field = {}
                    try:
                        field = self.type_instance.get_field(section_field)
                        field = self.__merge_field_content_section(field, self.object_instance)
                        if (field['type'] in ('ref','location')) and (not self.ref_render or 'summaries' not in field):
                            ref_field_name: str = field['name']
                            field = self.type_instance.get_field(ref_field_name)
                            reference_id: int = self.object_instance.get_value(ref_field_name)
                            field['value'] = reference_id

                            if field['type'] == 'ref':
                                reference_object = self.objects_manager.get_object(reference_id)
                                reference_object = CmdbObject.from_data(reference_object)

                                ref_type: CmdbType = self.objects_manager.get_object_type(
                                                                                reference_object.get_type_id()
                                                                           )
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
                    ref_field = self.type_instance.get_field(ref_field_name)
                except CmdbTypeFieldNotFoundError as err:
                    LOGGER.debug("[__merge_fields_value] CmdbTypeFieldNotFoundError: %s", err)
                    continue

                try:
                    reference_id: int = self.object_instance.get_value(ref_field_name)
                    ref_field['value'] = reference_id
                    reference_object: dict = self.objects_manager.get_object(reference_id)
                    reference_object = CmdbObject.from_data(reference_object)
                except Exception:
                    reference_object = None

                try:
                    ref_type = self.types_manager.get_type(section.reference.type_id)
                    if not ref_type:
                        continue

                    ref_type = CmdbType.from_data(ref_type)
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
                    self.type_instance.render_meta.sections[idx] = section
                else:
                    selected_ref_fields = [f for f in ref_section.fields if f in section.reference.selected_fields]

                for ref_section_field_name in selected_ref_fields:
                    try:
                        ref_section_field = ref_type.get_field(ref_section_field_name)
                        if reference_object:
                            ref_section_field = self.__merge_field_content_section(ref_section_field, reference_object)
                            if level > 0:
                                ref_section_fields = self.__merge_reference_section_fields(ref_section_field,
                                                                                           ref_type,
                                                                                           [], level)
                                ref_section_field.get('references', {'fields': []})['fields'] = ref_section_fields
                    except (FileNotFoundError, CmdbTypeFieldNotFoundError,
                            ValueError, IndexError, ObjectsManagerGetError):
                        continue
                    ref_field['references']['fields'].append(ref_section_field)
                field_map.append(ref_field)

        return field_map


    def __merge_reference_section_fields(
            self,
            ref_section_field: dict,
            ref_type: CmdbType,
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
                reference_type: CmdbType = self.objects_manager.get_object_type(instance.get_type_id())
                render = CmdbRender(instance, ref_type, self.render_user, True)
                fields = render.result(level).fields
                res = next((x for x in fields if x['name'] == ref_section_field.get('name', '')), None)

                if res and ref_section_field.get('type', '') == 'ref-section-field':
                    self.__merge_reference_section_fields(res, reference_type, ref_section_fields, level)

                    for field in res['references']['fields']:
                        merged_field_content = self.__merge_field_content_section(field, instance)
                        if merged_field_content and merged_field_content.get('type', '') == 'ref-section-field':
                            self.__merge_reference_section_fields(merged_field_content, reference_type,
                                                                  ref_section_fields, level)
                        else:
                            ref_section_fields.append(merged_field_content)
            except (Exception, TypeError, ObjectsManagerGetError) as err:
                LOGGER.info(err)

        return ref_section_fields


    def __merge_references(self, current_field: dict) -> dict:
        """
        Merges reference data for a given field if it exists

        Args:
            field (dict): The field to check and merge references for

        Returns:
            dict: The reference data if present
        """
        reference = TypeReference(type_id=0, object_id=0, type_label='', line='')

        if current_field['value']:

            try:
                ref_object = self.objects_manager.get_object(int(current_field['value']),
                                                             self.render_user,
                                                             AccessControlPermission.READ)
                ref_object = CmdbObject.from_data(ref_object)
            except AccessDeniedError as err:
                return err
            except ObjectsManagerGetError:
                return TypeReference.to_json(reference)

            try:
                ref_type = self.objects_manager.get_object_type(ref_object.get_type_id())

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
                except (CmdbTypeReferenceLineFillError, Exception, CmdbTypeFieldNotFoundError):
                    pass

            except ObjectsManagerGetError as err:
                LOGGER.error(err)
            finally:
                return TypeReference.to_json(reference)


    def __set_summaries(self, render_result: RenderResult) -> RenderResult:
        """
        Sets the summaries and summary line for the render result

        Args:
            render_result (RenderResult): The current render result object to update

        Returns:
            RenderResult: Updated render result with summaries and summary line filled
        """
        summary_list = []
        summary_line = ''
        default_line = f'{self.type_instance.label} #{self.object_instance.public_id}'

        if not self.type_instance.has_summaries():
            render_result.summaries = summary_list
            render_result.summary_line = default_line

            return render_result

        try:
            summary_list = self.type_instance.get_summary().fields
            render_result.summaries = summary_list
            first = True

            for line in summary_list:
                if first:
                    summary_line += f'{line["value"]}'
                    first = False
                else:
                    summary_line += f' | {line["value"]}'

            render_result.summary_line = summary_line
        except Exception:
            summary_line = default_line
        finally:
            render_result.summary_line = summary_line

        return render_result


    def __set_external(self, render_result: RenderResult) -> RenderResult:
        """
        Sets the external links for the render result.

        External links are populated based on the type's external link definitions.
        If required fields are missing, the link will be skipped.

        Args:
            render_result (RenderResult): The current render result object to update

        Returns:
            RenderResult: Updated render result with populated external links
        """
        # checks if type has externals defined
        if not self.type_instance.has_externals():
            render_result.externals = []
            return render_result

        # global external list
        external_list: list[dict[str, Any]] = []

        # loop over all externals
        for ext_link in self.type_instance.get_externals():
            # append all values for required field in this list
            field_list: list[Any] = []
            # if data are missing or empty append here
            missing_list: list[Any] = []

            try:
                # get TypeExternalLink definitions from type
                ext_link_instance: TypeExternalLink | None = self.type_instance.get_external(ext_link.name)

                if not ext_link_instance:
                    LOGGER.debug("[__set_external] ExternalLink for %s not found!", ext_link.name)
                    continue

                # check if link requires data - regex check for {}
                if ext_link_instance.link_requires_fields():

                    # check if has fields
                    if not ext_link_instance.has_fields():
                        raise ValueError(f"No fields assigned to the ExternalLink named: {ext_link.name}!")

                    # for every field get the value data from object_instance
                    for ext_link_field in ext_link_instance.fields:
                        try:
                            field_value: int | str | None = None

                            if ext_link_field == 'object_id':
                                field_value = self.object_instance.public_id
                            else:
                                field_value = self.object_instance.get_value(ext_link_field)

                            if field_value is None or field_value == '':
                                # if value is empty or does not exists
                                raise ValueError(f"Field '{ext_link_field}' for ExternalLink is empty!")

                            field_list.append(field_value)
                        except Exception:
                            # LOGGER.debug("[__set_external] ExternalLink set Field Exception: %s!", err)
                            # if error append missing data
                            missing_list.append(ext_link_instance)

                if len(missing_list) > 0:
                    raise RuntimeError(f"ExternalLink issues with {len(missing_list)} fields!")

                try:
                    # fill the href with field value data
                    ext_link_instance.fill_href(field_list)
                except ValueError:
                    # LOGGER.debug("[__set_external] ExternalLink ValueError: %s", err)
                    continue

            except Exception:
                # LOGGER.debug("[__set_external] ExternalLink Exception: %s", err)
                continue

            external_list.append(TypeExternalLink.to_json(ext_link_instance))

        render_result.externals = external_list
        return render_result
