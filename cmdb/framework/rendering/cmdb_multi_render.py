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

Turns stored CmdbObjects into the RenderResults the UI, the search, the exporters and DocAPI all read.
A render merges an object's stored values into its CmdbType's field definitions, groups them by the
type's sections, resolves references and builds the summary line.

Three things about this module decide how a change here behaves:

* **Rendering degrades, it does not fail.** Almost every step is wrapped in
  `except Exception: LOGGER.debug(...)` and continues with whatever it has - a reference that cannot be
  expanded, a summary that cannot be built or a ref-section field that cannot be read costs that piece
  of the result and nothing more. The trade-off is that a partial render is indistinguishable from a
  complete one: nothing marks the RenderResult and the only trace is a DEBUG line.
* **References recurse, bounded by `level`.** `result(level=3)` is the default depth; each nested
  expansion decrements it and `level == 0` stops the recursion. A reference cycle therefore terminates
  by depth rather than by cycle detection
* **The caches are shared on purpose.** `shared_objects_cache` / `shared_types_cache` /
  `shared_users_cache` are extended IN PLACE, so a nested render reuses what the outer one already
  loaded and each referenced document is fetched once across the whole recursion. The cached dicts are
  live - anything copied out of them (`get_field`, `get_summary`) must be copied before it is mutated,
  which is why several methods build a `dict(...)` first

Every key this module writes is named by the enum that OWNS it, never by a literal: `FieldKey` for a
field definition's own keys, `RenderedFieldKey` for the keys a render ADDS to a field (`reference`,
`references`, `default`), `TypeReferenceKey` for what sits inside `reference`,
`RenderedReferenceSectionKey` for what sits inside `references`, and `RenderObjectInfoKey` /
`RenderTypeInfoKey` for the two blocks of a RenderResult.

A section kind this version does not know is **rendered, not dropped**. `TypeRenderMeta.SECTION_CLASSES`
answers an unrecognised `type` with a `TypeFieldSection` that keeps its original kind string, so a Type
saved by a newer version stays readable; `__merge_fields_value` follows that policy - anything that is
not a reference section and carries a `fields` list is merged as a plain section, and
`_accept_unknown_section` logs what it did. An `elif` chain ending in nothing would leave a section
class outside the three contributing no fields with no log and no marker. On the WRITE side the
schema is strict instead: `render_meta.sections.type` only accepts a `SectionType` member.

