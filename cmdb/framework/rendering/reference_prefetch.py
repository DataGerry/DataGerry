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
Implementation of ReferencePrefetch

Loads, before a render starts, every object it will need to resolve a reference: the rendered objects'
own references and the reference-section chains behind them, one query per hop. Without it each
reference section nested in another fetched its target on its own, which made a list render one query
per object
"""
from logging import ERROR, Logger, getLogger
from typing import Any

from cmdb.manager import ObjectsManager, TypesManager

from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.framework.rendering.render_constants import DEFAULT_RENDER_LEVEL, RenderProblemCode
from cmdb.framework.rendering.render_problem_log import RenderProblemLog

from cmdb.errors.models.cmdb_type import CmdbTypeFieldNotFoundError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                              ReferencePrefetch - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class ReferencePrefetch:
    """
    Loads the objects a render will reference, before it starts

    Attributes:
        objects_manager (ObjectsManager): Loads the referenced objects in bulk
        types_manager (TypesManager): Resolves the kind of a legacy stored field that carries no 'type'
        objects_cache (dict[int, CmdbObject]): The render's cache; what is in it is not loaded again
        problems (RenderProblemLog): Where a failed load and a stored field the type dropped are reported
    """

    def __init__(
        self,
        objects_manager: ObjectsManager,
        types_manager: TypesManager,
        objects_cache: dict[int, CmdbObject],
        problems: RenderProblemLog,
    ) -> None:
        """
        Initialises a ReferencePrefetch for one render

        Args:
            objects_manager (ObjectsManager): Loads the referenced objects in bulk
            types_manager (TypesManager): Resolves the kind of a legacy untyped stored field
            objects_cache (dict[int, CmdbObject]): The render's cache, read and never written here
            problems (RenderProblemLog): The render's problem log
        """
        self.objects_manager: ObjectsManager = objects_manager
        self.types_manager: TypesManager = types_manager
        self.objects_cache: dict[int, CmdbObject] = objects_cache
        self.problems: RenderProblemLog = problems

        # Legacy fields missing a 'type' key: each object's type is fetched at most once, keyed by
        # type_id, instead of being re-queried for every untyped field (an N+1 otherwise)
        self.fallback_types: dict[int, CmdbType | None] = {}


    def load(self, to_render_objects: list[CmdbObject]) -> dict[int, CmdbObject]:
        """
        Loads everything the given objects reference, directly or through reference-section chains

        A load that fails is reported on every object that references anything: the render continues
        without the expansions, and each of those objects says so

        Args:
            to_render_objects (list[CmdbObject]): The objects about to be rendered

        Returns:
            dict[int, CmdbObject]: The objects loaded, keyed by public_id - none already cached
        """
        references_by_object: dict[int, set[int]] = {}
        section_targets: set[int] = set()

        for obj in to_render_objects:
            object_references, object_section_targets = self._collect_reference_ids(obj)
            references_by_object[obj.public_id] = object_references
            section_targets |= object_section_targets

        reference_ids: set[int] = set().union(*references_by_object.values()) - set(self.objects_cache)

        if not reference_ids:
            return {}

        try:
            return self._load_chains(reference_ids, section_targets)
        except Exception as err:
            self.problems.report(
                RenderProblemCode.REFERENCES_UNAVAILABLE,
                "[ReferencePrefetch] The referenced objects could not be loaded, rendering without their "
                "expansions: %s. Type: %s",
                err, type(err).__name__,
                object_ids=[object_id for object_id, ids in references_by_object.items() if ids],
                log_level=ERROR,
            )
            return {}


    def _load_chains(
        self,
        reference_ids: set[int],
        section_targets: set[int],
    ) -> dict[int, CmdbObject]:
        """
        Loads the referenced objects, then follows the reference-section chains one query per hop

        A reference-section chain alternates between two roles, and each needs different ids:

        * a **section target** - what a rendered object's ref-section field points at - is only MERGED
          into the section: its values are read, and only its own ref-section fields lead on, to
          objects rendered NESTED. Its plain references are not resolved by the render, so they are
          not loaded here either - loading them would change what the section shows
        * a **nested target** is rendered by a render of its own, which loads every object it
          references. Loading them here instead, all nested targets of a hop in one query, is what the
          prefetch is for; its ref-section targets are section targets again

        The walk ends after ``DEFAULT_RENDER_LEVEL`` hops, when a hop turns up nothing new, or at an id
        already known - which is also what ends a reference cycle

        Args:
            reference_ids (set[int]): The uncached ids the rendered objects reference
            section_targets (set[int]): Those of them a ref-section field points at

        Returns:
            dict[int, CmdbObject]: Every object loaded, keyed by public_id
        """
        loaded: dict[int, CmdbObject] = {}
        pending: set[int] = reference_ids
        nested_targets: set[int] = set()

        for _ in range(DEFAULT_RENDER_LEVEL):
            if not pending:
                break

            loaded.update(self.objects_manager.get_objects_lookup(list(pending)))

            next_pending: set[int] = set()
            next_section_targets: set[int] = set()
            next_nested_targets: set[int] = set()

            for target in self._known_objects(section_targets, loaded):
                next_nested_targets |= self._collect_reference_ids(target)[1]

            for target in self._known_objects(nested_targets, loaded):
                target_references, target_section_targets = self._collect_reference_ids(target)
                next_pending |= target_references
                next_section_targets |= target_section_targets

            pending = (next_pending | next_nested_targets) - set(loaded) - set(self.objects_cache)
            section_targets, nested_targets = next_section_targets, next_nested_targets

        return loaded


    def _known_objects(self, public_ids: set[int], loaded: dict[int, CmdbObject]) -> list[CmdbObject]:
        """
        Answers the objects among the given ids that are loaded or already cached

        Args:
            public_ids (set[int]): The ids to look up
            loaded (dict[int, CmdbObject]): The objects the current prefetch has loaded so far

        Returns:
            list[CmdbObject]: The known objects; an id neither loaded nor cached is skipped
        """
        known: list[CmdbObject] = []

        for public_id in public_ids:
            target: CmdbObject | None = loaded.get(public_id) or self.objects_cache.get(public_id)

            if target is not None:
                known.append(target)

        return known


    def _collect_reference_ids(self, obj: CmdbObject) -> tuple[set[int], set[int]]:
        """
        Collects the ids an object's reference and ref-section fields point at

        Args:
            obj (CmdbObject): The object whose fields are read

        Returns:
            tuple[set[int], set[int]]: (every referenced id, the ids its ref-section fields point at)
        """
        reference_ids: set[int] = set()
        section_target_ids: set[int] = set()

        for field in obj.fields:
            field_type: str | None = field.get(FieldKey.TYPE) or self._resolve_untyped_field_type(obj, field)

            if field_type not in (FieldType.REFERENCE, FieldType.REF_SECTION) or not field.get(FieldKey.VALUE):
                continue

            reference_ids.add(int(field[FieldKey.VALUE]))

            if field_type == FieldType.REF_SECTION:
                section_target_ids.add(int(field[FieldKey.VALUE]))

        return reference_ids, section_target_ids


    def _resolve_untyped_field_type(self, obj: CmdbObject, field: dict[str, Any]) -> str | None:
        """
        Looks up the kind of a stored field that carries no 'type' key, from the object's type

        A legacy object may store a field its type no longer declares. Such a value is never rendered
        anyway - a render draws the fields the TYPE declares - so the field is only skipped here and
        logged, rather than taking the whole render down with it

        Args:
            obj (CmdbObject): The object the field belongs to
            field (dict[str, Any]): The stored field entry without a 'type' key

        Returns:
            str | None: The field's kind, or None when it cannot be determined
        """
        field_name: Any = field.get(FieldKey.NAME)
        LOGGER.debug("Field-Type in Object: %s not found for field name: %s !", obj.public_id, field_name)

        type_id: int = obj.get_type_id()

        if type_id not in self.fallback_types:
            self.fallback_types[type_id] = self.types_manager.get_type_instance(type_id)

        type_instance: CmdbType | None = self.fallback_types[type_id]

        if not type_instance:
            LOGGER.debug("Type of Object: %s not found!", obj.public_id)
            return None

        try:
            return type_instance.get_field(field_name).get(FieldKey.TYPE)
        except CmdbTypeFieldNotFoundError:
            # Logged, not flagged: nothing the render answers is missing, because the value was never
            # going to be drawn. The object is just carrying data its type has dropped
            self.problems.report(
                RenderProblemCode.FIELD_NOT_ON_TYPE,
                "[ReferencePrefetch] Object ID:%s stores field '%s', which Type ID:%s does not declare; "
                "its value is not rendered",
                obj.public_id, field_name, type_id,
                field=field_name, object_ids=(), log_key=(type_id,),
            )
            return None
