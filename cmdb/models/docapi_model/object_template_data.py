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
Implementation of ObjectTemplateData
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import ObjectsManager, LocationsManager

from cmdb.models.object_model import CmdbObject
from cmdb.models.user_model import CmdbUser
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.type_constants import DG_LOCATION_FIELD_NAME
from cmdb.models.docapi_model.docapi_template_type_enum import DocapiTemplateType
from cmdb.models.docapi_model.reference_result import ReferenceResult
from cmdb.framework.rendering.cmdb_multi_render import CmdbMultiRender
from cmdb.framework.rendering.render_result import RenderResult

from cmdb.errors.manager.objects_manager import ObjectsManagerGetError
from cmdb.errors.manager.locations_manager import LocationsManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# Reserved `name` of the location field on every locatable type
# Initial recursion depth for resolving nested reference chains
DEFAULT_REFERENCE_DEPTH: int = 3

# -------------------------------------------------------------------------------------------------------------------- #
#                                              ObjectTemplateData - CLASS                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class ObjectTemplateData:
    """
    Prepares and retrieves template data for a given RenderResult
    """
    def __init__(
        self,
        cmdb_render_object: RenderResult,
        objects_manager: ObjectsManager,
        request_user: CmdbUser,
        template_type: DocapiTemplateType
    ) -> None:
        """
        Initializes the ObjectTemplateData

        Args:
            cmdb_render_object (RenderResult): The RenderResult to extract data from
            objects_manager (ObjectsManager): The manager handling CmdbObject
            request_user (CmdbUser): The user requesting the document
            template_type (DocapiTemplateType): The template type (DEFAULT enables the modern
                template data shape)
        """
        self.objects_manager: ObjectsManager = objects_manager
        self.request_user: CmdbUser = request_user
        self.template_type: DocapiTemplateType = template_type

        self.modern_templates: bool = self.template_type == DocapiTemplateType.DEFAULT

        self.locations_manager: LocationsManager = ManagerProvider.get_manager(
            ManagerType.LOCATIONS, request_user
        )

        self.template_data: dict[str, Any] = self.extract_object_data(cmdb_render_object, DEFAULT_REFERENCE_DEPTH)


    def get_template_data(self) -> dict[str, Any]:
        """
        Retrieves the processed template data

        Returns:
            dict[str, Any]: The structured template data extracted from the RenderResult
        """
        return self.template_data


    def _resolve_reference(self, public_id: int, depth: int) -> dict[str, Any] | None:
        """
        Resolves a referenced object into its extracted template data

        Args:
            public_id (int): The referenced object's public id
            depth (int): The remaining recursion depth for nested references

        Returns:
            dict[str, Any] | None: The referenced object's extracted data, or None if it cannot
                be retrieved
        """
        try:
            related_object: CmdbObject = self.objects_manager.get_object(public_id, as_dict=False)
        except ObjectsManagerGetError:
            LOGGER.error("Failed to resolve reference object with public_id '%s'", public_id)
            return None

        related_render: RenderResult = CmdbMultiRender(
            [related_object],
            self.request_user
        ).result(single_object=True)

        return self.extract_object_data(related_render, depth - 1)


    def _resolve_location(self, value: Any) -> str:
        """
        Resolves a location field value into the location's name

        Args:
            value (Any): The stored location public id (falsy when unset)

        Returns:
            str: The location name, or an empty string when unset or not resolvable
        """
        if not value:
            return ""

        try:
            location: dict[str, Any] | None = self.locations_manager.get_location(value)
        except LocationsManagerGetError:
            LOGGER.error("Failed to resolve location '%s'", value)
            return ""

        return location.get("name") if location else ""


    def _resolve_field(self, name: str, ftype: str, value: Any, references: dict | None, depth: int) -> Any:
        """
        Resolves a single field value, dispatching by field name / kind and template mode

        Args:
            name (str): The field name
            ftype (str): The field type (a `FieldType` value)
            value (Any): The stored field value
            references (dict | None): The field's resolved references (for reference sections)
            depth (int): The remaining recursion depth for nested references

        Returns:
            Any: The resolved field value
        """
        if name == DG_LOCATION_FIELD_NAME:
            return self._resolve_location(value)

        if self.modern_templates:
            return self._resolve_modern_field(ftype, value, references, depth)

        return self._resolve_legacy_field(ftype, value, references, depth)


    def _resolve_legacy_field(self, ftype: str, value: Any, references: dict | None, depth: int) -> Any:
        """
        Resolves a field for OBJECT (legacy) templates

        References resolve to the raw extracted dict; reference sections resolve to a plain
        ``{"fields": {name: value}}`` mapping.

        Args:
            ftype (str): The field type (a `FieldType` value)
            value (Any): The stored field value
            references (dict | None): The field's resolved references
            depth (int): The remaining recursion depth for nested references

        Returns:
            Any: The resolved field value
        """
        if ftype in (FieldType.REFERENCE, FieldType.LOCATION):
            if value and depth > 0:
                return self._resolve_reference(value, depth)
            return value

        if ftype == FieldType.REF_SECTION:
            return {
                "fields": {
                    ref.get("name"): ref.get("value", "")
                    for ref in (references or {}).get("fields", [])
                }
            }

        return value


    def _resolve_modern_field(self, ftype: str, value: Any, references: dict | None, depth: int) -> Any:
        """
        Resolves a field for DEFAULT (modern) templates

        Reference fields resolve to a `ReferenceResult` wrapper (locations to the raw dict);
        reference sections resolve their sub-fields recursively.

        Args:
            ftype (str): The field type (a `FieldType` value)
            value (Any): The stored field value
            references (dict | None): The field's resolved references
            depth (int): The remaining recursion depth for nested references

        Returns:
            Any: The resolved field value
        """
        if ftype in (FieldType.REFERENCE, FieldType.LOCATION) and value and depth > 0:
            resolved: dict[str, Any] | None = self._resolve_reference(value, depth)

            if resolved and ftype == FieldType.REFERENCE:
                return ReferenceResult(resolved)  # wrap only "ref" fields

            return resolved

        if ftype == FieldType.REF_SECTION:
            section_fields: dict[str, Any] = {}
            for ref in (references or {}).get("fields", []):
                section_fields[ref.get("name")] = self._resolve_field(
                    name=ref.get("name"),
                    ftype=ref.get("type"),
                    value=ref.get("value", ""),
                    references=ref.get("references"),
                    depth=depth,
                )
            return {"fields": section_fields}

        return value


    def _extract_mds(self, cmdb_render_object: RenderResult) -> dict[str, Any]:
        """
        Flattens the object's multi-data-sections into per-section, comma-joined field values

        Args:
            cmdb_render_object (RenderResult): The RenderResult whose multi-data-sections are flattened

        Returns:
            dict[str, Any]: A mapping of section id to ``{field_name: "v1, v2, ..."}``
        """
        mds_result: dict[str, Any] = {}

        for section in cmdb_render_object.multi_data_sections or []:
            section_id = section.get("section_id")
            if not section_id:
                continue

            aggregated: dict[str, list] = {}

            for entry in section.get("values", []):
                for field in entry.get("data", []):
                    name = field.get("name")
                    value = field.get("value", "")

                    if name is None:
                        continue

                    aggregated.setdefault(name, []).append(value)

            # convert lists to comma-separated strings
            mds_result[section_id] = {
                field_name: ", ".join(
                    "" if v is None else str(v) for v in values
                )
                for field_name, values in aggregated.items()
            }

        return mds_result


    def extract_object_data(self, cmdb_render_object: RenderResult, depth: int) -> dict[str, Any]:
        """
        Recursively extracts object data from a RenderResult

        Args:
            cmdb_render_object (RenderResult): The RenderResult to extract data from
            depth (int): The recursion depth limit for resolving references

        Returns:
            dict[str, Any]: The extracted object data
        """
        data: dict[str, Any] = {
            # `id` and `public_id` are both exposed for template convenience (same value)
            "id": cmdb_render_object.object_information.get("object_id"),
            "public_id": cmdb_render_object.object_information.get("object_id"),
            "type_id": cmdb_render_object.type_information.get("type_id"),
            "fields": {}
        }

        for field in cmdb_render_object.fields:
            field_name = field.get("name")
            if not field_name:
                continue

            try:
                data["fields"][field_name] = self._resolve_field(
                    name=field_name,
                    ftype=field.get("type"),
                    value=field.get("value", ""),
                    references=field.get("references"),
                    depth=depth,
                )
            except Exception as err:
                # Render-robustness boundary: one bad field must not abort the whole document
                LOGGER.error("Exception processing field '%s': %s", field_name, err)

        mds_result: dict[str, Any] = self._extract_mds(cmdb_render_object)

        if mds_result:
            data["mds"] = mds_result

        return data