There is exactly ONE producer per payload. A reference expansion is always a serialised
`TypeReference` built by `__merge_references` - `_build_reference_expansion` delegates to it rather
than assembling a shape of its own - so the seven keys the frontend, the human-readable exporter and
the search matcher read are the same whichever render path filled them. The one deliberate exception
is a LOCATION field, whose expansion is a placeholder (`_build_location_reference`,
`RenderedLocationReferenceKey`) because nothing resolves a location here
"""
from logging import Logger, getLogger
from typing import Any
from copy import deepcopy

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import (
    ObjectsManager,
    UsersManager,
    TypesManager,
)

from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import (
    CmdbType,
    DEFAULT_PORT_SECTION_INDEX,
    TypeReference,
    TypeExternalLink,
    TypeFieldSection,
    TypeReferenceSection,
    TypeMultiDataSection,
)
from cmdb.models.type_model.type_section import TypeSection
from cmdb.models.type_model.section_key_enum import SectionKey
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.type_reference_key_enum import TypeReferenceKey
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.models.user_model import CmdbUser
from cmdb.utils import coerce_mongo_datetime
from cmdb.framework.rendering.render_constants import (
    ANONYMOUS_NAME,
    RenderedFieldKey,
    RenderedLocationReferenceKey,
    RenderedReferenceSectionKey,
    RenderObjectInfoKey,
    RenderTypeInfoKey,
)
from cmdb.framework.rendering.render_result import RenderResult

from cmdb.errors.models.cmdb_type import CmdbTypeFieldNotFoundError, CmdbTypeReferenceLineFillError
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
        ref_render: bool = False,
        *,
        shared_objects_cache: dict[int, CmdbObject] | None = None,
        shared_types_cache: dict[int, CmdbType] | None = None,
        shared_users_cache: dict[int, CmdbUser] | None = None,
    ) -> None:
        """
        Initializes CmdbMultiRender

        The shared_* caches let a nested render (reference-section resolution) reuse an outer render's
        already-loaded objects/types/users. They are extended in place with only the ids not already
        present, so each referenced document is fetched once across the whole (possibly recursive)
        render instead of every nested node rebuilding its own caches from scratch

        Args:
            to_render_objects (list[CmdbObject]): All CmdbObjects which should be rendered
            render_user (CmdbUser): The user who is requesting the render
            ref_render (bool, optional): Flag to enable reference rendering. Defaults to False
            shared_objects_cache (dict[int, CmdbObject] | None): Reused/extended object cache
            shared_types_cache (dict[int, CmdbType] | None): Reused/extended type cache
            shared_users_cache (dict[int, CmdbUser] | None): Reused/extended user cache
        """
        self.to_render_objects: list[CmdbObject] = to_render_objects
        self.render_user: CmdbUser = render_user

        self.objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, self.render_user)
        self.types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, self.render_user)
        self.users_manager: UsersManager = ManagerProvider.get_manager(ManagerType.USERS, self.render_user)

        self.ref_render: bool = ref_render

        # Caches - reuse the shared ones when provided (nested render), else start fresh. Each is
        # extended only with the ids it is still missing (see the get_all_linked_* helpers)
        self.objects_cache: dict[int, CmdbObject] = shared_objects_cache if shared_objects_cache is not None else {}
        self.types_cache: dict[int, CmdbType] = shared_types_cache if shared_types_cache is not None else {}
        self.users_cache: dict[int, CmdbUser] = shared_users_cache if shared_users_cache is not None else {}

        # Which (type_id, section) pairs already had their broken reference reported. A list render
        # walks many objects through the same type, so without this a single broken ref-section would
        # emit one warning per object per request
        self.reported_reference_problems: set[tuple[str, int, str]] = set()

        self.objects_cache.update(self.get_all_linked_objects())
        self.types_cache.update(self.get_all_linked_types())
        self.users_cache.update(self.get_all_linked_users())


    def result(self, level: int = 3, single_object: bool = False) -> list[RenderResult] | RenderResult | None:
        """
        Renders every object in ``to_render_objects`` into a RenderResult

        Objects whose type is missing from the cache are skipped. Each result bundles the object and
        type information, the merged (and, when ``ref_render`` is set, reference-resolved) fields, the
        type sections, the summaries/summary line, the external links and the multi-data-sections. The
        per-result values are deep-copied so the shared type/object caches are never mutated by callers

        Args:
            level (int): Reference-resolution depth for nested references. Defaults to 3
            single_object (bool): When True return the first RenderResult instead of a list

        Returns:
            list[RenderResult] | RenderResult | None: The rendered result(s); when ``single_object`` is
            set, the single RenderResult, or None when nothing rendered (e.g. the object's type is missing)
        """
        render_results: list[RenderResult] = []

        for obj in self.to_render_objects:
            obj_type: CmdbType | None = self.types_cache.get(obj.get_type_id())

            if not obj_type:
                LOGGER.error("[render] Type for Object with type_id:%s not found!", obj.get_type_id())
                continue

            result = RenderResult()
            # object/type information build fresh dicts of immutable values; fields are freshly copied
            # during merge (copy-on-write off the cache), so none of these need an extra deep copy
            result.object_information = self.__generate_object_information(obj)
            result.type_information = self.__generate_type_information(obj_type)
            result.fields = self.__set_fields(obj, obj_type, level)
            # sections/externals/mds still serialise structures that share lists with the cache/object
            result.sections = deepcopy(self.__get_type_sections(obj_type))
            result = self.__set_summaries(result, obj, obj_type)
            result.externals = deepcopy(self.__set_externals(obj, obj_type))
            result.multi_data_sections = deepcopy(obj.multi_data_sections)

            render_results.append(result)

        if single_object:
            return render_results[0] if render_results else None

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
            RenderObjectInfoKey.OBJECT_ID.value: obj.public_id,
            RenderObjectInfoKey.CREATION_TIME.value: obj.creation_time,
            RenderObjectInfoKey.LAST_EDIT_TIME.value: obj.last_edit_time,
            RenderObjectInfoKey.AUTHOR_ID.value: obj.author_id,
            RenderObjectInfoKey.AUTHOR_NAME.value: self.get_user_name(obj.author_id),
            RenderObjectInfoKey.EDITOR_ID.value: obj.editor_id,
            RenderObjectInfoKey.EDITOR_NAME.value: self.get_user_name(obj.editor_id, True),
            RenderObjectInfoKey.ACTIVE.value: obj.active,
            RenderObjectInfoKey.VERSION.value: obj.version,
            RenderObjectInfoKey.SPECIAL_TYPE.value: obj.special_type,
        }

        return object_info


    def __generate_type_information(self, type_instance: CmdbType) -> dict[str, Any]:
        """
        Generate type-specific information for rendering using cached types and users.

        The keys are named by `RenderTypeInfoKey`, which also documents what the block deliberately
        does and does not carry

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
        # A CURATED selection, not a dump of the CmdbType: a flag added to the model does not appear
        # here on its own, which is why `uses_ports` was absent until it was added deliberately
        type_info: dict[str, Any] = {
            RenderTypeInfoKey.TYPE_ID.value: type_instance.public_id,
            RenderTypeInfoKey.TYPE_NAME.value: type_instance.name,
            RenderTypeInfoKey.TYPE_LABEL.value: type_instance.label,
            RenderTypeInfoKey.CREATION_TIME.value: type_instance.creation_time,
            RenderTypeInfoKey.AUTHOR_ID.value: type_instance.author_id,
            RenderTypeInfoKey.AUTHOR_NAME.value: self.get_user_name(type_instance.author_id),
            RenderTypeInfoKey.ICON.value: icon,
            RenderTypeInfoKey.ACTIVE.value: type_instance.active,
            RenderTypeInfoKey.VERSION.value: type_instance.version,
            RenderTypeInfoKey.ACL.value: type_instance.acl.to_json(type_instance.acl),
            # TYPE-level presentation state a client needs while rendering an object: whether the
            # object may be picked as a location parent, whether it may carry ports (which is what
            # decides if the ports panel renders at all) and, when it does, where that panel sits
            # among the type's sections. Read with getattr-style defaults so a CmdbType built from a
            # document predating any of them renders instead of raising
            RenderTypeInfoKey.SELECTABLE_AS_PARENT.value: bool(
                getattr(type_instance, TypeSchemaKey.SELECTABLE_AS_PARENT.value, False),
            ),
            RenderTypeInfoKey.USES_PORTS.value: bool(
                getattr(type_instance, TypeSchemaKey.USES_PORTS.value, False),
            ),
            RenderTypeInfoKey.PORT_SECTION_INDEX.value: getattr(
                type_instance, TypeSchemaKey.PORT_SECTION_INDEX.value, DEFAULT_PORT_SECTION_INDEX,
            ),
        }

        return type_info


    def __get_type_sections(self, type_instance: CmdbType) -> list[dict[str, Any]]:
        """
        Serialise the type's render_meta sections for the render result

        Args:
            type_instance (CmdbType): The CmdbType whose sections should be serialised

        Returns:
            list[dict[str, Any]]: The sections of the type (empty list on error)
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
        Build the merged field list for the render result

        Args:
            object_instance (CmdbObject): The object whose values are merged into the fields
            type_instance (CmdbType): The object's type, providing the field/section definitions
            level (int): The reference-resolution depth

        Returns:
            list[dict[str, Any]]: The merged fields
        """
        return self.__merge_fields_value(object_instance, type_instance, level-1)


    def __set_externals(
        self,
        object_instance: CmdbObject,
        type_instance: CmdbType
    ) -> list[dict[str, Any]]:
        """
        Build the resolved external links for the render result

        For each external link defined on the type, collect the required field values from the object,
        fill the link href and serialise it. Links whose required values are missing are skipped

        Args:
            object_instance (CmdbObject): The object providing the field values
            type_instance (CmdbType): The type defining the external links

        Returns:
            list[dict[str, Any]]: The resolved external links (empty when the type has none)
        """
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

                # The link belongs to the CACHED CmdbType, shared by every object of this type in the
                # batch, so the filled href is taken as a value and the template is left untouched
                externals.append({**TypeExternalLink.to_json(ext), 'href': ext.filled_href(field_values)})

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

        Best-effort, like the rest of the render: anything raised while building the summary - most
        realistically `CmdbObject.get_value` refusing a field the object does not carry, which happens
        whenever a field is added to a type and put in its summary before existing objects are saved -
        drops the summaries entirely and falls back to '<type label> #<public_id>'. A summary naming a
        field that no longer exists on the TYPE does not reach here: `CmdbType.get_summary` skips it, so
        the remaining fields still render

        Args:
            render_result (RenderResult): The current render result object to update
            object_instance (CmdbObject): The object being rendered (for the default summary line)
            type_instance (CmdbType): The object's type, providing the summary field definitions

        Returns:
            RenderResult: Updated render result with summaries and summary line filled
        """
        default_line = f'{type_instance.label} #{object_instance.public_id}'

        if not type_instance.has_summaries():
            render_result.summaries = []
            render_result.summary_line = default_line
            return render_result

        try:
            # Copy each summary field definition (get_summary() returns live cached field dicts) and fill
            # its value from the object - the render no longer mutates the cached fields in place
            summary_list = []
            for item in type_instance.get_summary().fields:
                entry = dict(item)
                entry[FieldKey.VALUE] = object_instance.get_value(entry[FieldKey.NAME])
                summary_list.append(entry)

            render_result.summaries = summary_list

            render_result.summary_line = " | ".join(
                str(line.get(FieldKey.VALUE, "")) for line in summary_list
            ) or default_line

        except Exception as err:
            LOGGER.debug("[__set_summaries] Falling back to default summary line: %s", err)
            render_result.summaries = []
            render_result.summary_line = default_line

        return render_result

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    def get_user_name(self, user_id: int | None = None, for_editor: bool = False) -> str | None:
        """
        Resolve a user's display name from the users cache

        Args:
            user_id (int | None): The user's public_id. Defaults to None
            for_editor (bool): When True a missing user_id yields None (no editor), otherwise the
                               anonymous placeholder name. Defaults to False

        Returns:
            str | None: The display name, the anonymous placeholder, or None for a missing editor
        """
        if not user_id:
            return None if for_editor else ANONYMOUS_NAME

        user: CmdbUser | None = self.users_cache.get(user_id)

        return user.get_display_name() if user else ANONYMOUS_NAME


    def get_all_linked_users(self) -> dict[int, CmdbUser]:
        """
        Collect the author/editor users of the rendered objects and the authors of their types, and
        return them as a single bulk lookup (one query) keyed by public_id

        Returns:
            dict[int, CmdbUser]: Lookup of user public_id -> CmdbUser (empty when none are referenced)
        """
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

        # Only fetch the users not already cached (a nested render reuses the outer cache)
        user_ids -= set(self.users_cache)

        if not user_ids:
            return {}

        linked_users: dict[int, CmdbUser] = self.users_manager.get_user_lookup(list(user_ids))

        return linked_users


    def get_all_linked_types(self) -> dict[int, CmdbType]:
        """
        Collect the types needed to render every object and return them as a bulk lookup by public_id

        Loads three groups in at most two queries: the rendered objects' own types, the types of every
        referenced object already in the cache, and the target type of every ref-section declared by
        those types. The ref-section target must be loaded even when no object is referenced yet (value
        None) - otherwise __merge_fields_value drops the ref-section field and the frontend hides the
        whole section. Only the direct ref-section targets are pulled here; deeper reference chains are
        resolved by the nested render that runs once an object is actually referenced

        Returns:
            dict[int, CmdbType]: Lookup of type public_id -> CmdbType (empty when none are referenced)
        """
        type_ids: set[int] = set()

        for obj in self.to_render_objects:
            type_ids.add(obj.get_type_id())

        # types from referenced objects (objects_cache is populated before this runs in __init__)
        for obj in self.objects_cache.values():
            type_ids.add(obj.get_type_id())

        # Only fetch the types not already cached (a nested render reuses the outer cache)
        type_ids -= set(self.types_cache)

        linked_types: dict[int, CmdbType] = {}

        if type_ids:
            linked_types = self.types_manager.get_types_lookup(list(type_ids))

        # Every ref-section renders fields from a target type regardless of whether an object is
        # referenced, so that target must be cached too. Scan the loaded (and already cached) types
        # for their ref-section targets and bulk-fetch the ones still missing.
        known_types: dict[int, CmdbType] = {**self.types_cache, **linked_types}
        missing_ref_type_ids: set[int] = self.__collect_ref_section_type_ids(list(known_types.values())) \
                                         - set(known_types)

        if missing_ref_type_ids:
            linked_types.update(self.types_manager.get_types_lookup(list(missing_ref_type_ids)))

        return linked_types


    @staticmethod
    def __collect_ref_section_type_ids(types: list[CmdbType]) -> set[int]:
        """
        Collect the reference target type_id of every ref-section declared by the given types

        Args:
            types (list[CmdbType]): The types whose render_meta sections should be scanned

        Returns:
            set[int]: The type_ids referenced by any ref-section (empty when there are none)
        """
        ref_type_ids: set[int] = set()

        for type_instance in types:
            for section in type_instance.render_meta.sections:
                if isinstance(section, TypeReferenceSection) and section.reference \
                        and section.reference.type_id is not None:
                    ref_type_ids.add(section.reference.type_id)

        return ref_type_ids


    def get_all_linked_objects(self) -> dict[int, CmdbObject]:
        """
        Collect all referenced objects (ref + ref-section-field) and return as lookup.

        Returns:
            dict[int, CmdbObject]: Lookup of object_id -> CmdbObject
        """
        if not self.ref_render:
            return {}

        reference_ids: set[int] = set()
        # Fallback lookup for legacy fields missing a 'type' key: fetch each object's type at most
        # once (keyed by type_id) instead of re-querying it per untyped field (avoids an N+1)
        fallback_types: dict[int, CmdbType | None] = {}

        # Collect referenced object IDs
        for obj in self.to_render_objects:
            for field in obj.fields:
                field_type = field.get(FieldKey.TYPE)

                if not field_type:
                    LOGGER.debug(
                        "Field-Type in Object: %s not found for field name: %s !",
                        obj.public_id,
                        field.get(FieldKey.NAME)
                    )
                    type_id = obj.get_type_id()
                    if type_id not in fallback_types:
                        fallback_types[type_id] = self.types_manager.get_type_instance(type_id)
                    type_instance: CmdbType | None = fallback_types[type_id]

                    if not type_instance:
                        LOGGER.debug("Type of Object: %s not found!", obj.public_id)
                        continue

                    target_field = type_instance.get_field(field[FieldKey.NAME])

                    field_type = target_field[FieldKey.TYPE]


                if field_type in (FieldType.REFERENCE, FieldType.REF_SECTION) and field.get(FieldKey.VALUE):
                    reference_ids.add(int(field[FieldKey.VALUE]))

        # Only fetch the referenced objects not already cached (a nested render reuses the outer cache)
        reference_ids -= set(self.objects_cache)

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
            ref_section_field: dict[str, Any],
            ref_section_fields: list[dict[str, Any]],
            level: int
    ) -> list[dict[str, Any]]:
        """
        Recursively merges fields from a referenced section into the current section fields list.

        This method handles fields of type 'ref-section-field' by retrieving the referenced object,
        rendering its fields, and recursively merging their contents.

        Args:
            ref_section_field (dict[str, Any]): The reference section field to process
            ref_section_fields (list[dict[str, Any]]): A list to accumulate merged fields
            level (int): The depth level for rendering referenced objects

        Returns:
            list[dict[str, Any]]: The updated list of merged reference section fields
        """
        if ref_section_field and ref_section_field.get(FieldKey.TYPE, '') == FieldType.REF_SECTION:
            try:
                reference_id = ref_section_field.get(FieldKey.VALUE)

                # Reuse the already-loaded object when present, else fetch once (and it lands in the
                # shared cache below); avoids re-querying references resolved higher up the render
                instance = self.objects_cache.get(reference_id)
                if instance is None:
                    instance = CmdbObject.from_data(self.objects_manager.get_object(reference_id))

                # Share this render's caches with the nested render so it does not rebuild them from
                # scratch (this is what turns the previous per-node N+1 into a single shared cache)
                render = CmdbMultiRender(
                    [instance], self.render_user, True,
                    shared_objects_cache=self.objects_cache,
                    shared_types_cache=self.types_cache,
                    shared_users_cache=self.users_cache,
                )
                fields = render.result(level)[0].fields
                res = next(
                    (x for x in fields if x[FieldKey.NAME] == ref_section_field.get(FieldKey.NAME, '')), None
                )

                if res and ref_section_field.get(FieldKey.TYPE, '') == FieldType.REF_SECTION:
                    self.__merge_reference_section_fields(res, ref_section_fields, level)

                    for field in res[RenderedFieldKey.REFERENCES][RenderedReferenceSectionKey.FIELDS]:
                        merged_field_content = self.__merge_field_content_section(field, instance)
                        if merged_field_content and \
                           merged_field_content.get(FieldKey.TYPE, '') == FieldType.REF_SECTION:
                            self.__merge_reference_section_fields(merged_field_content, ref_section_fields, level)
                        else:
                            ref_section_fields.append(merged_field_content)
            except Exception as err:
                LOGGER.debug("[__merge_reference_section_fields] Exception: %s. Type: %s", err, type(err).__name__)

        return ref_section_fields


    @staticmethod
    def _build_reference_summaries(
        ref_type: CmdbType,
        ref_object: CmdbObject,
        nested_summaries: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[str], str | None]:
        """
        Build the reference summaries, their string values and the nested summary line

        The summary fields are the type's configured nested summary fields when a nested summary is
        set, otherwise the type's default summary fields; each summary value is read from the
        referenced object

        Args:
            ref_type (CmdbType): The referenced object's type
            ref_object (CmdbObject): The referenced object providing the values
            nested_summaries (list[dict[str, Any]]): The field's configured nested summaries

        Returns:
            tuple[list[dict[str, Any]], list[str], str | None]: (summaries, summary values, summary line)
        """
        nested_summary_line: str | None = ref_type.get_nested_summary_line(nested_summaries)
        nested_summary_fields = nested_summaries

        try:
            nested_summary_fields = ref_type.get_nested_summary_fields(nested_summaries)
        except CmdbTypeFieldNotFoundError as error:
            LOGGER.warning('Summary setting refers to non-existent field(s), Error %s', error)

        summary_fields = nested_summary_fields \
            if (nested_summary_line or nested_summary_fields) else ref_type.get_summary().fields

        summaries: list[dict[str, Any]] = []
        summary_values: list[str] = []

        for field in summary_fields:
            ref_value = next(
                (x[FieldKey.VALUE] for x in ref_object.fields if x[FieldKey.NAME] == field[FieldKey.NAME]), ''
            )
            summary_value = str(ref_value)
            summaries.append({FieldKey.VALUE.value: summary_value, FieldKey.TYPE.value: field.get(FieldKey.TYPE)})
            summary_values.append(summary_value)

        return summaries, summary_values, nested_summary_line


    def __merge_references(self, current_field: dict[str, Any]) -> dict[str, Any]:
        """
        Merges reference data for a given field

        Resolves the referenced object/type from the caches and builds the reference summaries and
        line. Always returns a serialised TypeReference - an empty one when the field has no value,
        the reference is unresolved, or an error occurs

        Args:
            current_field (dict[str, Any]): The field to check and merge references for

        Returns:
            dict[str, Any]: The serialised reference data (empty reference when nothing resolves)
        """
        reference = TypeReference.empty()

        # No value on the field - return an empty reference rather than None (callers expect a dict)
        if not current_field[FieldKey.VALUE]:
            return TypeReference.to_json(reference)

        ref_object: CmdbObject | None = self.objects_cache.get(int(current_field[FieldKey.VALUE]))
        if not ref_object:
            return TypeReference.to_json(reference)

        try:
            ref_type: CmdbType | None = self.types_cache.get(ref_object.get_type_id())
            if not ref_type:
                return TypeReference.to_json(reference)

            nested_summaries = current_field.get(FieldKey.SUMMARIES, [])
            summaries, summary_values, nested_summary_line = self._build_reference_summaries(
                ref_type, ref_object, nested_summaries
            )

            reference.type_id = ref_type.get_public_id()
            reference.object_id = int(current_field[FieldKey.VALUE])
            reference.type_label = ref_type.label
            reference.icon = ref_type.get_icon()
            reference.prefix = ref_type.has_nested_prefix(nested_summaries)
            reference.summaries = summaries

            # Only evaluate the line when one is configured: a reference field without a custom
            # line has nothing to fill, and its summary FIELDS are what the frontend shows instead
            reference.line = nested_summary_line

            if nested_summary_line:
                # A line without placeholders is shown as it is, which makes the summary fields
                # redundant for this reference
                if not reference.line_requires_fields():
                    reference.summaries = []

                try:
                    reference.fill_line(summary_values)
                except CmdbTypeReferenceLineFillError as err:
                    # The line is left unfilled by fill_line, and answering it would show the raw
                    # '{}' template in the reference block. An EMPTY line is the frontend's
                    # documented fallback (icon + label + #id + summaries), so degrade to that -
                    # summary fields included, since they were only dropped because the line was
                    # going to carry the information - and report it: a line that no longer fits its
                    # type's summary fields is a configuration problem someone has to see
                    LOGGER.warning(
                        "[__merge_references] Summary line of Type ID:%s does not fit Object ID:%s, "
                        "answering the reference without it: %s",
                        ref_type.get_public_id(), reference.object_id, err,
                    )
                    reference.line = ''
                    reference.summaries = summaries

            return TypeReference.to_json(reference)
        except Exception as err:
            LOGGER.debug("[__merge_references] Exception: %s. Type: %s", err, type(err).__name__)
            return TypeReference.to_json(reference)


    def __merge_field_content_section(self, t_field: dict[str, Any], object_instance: CmdbObject) -> dict[str, Any]:
        """
        Merge field content with the given CmdbObject data

        Args:
            t_field (dict[str, Any]): The field to merge
            object_instance (CmdbObject): The object containing the data

        Returns:
            dict[str, Any]: The merged field content
        """
        # Copy first: t_field is a reference into the shared cached type (CmdbType.get_field returns the
        # live dict), so mutating it directly would corrupt the cache and bleed values across renders
        t_field = dict(t_field)

        obj_field: dict[str, Any] | None = next(
            (x for x in object_instance.fields if x[FieldKey.NAME] == t_field[FieldKey.NAME]), None
        )

        # The object may not carry this field yet (e.g. a type field added after its last save, or a
        # create that sent only some of the Type's fields); leave the type's default value in place
        # rather than raising. `setdefault` is what keeps the rendered entry a name+value+type
        # TRIPLE: a type field without a configured default has no 'value' key at all, so returning
        # it unchanged answers a field a consumer cannot read a value off - `undefined` rather than
        # null on the frontend, for every field an object has no entry for
        if obj_field is None:
            t_field.setdefault(FieldKey.VALUE, None)

            return t_field

        if t_field.get(FieldKey.VALUE):
            t_field[RenderedFieldKey.DEFAULT] = t_field[FieldKey.VALUE]

        t_field[FieldKey.VALUE] = obj_field[FieldKey.VALUE]

        # A DATE field whose stored value is a string is turned into a real date for the response.
        # This is the ONE place a date is read out of USER data rather than out of a machine-written
        # timestamp, which is why an unreadable value is LEFT AS IT IS rather than guessed: it used to
        # be `parse(..., fuzzy=True)`, so a field holding 'ask Bob' rendered as a date assembled from
        # today - invented on read, never stored, and carried into every export and report. Refusing
        # outright is not an option either: the render is crash-tolerant by construction, and one bad
        # cell must not take a whole object's view down
        if t_field[FieldKey.TYPE] == FieldType.DATE and isinstance(t_field[FieldKey.VALUE], str) \
           and t_field[FieldKey.VALUE]:
            t_field[FieldKey.VALUE] = coerce_mongo_datetime(t_field[FieldKey.VALUE]) or t_field[FieldKey.VALUE]

        if self.ref_render and t_field[FieldKey.TYPE] in (FieldType.REFERENCE, FieldType.LOCATION) \
           and t_field[FieldKey.VALUE]:
            t_field[RenderedFieldKey.REFERENCE] = self.__merge_references(t_field)

        return t_field


    def _build_reference_expansion(self, reference_id: int) -> dict[str, Any] | None:
        """
        Build the expanded reference dict for a 'ref' field from the caches

        Args:
            reference_id (int): The public_id of the referenced object

        Returns:
            dict[str, Any] | None: The reference dict (type info + per-field summaries), or None when
                                   the referenced object/type cannot be resolved (e.g. ref_render off)
        """
        # ONE producer for this payload: `__merge_references` serialises a `TypeReference`, whose keys
        # `TypeReferenceKey` owns and the frontend, the human-readable exporter and the search matcher
        # all read. A second, five-key dict built here - no `line`, no `icon`, no `prefix`, and
        # `summaries` holding EVERY field of the referenced type rather than the type's configured
        # summary fields - would make the same `reference` key carry two different shapes depending
        # on which render path filled it
        reference: dict[str, Any] = self.__merge_references({FieldKey.VALUE: reference_id})

        # The empty reference (object_id 0) is how `TypeReference` reports "did not resolve"; this
        # method's callers expect None for that, and clear the field's value on it
        if not reference.get(TypeReferenceKey.OBJECT_ID.value):
            return None

        return reference


    def _build_location_reference(self, reference_id: int) -> dict[str, Any]:
        """
        Build the placeholder reference dict for a 'location' field

        Args:
            reference_id (int): The public_id referenced by the location field

        Returns:
            dict[str, Any]: The location reference dict
        """
        return {
            RenderedLocationReferenceKey.TYPE_ID.value: '',
            RenderedLocationReferenceKey.TYPE_NAME.value: '',
            RenderedLocationReferenceKey.TYPE_LABEL.value: '',
            RenderedLocationReferenceKey.OBJECT_ID.value: reference_id,
            RenderedLocationReferenceKey.SUMMARIES.value: [],
        }


    def __merge_fields_value(
        self,
        object_instance: CmdbObject,
        type_instance: CmdbType,
        level: int = 3
    ) -> list[dict[str, Any]]:
        """
        Merge all field values with references extended

        Delegates each render_meta section to the matching helper: plain field/MDS sections to
        ``_merge_plain_section_fields`` and reference sections to ``_merge_reference_section``

        Args:
            object_instance (CmdbObject): The object whose values are merged into the type's fields
            type_instance (CmdbType): The object's type, providing the field/section definitions
            level (int): The level of rendering detail

        Returns:
            list[dict[str, Any]]: A list of merged fields with reference data
        """
        field_map: list[dict[str, Any]] = []
        if level == 0:
            return field_map

        for section in type_instance.render_meta.sections:
            if isinstance(section, TypeReferenceSection):
                ref_field = self._merge_reference_section(section, object_instance, type_instance, level)
                if ref_field is not None:
                    field_map.append(ref_field)
                continue

            if not isinstance(section, (TypeFieldSection, TypeMultiDataSection)) \
               and not self._accept_unknown_section(section, type_instance):
                continue

            field_map.extend(self._merge_plain_section_fields(section, object_instance, type_instance))

        return field_map


    @staticmethod
    def _accept_unknown_section(section: TypeSection, type_instance: CmdbType) -> bool:
        """
        Decide whether a section of a kind this render does not know can still be merged

        `TypeRenderMeta.SECTION_CLASSES` answers a stored kind it does not know with a
        `TypeFieldSection`, and the frontend's section factory draws such a section as a field
        section, so the render follows the same policy instead of dropping the section: anything
        carrying a `fields` list is merged as a plain section. What cannot be merged is reported -
        the previous `elif` chain ended with no branch at all, so a section the render did not
        recognise contributed no fields, with no log and no marker

        Args:
            section (TypeSection): The section whose kind none of the known classes covers
            type_instance (CmdbType): The type the section belongs to, for the log line

        Returns:
            bool: True when the section can be merged as a plain one, False when it is skipped
        """
        kind: Any = getattr(section, SectionKey.TYPE, None)
        name: Any = getattr(section, SectionKey.NAME, None)

        if hasattr(section, SectionKey.FIELDS):
            LOGGER.warning(
                "[_accept_unknown_section] Type ID:%s section '%s' has the unknown kind '%s' - "
                "rendered as a plain section", type_instance.public_id, name, kind,
            )
            return True

        LOGGER.warning(
            "[_accept_unknown_section] Type ID:%s section '%s' of the unknown kind '%s' carries no "
            "fields list and is skipped", type_instance.public_id, name, kind,
        )
        return False


    def _merge_plain_section_fields(
        self,
        section: TypeFieldSection | TypeMultiDataSection,
        object_instance: CmdbObject,
        type_instance: CmdbType
    ) -> list[dict[str, Any]]:
        """
        Merge the field values of a plain field or multi-data section

        Each field is merged with the object's value; reference/location fields not already expanded
        by the merge get their reference expansion filled here. A field that fails to merge degrades
        to a null value rather than aborting the section

        Args:
            section (TypeFieldSection | TypeMultiDataSection): The section whose fields are merged
            object_instance (CmdbObject): The object providing the field values
            type_instance (CmdbType): The object's type, providing the field definitions

        Returns:
            list[dict[str, Any]]: The merged fields of the section
        """
        fields: list[dict[str, Any]] = []

        for sf_name in section.fields:
            field: dict[str, Any] = {}
            try:
                field = type_instance.get_field(sf_name)
                field = self.__merge_field_content_section(field, object_instance)

                # Only when the merge above did not expand it. Testing `'summaries' not in field`
                # instead is ALWAYS true - summaries live inside the `reference` payload, never at
                # field level - which would replace the merged field (and its reference) on every
                # reference/location field of a plain section
                if field[FieldKey.TYPE] in (FieldType.REFERENCE, FieldType.LOCATION) and \
                   RenderedFieldKey.REFERENCE.value not in field:
                    field = self._expand_reference_field(field[FieldKey.NAME], object_instance, type_instance)
            except Exception as err:
                LOGGER.debug("[_merge_plain_section_fields] field '%s' merge failed: %s", sf_name, err)
                field[FieldKey.VALUE] = None

            fields.append(field)

        return fields


    def _expand_reference_field(
        self,
        field_name: str,
        object_instance: CmdbObject,
        type_instance: CmdbType
    ) -> dict[str, Any]:
        """
        Build the reference/location expansion for a reference- or location-typed field

        Args:
            field_name (str): The name of the reference/location field
            object_instance (CmdbObject): The object providing the referenced id
            type_instance (CmdbType): The object's type, providing the field definition

        Returns:
            dict[str, Any]: The field with its reference expansion (value cleared when unresolvable)
        """
        # copy: get_field returns the live cached dict (see __merge_field_content_section)
        field: dict[str, Any] = dict(type_instance.get_field(field_name))
        reference_id: int = object_instance.get_value(field_name)
        field[FieldKey.VALUE] = reference_id

        if field[FieldKey.TYPE] == FieldType.REFERENCE:
            reference = self._build_reference_expansion(reference_id)

            # Only expand when the referenced object/type resolve (they do not when ref_render is
            # off); preserves the prior value=None otherwise
            if reference is None:
                field[FieldKey.VALUE] = None
            else:
                field[RenderedFieldKey.REFERENCE] = reference

        if field[FieldKey.TYPE] == FieldType.LOCATION:
            field[RenderedFieldKey.REFERENCE] = self._build_location_reference(reference_id)

        return field


    def _report_reference_problem(
        self,
        section: TypeReferenceSection,
        reason: str,
        *reason_args: Any,
    ) -> None:
        """
        Logs, once per render, that a reference section could not be resolved

        These three situations - the referenced Type gone, its section gone, or the section no longer
        carrying any of the referenced fields - all end with the frontend drawing nothing where a
        block belongs. A CmdbType update refuses the edits that cause them, but a database can still
        hold data written without that guard, so the render says so instead of quietly dropping the
        block.

        Deduplicated per reference: a list render walks many objects through the same type
        definition, and one broken reference must not produce one line per object

        Args:
            section (TypeReferenceSection): The reference section that could not be resolved
            reason (str): A %-style message describing what is missing
            *reason_args (Any): Arguments for the reason template
        """
        # Keyed on the reference itself, not just the section: one section repointed at a different
        # target is a different problem and has to be reported on its own
        problem_key: tuple[str, int, str] = (
            section.name,
            getattr(section.reference, 'type_id', 0),
            getattr(section.reference, 'section_name', ''),
        )

        if problem_key in self.reported_reference_problems:
            return

        self.reported_reference_problems.add(problem_key)

        LOGGER.warning(
            "[_merge_reference_section] Reference section '%s' shows nothing: " + reason,
            section.name, *reason_args,
        )


    def _merge_reference_section(
        self,
        section: TypeReferenceSection,
        object_instance: CmdbObject,
        type_instance: CmdbType,
        level: int
    ) -> dict[str, Any] | None:
        # Resolving a reference section threads several intermediate lookups (field, object, type,
        # section, selected fields) through one method; the nested merges are already extracted
        # pylint: disable=too-many-locals
        """
        Merge one reference section into a single reference field for the render

        Resolves the section's implicit reference field, the referenced object (when any) and the
        referenced type/section, then merges each selected referenced field (recursively resolving
        nested ref-section fields). Returns None when the section cannot be rendered (missing field,
        missing referenced type or missing referenced section) so the caller can skip it

        Args:
            section (TypeReferenceSection): The reference section to merge
            object_instance (CmdbObject): The object being rendered
            type_instance (CmdbType): The object's type, providing the reference field definition
            level (int): The reference-resolution depth

        Returns:
            dict[str, Any] | None: The merged reference field, or None when the section is skipped
        """
        try:
            ref_field_name: str = f'{section.name}-field'
            # copy: get_field returns the live cached dict (see __merge_field_content_section)
            ref_field: dict[str, Any] = dict(type_instance.get_field(ref_field_name))
        except CmdbTypeFieldNotFoundError as err:
            LOGGER.debug("[_merge_reference_section] CmdbTypeFieldNotFoundError: %s", err)
            return None

        try:
            reference_id: int = object_instance.get_value(ref_field_name)
            ref_field[FieldKey.VALUE] = reference_id
            reference_object: CmdbObject | None = self.objects_cache.get(reference_id)
        except Exception as err:
            LOGGER.debug("[_merge_reference_section] could not resolve reference object: %s", err)
            reference_object = None

        try:
            ref_type: CmdbType | None = self.types_cache.get(section.reference.type_id)
            if not ref_type:
                self._report_reference_problem(
                    section, "referenced Type ID:%s does not exist", section.reference.type_id,
                )
                return None

            ref_section = ref_type.get_section(section.reference.section_name)
            ref_field[RenderedFieldKey.REFERENCES] = {
                RenderedReferenceSectionKey.TYPE_ID.value: ref_type.public_id,
                RenderedReferenceSectionKey.TYPE_NAME.value: ref_type.name,
                RenderedReferenceSectionKey.TYPE_LABEL.value: ref_type.label,
                RenderedReferenceSectionKey.TYPE_ICON.value: ref_type.get_icon(),
                RenderedReferenceSectionKey.FIELDS.value: [],
            }
        except Exception as err:
            LOGGER.debug("[_merge_reference_section] reference section build failed: %s", err)
            return None

        if not ref_section:
            self._report_reference_problem(
                section, "Type ID:%s has no section '%s' any more",
                section.reference.type_id, section.reference.section_name,
            )
            return None

        # Select the configured fields, else every field of the referenced section - one rule, shared
        # with the update guard that refuses emptying a referenced section. Compute this locally:
        # writing it back onto section.reference would mutate the shared cached type
        selected_ref_fields = section.reference.resolve_pulled_field_names(ref_section.fields)

        if not selected_ref_fields:
            self._report_reference_problem(
                section, "section '%s' of Type ID:%s carries none of the referenced field(s) %s",
                section.reference.section_name, section.reference.type_id,
                sorted(section.reference.selected_fields or []),
            )

        for ref_section_field_name in selected_ref_fields:
            try:
                # copy: get_field returns the live cached dict (see __merge_field_content_section)
                ref_section_field = dict(ref_type.get_field(ref_section_field_name))
                if reference_object:
                    ref_section_field = self.__merge_field_content_section(ref_section_field, reference_object)
                    if level > 0:
                        ref_section_fields = self.__merge_reference_section_fields(ref_section_field, [], level)
                        ref_section_field.get(
                            RenderedFieldKey.REFERENCES,
                            {RenderedReferenceSectionKey.FIELDS.value: []},
                        )[RenderedReferenceSectionKey.FIELDS] = ref_section_fields
            except Exception as err:
                LOGGER.debug("[_merge_reference_section] ref-section field '%s' skipped: %s",
                             ref_section_field_name, err)
                continue
            ref_field[RenderedFieldKey.REFERENCES][RenderedReferenceSectionKey.FIELDS].append(ref_section_field)

        return ref_field


    def get_mds_reference(self, field_value: int) -> dict:
        """
        Generate a reference for the MDS

        Args:
            field_value (int): The field value to generate the reference for

        Returns:
            dict: The generated reference as a dictionary
        """
        return self.__merge_references({FieldKey.VALUE: field_value})
