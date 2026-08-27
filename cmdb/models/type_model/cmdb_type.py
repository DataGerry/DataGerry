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
Implementation of CmdbType

The CmdbType is the schema every CmdbObject is written against: `fields` holds the field definitions,
`render_meta` holds how they are grouped (sections), summarised and linked out. Three invariants hold
across the whole codebase and are what most of this class exists to serve:

* **A field's `name` is its unique, immutable identifier.** `CmdbObject.fields` rows reference type
  fields by name, so renaming one would orphan every stored value - the frontend does not allow it and
  the backend assumes name-stability across updates
* **Kind is decided by the `type` key**, on a field entry (`FieldType`) and on a render_meta section
  (`SectionType`). Always compare against those enums, never against a bare string
* **Removing a field is silently destructive** - the value disappears from every existing CmdbObject,
  and nothing cleans the removed name out of `render_meta.summary.fields`. The summary accessors here
  therefore have to tolerate a name that no longer resolves

Document keys are named by `TypeSchemaKey` and field-entry keys by `FieldKey`, so the two halves of
the `from_data` / `to_json` round-trip are defined once rather than spelled out twice
"""
from logging import Logger, getLogger
from typing import Any
from datetime import datetime, timezone
from dateutil.parser import parse

from cmdb.security.acl.access_control_list import AccessControlList
from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.type_model.type_summary import TypeSummary
from cmdb.models.type_model.type_external_link import TypeExternalLink
from cmdb.models.type_model.type_section import TypeSection
from cmdb.models.type_model.type_render_meta import TypeRenderMeta
from cmdb.models.type_model.section_type_enum import SectionType
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.models.type_model.type_constants import NestedSummaryKey
from cmdb.class_schema.type_model.cmdb_type_schema import get_cmdb_type_schema

from cmdb.errors.models.cmdb_type import (
    CmdbTypeInitError,
    CmdbTypeInitFromDataError,
    CmdbTypeToJsonError,
    CmdbTypeFieldNotFoundError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   CmdbType - CLASS                                                   #
# -------------------------------------------------------------------------------------------------------------------- #


# pylint: disable=too-many-instance-attributes
class CmdbType(CmdbDAO):
    """
    Represents a CmdbType in DataGerry

    Extends: CmdbDAO
    """
    COLLECTION = "framework.types"
    DEFAULT_VERSION = '1.0.0'
    SCHEMA: dict[str, Any] = get_cmdb_type_schema()

    INDEX_KEYS: list[dict[str, Any]] = [
        {'keys': [('name', CmdbDAO.DAO_ASCENDING)], 'name': 'name', 'unique': True},
        {'keys': [('author_id', CmdbDAO.DAO_ASCENDING)], 'name': 'author_id', 'unique': False},
    ]

    # pylint: disable=too-many-locals, too-many-arguments, too-many-positional-arguments
    def __init__(
        self,
        public_id: int,
        name: str,
        author_id: int,
        render_meta: TypeRenderMeta,
        creation_time: datetime | None = None,
        last_edit_time: datetime | None = None,
        editor_id: int | None = None,
        active: bool = True,
        special_type: str | None = None,
        selectable_as_parent: bool = True,
        global_template_ids: list[str] | None = None,
        fields: list[dict[str, Any]] | None = None,
        version: str | None = None,
        label: str | None = None,
        description: str | None = None,
        ci_explorer_label: str | None = None,
        ci_explorer_color: str | None = None,
        acl: AccessControlList | None = None
    ) -> None:
        """
        Initializes a CmdbType

        Args:
            public_id (int): unique public_id of the CmdbType
            name (str): The name of the CmdbType
            author_id (int): The public_id of the CmdbUser who created the CmdbType
            render_meta (TypeRenderMeta): Metadata related to rendering
            creation_time (datetime | None): The time when the CmdbType was created.
                                                Defaults to the current UTC time if not provided
            last_edit_time (datetime | None): The last time the CmdbType was edited
            editor_id (int | None): The public_id of the CmdbUser who last edited the CmdbType
            active (bool): Indicates whether the object is active. Defaults to True
            special_type (str | None): The `SpecialType` marker of the CmdbType (RACK, SUBNET, ...) as
                                        its stored string value, or None for an ordinary CmdbType.
                                        Stored and returned verbatim - `SpecialType` is a str enum, so
                                        a member compares equal to the stored value
            selectable_as_parent (bool): Whether this CmdbType can be a parent Location. Defaults to True
            global_template_ids (list[str]): Names of the global CmdbSectionTemplates used by this
                                                CmdbType (the name is also the render_meta section name)
            fields (list): A list of fields associated with the CmdbType
            version (str): The version of the CmdbType. Defaults to 1.0.0
            label (str): A user-friendly label for the CmdbType. Defaults to a title-cased version of the name
            description (str | None): A description of the CmdbType
            ci_explorer_label (str): Label displayed in the CI Explorer
            ci_explorer_color (str): Color of the CmdbType in the CI Explorer
            acl (AccessControlList | None): AccessControlList for the CmdbType. Defaults to none

        Raises:
            CmdbTypeInitError: If initialization fails due to an error
        """
        try:
            self.name: str = name
            self.label: str = label or self.name.title()
            self.description: str | None = description
            self.version: str = version or CmdbType.DEFAULT_VERSION
            self.selectable_as_parent: bool = selectable_as_parent
            self.global_template_ids: list[str] = global_template_ids or []
            self.active: bool = active
            self.special_type: str | None = special_type
            self.author_id: int = author_id
            self.creation_time: datetime = creation_time or datetime.now(timezone.utc)
            self.editor_id: int | None = editor_id
            self.last_edit_time: datetime | None = last_edit_time
            self.render_meta: TypeRenderMeta = render_meta
            self.fields: list[dict[str, Any]] = fields or []
            self.ci_explorer_label: str | None = ci_explorer_label
            self.ci_explorer_color: str | None = ci_explorer_color
            self.acl: AccessControlList | None = acl

            super().__init__(public_id=public_id)
        except Exception as err:
            raise CmdbTypeInitError(str(err)) from err

# --------------------------------------------------- CLASS METHODS -------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> "CmdbType":
        """
        Initialises a CmdbType from a dict

        Args:
            data (dict): Data with which the CmdbType should be initialised

        Raises:
            CmdbTypeInitFromDataError: If the initialisation with the given data fails

        Returns:
            CmdbType: CmdbType with the given data
        """
        try:
            creation_time: datetime | None = data.get(TypeSchemaKey.CREATION_TIME.value)
            if isinstance(creation_time, str):
                creation_time = parse(creation_time, fuzzy=True)

            last_edit_time: datetime | None = data.get(TypeSchemaKey.LAST_EDIT_TIME.value)
            if isinstance(last_edit_time, str):
                last_edit_time = parse(last_edit_time, fuzzy=True)

            raw_editor_id: Any | None = data.get(TypeSchemaKey.EDITOR_ID.value)

            return cls(
                public_id=int(data[TypeSchemaKey.PUBLIC_ID.value]),
                name=data[TypeSchemaKey.NAME.value],
                selectable_as_parent=data.get(TypeSchemaKey.SELECTABLE_AS_PARENT.value, True),
                global_template_ids=data.get(TypeSchemaKey.GLOBAL_TEMPLATE_IDS.value, []),
                active=data.get(TypeSchemaKey.ACTIVE.value, True),
                special_type=data.get(TypeSchemaKey.SPECIAL_TYPE.value),
                author_id=int(data[TypeSchemaKey.AUTHOR_ID.value]),
                creation_time=creation_time,
                editor_id=int(raw_editor_id) if raw_editor_id is not None else None,
                last_edit_time=last_edit_time,
                label=data.get(TypeSchemaKey.LABEL.value),
                version=data.get(TypeSchemaKey.VERSION.value),
                description=data.get(TypeSchemaKey.DESCRIPTION.value),
                render_meta=TypeRenderMeta.from_data(data.get(TypeSchemaKey.RENDER_META.value, {})),
                fields=data.get(TypeSchemaKey.FIELDS.value) or [],
                ci_explorer_label=data.get(TypeSchemaKey.CI_EXPLORER_LABEL.value),
                ci_explorer_color=data.get(TypeSchemaKey.CI_EXPLORER_COLOR.value),
                acl=AccessControlList.from_data(data.get(TypeSchemaKey.ACL.value, {})),
            )
        except Exception as err:
            raise CmdbTypeInitFromDataError(str(err)) from err


    @classmethod
    def to_json(cls, instance: "CmdbType") -> dict[str, Any]:
        """
        Converts a CmdbType into a json compatible dict

        Args:
            instance (CmdbType): The CmdbType which should be converted

        Raises:
            CmdbTypeToJsonError: If the CmdbType could not be converted to a json compatible dict

        Returns:
            dict: Json compatible dict of the CmdbType values
        """
        try:
            return {
                TypeSchemaKey.PUBLIC_ID.value: instance.get_public_id(),
                TypeSchemaKey.NAME.value: instance.name,
                TypeSchemaKey.SELECTABLE_AS_PARENT.value: instance.selectable_as_parent,
                TypeSchemaKey.GLOBAL_TEMPLATE_IDS.value: instance.global_template_ids,
                TypeSchemaKey.ACTIVE.value: instance.active,
                TypeSchemaKey.SPECIAL_TYPE.value: instance.special_type,
                TypeSchemaKey.AUTHOR_ID.value: instance.author_id,
                TypeSchemaKey.CREATION_TIME.value: instance.creation_time,
                TypeSchemaKey.EDITOR_ID.value: instance.editor_id,
                TypeSchemaKey.LAST_EDIT_TIME.value: instance.last_edit_time,
                TypeSchemaKey.LABEL.value: instance.label,
                TypeSchemaKey.VERSION.value: instance.version,
                TypeSchemaKey.DESCRIPTION.value: instance.description,
                TypeSchemaKey.RENDER_META.value: TypeRenderMeta.to_json(instance.render_meta),
                TypeSchemaKey.FIELDS.value: instance.fields,
                TypeSchemaKey.CI_EXPLORER_LABEL.value: instance.ci_explorer_label,
                TypeSchemaKey.CI_EXPLORER_COLOR.value: instance.ci_explorer_color,
                TypeSchemaKey.ACL.value: AccessControlList.to_json(instance.acl),
            }
        except Exception as err:
            raise CmdbTypeToJsonError(str(err)) from err

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    def get_name(self) -> str:
        """
        Returns the name of the CmdbType

        Returns:
            str: The name of the CmdbType
        """
        return self.name


    def get_label(self) -> str:
        """
        Returns the display label of the CmdbType

        Falls back to the title-cased name when no label is set. The fallback is computed, NOT written
        back - a reader must not change the CmdbType it is reading. `__init__` already applies the same
        default, so the fallback only matters for a label cleared after construction

        Returns:
            str: The display label of the CmdbType, or the title-cased name when none is set
        """
        return self.label or self.name.title()


    def get_externals(self) -> list[TypeExternalLink]:
        """
        Retrieves the external links from the TypeRenderMeta

        Returns:
            list[TypeExternalLink]: A list of external links associated with the TypeRenderMeta
        """
        return self.render_meta.externals


    def has_externals(self) -> bool:
        """
        Checks if the CmdbType has external links

        Returns:
            bool: True if external links exist, False otherwise
        """
        return bool(self.get_externals())


    def get_external(self, name: str) -> TypeExternalLink | None:
        """
        Retrieves a TypeExternalLink by name

        Args:
            name (str): The name of the TypeExternalLink to retrieve

        Returns:
            TypeExternalLink | None: The matching TypeExternalLink if found, otherwise None
        """
        return next((external for external in self.get_externals() if external.name == name), None)


    def has_summaries(self) -> bool:
        """
        Checks if there are any fields in the `summary` object of the TypeRenderMeta

        Returns:
            bool: True if there are fields in the summary, False otherwise
        """
        return self.render_meta.summary.has_fields()


    def get_nested_summaries(self) -> list[dict]:
        """
        Collects the nested summaries of every reference field of the CmdbType

        Every `FieldType.REFERENCE` field may carry a ``summaries`` list overriding, per referenced
        CmdbType, which fields and which summary line the renderer shows. This gathers the entries of
        ALL such fields, not only the first one that declares any

        Note the renderer does not go through here: it reads ``summaries`` off the specific field it
        is rendering, because two reference fields on the same CmdbType may legitimately override the
        same referenced type differently. This is the whole-type view, for a caller that needs every
        override the CmdbType declares

        Returns:
            list[dict]: Every nested-summary entry declared by the type's reference fields, in field
                        order; empty when no reference field declares any
        """
        nested_summaries: list[dict] = []

        for field in self.get_fields():
            if field.get(FieldKey.TYPE.value) != FieldType.REFERENCE:
                continue

            nested_summaries.extend(field.get(FieldKey.SUMMARIES.value) or [])

        return nested_summaries


    def has_nested_prefix(self, nested_summaries: list[dict]) -> str | bool:
        """
        Checks if any of the nested summaries have a matching prefix for this instance

        Looks for the nested-summary entry addressing this CmdbType (`type_id` equal to
        `self.public_id`) and returns its `prefix`. Returns `False` when no entry addresses this type -
        `False` rather than None because the value is a flag the renderer passes straight through

        Args:
            nested_summaries (list[dict]): A list of nested summary dictionaries that may contain a `type_id`
                                            and `prefix` key

        Returns:
            str | bool: The `prefix` of the matching nested summary if found, otherwise `False`
        """
        return next(
            (
                entry[NestedSummaryKey.PREFIX.value] for entry in nested_summaries
                if entry.get(NestedSummaryKey.TYPE_ID.value) == self.public_id
            ),
            False,
        )


    def get_nested_summary_fields(self, nested_summaries: list[dict]) -> list[str]:
        """
        Retrieves the fields from the nested summaries that match the current CmdbType's public_id

        Looks for the nested-summary entry addressing this CmdbType, then resolves the field names it
        lists to their definitions

        A name that no longer resolves to a field is SKIPPED rather than raised: removing a field from
        a CmdbType does not clean the name out of any summary that referenced it, so a stale entry is a
        normal state of a long-lived type and must not cost the caller the whole summary

        Args:
            nested_summaries (list[dict]): A list of nested summary dictionaries containing `type_id` and `fields`

        Returns:
            list[str]: The field definitions named by the matching nested summary, in its order, with
                       names that no longer exist dropped
        """
        field_names: list[str] = next(
            (
                entry[NestedSummaryKey.FIELDS.value] for entry in nested_summaries
                if entry.get(NestedSummaryKey.TYPE_ID.value) == self.public_id
            ),
            [],
        )

        return TypeSummary(self._resolve_summary_fields(field_names)).fields


    def get_nested_summary_line(self, nested_summaries: list[dict]) -> str | None:
        """
        Retrieves the 'line' value from the nested summaries that match the current CmdbType's public_id

        Looks for the nested-summary entry addressing this CmdbType and returns its `line` template,
        or None when no entry addresses this type

        Args:
            nested_summaries (list[dict]): A list of nested summary dictionaries containing `type_id` and `line`

        Returns:
            str | None: The `line` value from the matching nested summary if found, otherwise `None`
        """
        return next(
            (
                entry[NestedSummaryKey.LINE.value] for entry in nested_summaries
                if entry.get(NestedSummaryKey.TYPE_ID.value) == self.public_id
            ),
            None,
        )


    def get_summary(self) -> TypeSummary:
        """
        Retrieves the summary of fields from the TypeRenderMeta

        This method iterates over the fields defined in the `summary` of the TypeRenderMeta,
        fetches the details of each field using `get_field`, and returns a `TypeSummary`
        containing these fields

        A summary name that no longer resolves to a field is SKIPPED - see
        `get_nested_summary_fields` for why a stale name is expected rather than exceptional

        Returns:
            TypeSummary: A `TypeSummary` object holding the resolved summary field definitions
        """
        return TypeSummary(self._resolve_summary_fields(self.render_meta.summary.fields))


    def _resolve_summary_fields(self, field_names: list[str]) -> list[dict[str, Any]]:
        """
        Resolves summary field names to their field definitions, dropping the ones that are gone

        Removing a field from a CmdbType does not clean its name out of `render_meta.summary.fields`
        or out of any reference field's nested summaries, so a summary referencing a deleted field is
        a normal state. Skipping the stale name degrades the summary by one entry instead of raising
        `CmdbTypeFieldNotFoundError` for the whole of it

        Args:
            field_names (list[str]): The summary's configured field names

        Returns:
            list[dict[str, Any]]: The field definitions that still exist, in the given order
        """
        resolved: list[dict[str, Any]] = []

        for field_name in field_names:
            try:
                resolved.append(self.get_field(field_name))
            except CmdbTypeFieldNotFoundError:
                LOGGER.warning(
                    "[CmdbType] Summary of Type with ID %s references the unknown field '%s' - skipped",
                    self.public_id, field_name,
                )

        return resolved


    def get_sections(self) -> list[TypeSection]:
        """
        Retrieves the sections from the TypeRenderMeta

        Returns:
            List[TypeSection]: A list of `TypeSection` objects defined in the `render_meta.sections`
        """
        return self.render_meta.sections


    def get_section(self, name: str) -> TypeSection | None:
        """
        Retrieves a section with the given name

        Args:
            name (str): Name of the section

        Returns:
            TypeSection | None: The Typesection with the given name else None
        """
        return next((section for section in self.get_sections() if section.name == name), None)


    def get_icon(self) -> str | None:
        """
        Retrieves the icon of the current CmdbType

        This method returns the `icon` from the `render_meta` if available. If not,
        it returns `None`

        Returns:
            str | None: The icon as a string if available, otherwise `None`
        """
        return getattr(self.render_meta, 'icon', None)


    def has_sections(self) -> bool:
        """
        Checks if the CmdbType has any sections

        This method returns True if the CmdbType has one or more sections, otherwise it returns False

        Returns:
            bool: True if at least one section is present, False otherwise
        """
        return len(self.get_sections()) > 0


    def get_fields(self) -> list[dict[str, Any]]:
        """
        Retrieves all fields of the CmdbType

        This method returns the list of fields associated with the current `CmdbType`

        Returns:
            List: A list of fields for the current `CmdbType`
        """
        return self.fields


    def get_field(self, name: str) -> dict[str, Any]:
        """
        Retrieves a field by its name

        Args:
            name (str): The name of the field to retrieve

        Raises:
            CmdbTypeFieldNotFoundError: If no field with the specified name is found

        Returns:
            dict: The field as a dictionary
        """
        field = next((x for x in self.fields if x[FieldKey.NAME.value] == name), None)

        if field:
            return field

        raise CmdbTypeFieldNotFoundError(f"Field '{name}' was not found on Type with ID: {self.public_id}!")


    def get_all_mds_fields(self) -> list[str]:
        """
        Retrieves all field names from multi-data sections

        This method searches through the sections in the `render_meta` and collects the names of all
        fields that belong to sections of type SectionType.MDS_SECTION (render_meta sections store
        their fields as name strings)

        Returns:
            list[str]: A list containing the names of all fields from multi-data sections
        """
        mds_fields: list[str] = []

        for section in self.render_meta.sections:
            if section.type == SectionType.MDS_SECTION:
                mds_fields.extend(section.fields)

        return mds_fields


    def get_mds_section_ids(self) -> set[str]:
        """
        Retrieves the ids of all multi-data sections declared by the CmdbType

        A section's name is what a CmdbObject stores as the ``section_id`` of its multi_data_sections
        entries, so this is the set of MDS section_ids the type permits

        Returns:
            set[str]: The section_ids (names) of every SectionType.MDS_SECTION section
        """
        return {
            section.name for section in self.render_meta.sections if section.type == SectionType.MDS_SECTION
        }


    def get_all_fields_of_type(self, field_type: str) -> list[str]:
        """
        Retrieves all field names of the specified type

        This method iterates through the fields and collects the names of fields
        that match the given `field_type`

        Args:
            field_type (str): The FieldType value to search for

        Returns:
            list[str]: A list of field names that match the specified field type
        """
        field_names = [
            field[FieldKey.NAME.value] for field in self.fields if field[FieldKey.TYPE.value] == field_type
        ]

        return field_names


    def get_fields_with_type(self, field_type: str) -> dict[str, dict[str, Any]]:
        """
        Retrieves the field definitions of the specified type, keyed by field name

        The name-keyed counterpart of ``get_all_fields_of_type``, for callers that need the whole
        definition (options, default value, flags) instead of only the names

        Args:
            field_type (str): The type of the fields to collect (a ``FieldType`` value)

        Returns:
            dict[str, dict[str, Any]]: {field name: field definition} of every matching field
        """
        return {f[FieldKey.NAME.value]: f for f in self.fields if f[FieldKey.TYPE.value] == field_type}
