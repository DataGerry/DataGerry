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
Implementation of DocumentReferenceResolver

A DocAPI document follows reference fields up to `DEFAULT_REFERENCE_DEPTH` hops from every object it renders. Done
one reference at a time, that is one object read and one render (with its own prefetch) per resolved reference, and
the references fan out: N reference fields per object are N + N**2 + N**3 resolutions. This resolver serves one
document and does it one LEVEL at a time instead: all objects one hop away are rendered in a single
`CmdbMultiRender`, whose prefetch already loads the next hop. An object is taken from the prefetch caches when they
hold it; the ones they do not (a plain reference inside a reference section's object) are loaded in one query per
level - through the caller's READ ACL, the same rule the prefetch applies. What a document extracts per object and
depth is remembered, so a reference reached twice - or an `object(id)` the root already reached - costs nothing more

The extracted data is shared between the places that reach it. The template engine's sandbox does not freeze it, so a
template that changes one value sees the change everywhere in its own document - it is the template's own document
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.manager import LocationsManager, ObjectsManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.object_model import CmdbObject
from cmdb.models.user_model import CmdbUser
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.type_constants import DG_LOCATION_FIELD_NAME
from cmdb.models.docapi_model.docapi_reference_constants import LOCATION_NAME_KEY
from cmdb.framework.rendering.cmdb_multi_render import CmdbMultiRender
from cmdb.framework.rendering.render_constants import RenderedFieldKey, RenderObjectInfoKey
from cmdb.framework.rendering.render_result import RenderResult
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.utils import Builder

from cmdb.errors.manager.objects_manager import ObjectsManagerGetError
from cmdb.errors.manager.locations_manager import LocationsManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

#: What a document's extraction is remembered under: the object, the hops left, and the template mode
ExtractionKey = tuple[int, int, bool]

def is_location_field(name: Any, field_type: Any) -> bool:
    """
    Whether a field holds a CmdbLocation id rather than an object's - such a field is never followed as a reference

    Args:
        name (Any): The field's name
        field_type (Any): The field's type (a `FieldType` value)

    Returns:
        bool: True for a LOCATION field, whatever its name, and for the reserved location field name
    """
    return field_type == FieldType.LOCATION or name == DG_LOCATION_FIELD_NAME


def followed_reference_id(field: dict[str, Any]) -> int | None:
    """
    The object id a rendered field leads to, when a document follows it

    Args:
        field (dict[str, Any]): A rendered field

    Returns:
        int | None: The referenced public_id of a set REFERENCE field; None for anything else
    """
    value: Any = field.get(FieldKey.VALUE.value)
    field_type: Any = field.get(FieldKey.TYPE.value)

    if is_location_field(field.get(FieldKey.NAME.value), field_type) or field_type != FieldType.REFERENCE:
        return None

    if isinstance(value, bool) or not isinstance(value, int) or not value:
        return None

    return value


def collect_reference_ids(fields: list[dict[str, Any]], modern: bool) -> set[int]:
    """
    Every object id a render's fields lead a document to, one hop away

    Mirrors `ObjectTemplateData`'s dispatch: a REFERENCE field is followed; a DEFAULT template also resolves the
    fields of a reference section, and a reference among them is followed at the same hop. A miss here is not wrong,
    only slower - the resolver still renders a reference it was not told about, on its own

    Args:
        fields (list[dict[str, Any]]): A RenderResult's fields, or a reference section's
        modern (bool): Whether the document's template is a DEFAULT one

    Returns:
        set[int]: The referenced public_ids
    """
    referenced: set[int] = set()

    for field in fields or []:
        reference_id: int | None = followed_reference_id(field)

        if reference_id is not None:
            referenced.add(reference_id)
        elif modern and field.get(FieldKey.TYPE.value) == FieldType.REF_SECTION:
            section: dict[str, Any] = field.get(RenderedFieldKey.REFERENCES.value) or {}
            referenced |= collect_reference_ids(section.get(RenderedFieldKey.FIELDS.value, []), modern)

    return referenced


# -------------------------------------------------------------------------------------------------------------------- #
#                                          DocumentReferenceResolver - CLASS                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class DocumentReferenceResolver:
    """
    The objects one DocAPI document reaches through references, rendered once and one level at a time

    Attributes:
        request_user (CmdbUser | None): The user the document is rendered for - every object is read through their
            READ ACL
        objects (dict[int, CmdbObject]): The readable objects known so far, from the renders' prefetch caches and
            the level loads
        renders (dict[int, RenderResult]): Every object rendered for the document, by public_id
        unresolvable (set[int]): Ids that were asked for and are unreadable, missing or of a missing type - not
            asked for again
        extracted (dict[ExtractionKey, dict[str, Any]]): What `ObjectTemplateData` extracted per object, hops
            left and template mode
        location_names (dict[Any, str]): The location names a document's location fields resolved to
    """
    def __init__(self, request_user: CmdbUser | None, objects_manager: ObjectsManager) -> None:
        """
        Initialises the resolver of one document

        Args:
            request_user (CmdbUser | None): The user the document is rendered for
            objects_manager (ObjectsManager): Reads the objects the prefetch caches do not hold
        """
        self.request_user: CmdbUser | None = request_user
        self.objects_manager: ObjectsManager = objects_manager
        self.locations_manager: LocationsManager | None = None

        self.objects: dict[int, CmdbObject] = {}
        self.renders: dict[int, RenderResult] = {}
        self.unresolvable: set[int] = set()
        self.extracted: dict[ExtractionKey, dict[str, Any]] = {}
        self.location_names: dict[Any, str] = {}


    def adopt(self, renderer: CmdbMultiRender) -> None:
        """
        Takes what a render loaded: the objects its prefetch read, and the ids its prefetch asked for and did not get

        Args:
            renderer (CmdbMultiRender): A render performed for this document's user
        """
        self.objects.update(renderer.objects_cache)
        self.unresolvable |= set(renderer.read_scope.unreturned_ids) - set(self.objects)


    def render_objects(self, objects: list[CmdbObject]) -> list[RenderResult]:
        """
        Renders the given objects that are not rendered yet, in one pass, and answers all of them in order

        Args:
            objects (list[CmdbObject]): Objects the caller may read

        Returns:
            list[RenderResult]: The render of each object that has one, in the given order - an object of a missing
                type has none
        """
        pending: list[CmdbObject] = [obj for obj in objects if obj.public_id not in self.renders]

        if pending:
            renderer: CmdbMultiRender = CmdbMultiRender(pending, self.request_user, ref_render=True)

            for result in renderer.result():
                self.renders[result.object_information[RenderObjectInfoKey.OBJECT_ID.value]] = result

            self.adopt(renderer)
            self.unresolvable |= {obj.public_id for obj in pending} - set(self.renders)

        return [self.renders[obj.public_id] for obj in objects if obj.public_id in self.renders]


    def prepare(self, renders: list[RenderResult], depth: int, modern: bool) -> None:
        """
        Renders, level by level, everything the given renders reach within `depth` hops

        Args:
            renders (list[RenderResult]): The renders the document starts from at this point
            depth (int): The hops to follow
            modern (bool): Whether the document's template is a DEFAULT one
        """
        level: list[RenderResult] = renders

        for _ in range(depth):
            reached: set[int] = set()

            for render in level:
                reached |= collect_reference_ids(render.fields, modern)

            pending: set[int] = reached - set(self.renders) - self.unresolvable

            if not pending:
                return

            level = self.render_objects(self._readable_objects(pending))


    def render_for(self, public_id: int) -> RenderResult | None:
        """
        The render of a referenced object - prepared by a level, or rendered now when no level reached it

        Args:
            public_id (int): The referenced object's public_id

        Returns:
            RenderResult | None: Its render; None when it is unreadable, missing or of a missing type
        """
        if public_id in self.renders:
            return self.renders[public_id]

        if public_id in self.unresolvable:
            return None

        LOGGER.debug("[docapi] Reference '%s' was not prepared by a level - rendered on its own", public_id)
        self.render_objects(self._readable_objects({public_id}))

        return self.renders.get(public_id)


    def location_name(self, location_id: Any) -> str:
        """
        The name a location field resolves to, read once per document

        Args:
            location_id (Any): The stored location public_id (falsy when unset)

        Returns:
            str: The location's name; an empty string when unset or not resolvable
        """
        if not location_id:
            return ""

        if location_id not in self.location_names:
            self.location_names[location_id] = self._read_location_name(location_id)

        return self.location_names[location_id]


    def _read_location_name(self, location_id: Any) -> str:
        """
        Reads one location's name

        Args:
            location_id (Any): The location's public_id

        Returns:
            str: The location's name; an empty string when it cannot be read
        """
        if self.locations_manager is None:
            self.locations_manager = ManagerProvider.get_manager(ManagerType.LOCATIONS, self.request_user)

        try:
            location: dict[str, Any] | None = self.locations_manager.get_location(location_id)
        except LocationsManagerGetError:
            LOGGER.error("Failed to resolve location '%s'", location_id)
            return ""

        return location.get(LOCATION_NAME_KEY) if location else ""


    def _readable_objects(self, public_ids: set[int]) -> list[CmdbObject]:
        """
        The objects of the given ids the caller may read - from what is known, the rest loaded in one query

        Args:
            public_ids (set[int]): Ids not rendered yet and not known to be unresolvable

        Returns:
            list[CmdbObject]: The readable ones, in id order
        """
        missing: set[int] = public_ids - set(self.objects)

        if missing:
            self._load(missing)

        return [self.objects[public_id] for public_id in sorted(public_ids) if public_id in self.objects]


    def _load(self, public_ids: set[int]) -> None:
        """
        Loads objects through the caller's READ ACL; an id that does not come back is unresolvable

        Args:
            public_ids (set[int]): The ids to load
        """
        try:
            loaded: list[CmdbObject] = self.objects_manager.get_objects_by(
                user=self.request_user,
                permission=AccessControlPermission.READ,
                criteria=Builder.in_(CmdbObjectKey.PUBLIC_ID.value, sorted(public_ids)),
            )
        except ObjectsManagerGetError:
            LOGGER.error("Failed to resolve reference objects %s", sorted(public_ids))
            loaded = []

        for obj in loaded:
            self.objects[obj.public_id] = obj

        self.unresolvable |= public_ids - set(self.objects)
