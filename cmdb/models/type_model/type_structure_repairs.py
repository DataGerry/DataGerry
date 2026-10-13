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
The repair of a CmdbType's references to fields it does not declare - the counterpart of the structure rules

A Type's sections, summary line and external links only NAME its fields. A name whose field is gone renders nothing,
and the structure rules refuse it (``type_structure_rules``). Some of those names are no choice of the request that
carries them, and dropping them is the repair:

* **an update** - a name the stored Type already carried in the same place, or one naming a field the stored Type
  declared and this update removes. The client sent the Type back as it read it, or removed a field without also
  editing every place that named it. A name the update newly writes is still refused
* **an import** - every such name: an upload is an export, and a stale name in it was stored on the system it
  came from

A name that resolves - a declared field, or ``object_id`` in an external link - is always kept, and nothing but
those names is changed. Entries the rules do not read as names (a non-string section entry, a malformed section) are
left for the rules to answer
"""
from typing import Any, Iterator, NamedTuple

from cmdb.models.type_model.section_key_enum import SectionKey
from cmdb.models.type_model.type_constants import (
    EXTERNAL_LINK_NAME_KEY,
    EXTERNAL_LINK_OBJECT_ID,
    LEGACY_EXTERNALS_KEY,
    TypeReferencePlace,
)
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.models.type_model.type_structure_rules import read_type_structure
# -------------------------------------------------------------------------------------------------------------------- #

__all__ = ['DroppedReference', 'drop_unresolvable_references']

# The two lists of a section that name fields: what it shows, and what an MDS section hides
SECTION_REFERENCE_KEYS: tuple[str, ...] = (SectionKey.FIELDS.value, SectionKey.HIDDEN_FIELDS.value)


class DroppedReference(NamedTuple):
    """
    One name the repair dropped

    Attributes:
        place (TypeReferencePlace): Where it was
        owner (Any): The section's or the external link's name; None for the summary
        key (str): The list it was in - a section's `fields` or `hidden_fields`, else `fields`
        name (Any): The dropped name
    """
    place: TypeReferencePlace
    owner: Any
    key: str
    name: Any


class _ReferenceList(NamedTuple):
    """
    One list of field names inside a type document, and where it sits

    Attributes:
        place (TypeReferencePlace): Where the list is
        owner (Any): The section's or the external link's name; None for the summary
        key (str): The key of the list inside its holder
        holder (dict[str, Any]): The dictionary holding the list, so it can be replaced
    """
    place: TypeReferencePlace
    owner: Any
    key: str
    holder: dict[str, Any]

    @property
    def names(self) -> list[Any]:
        """The list itself."""
        return self.holder[self.key]

    @property
    def identity(self) -> tuple[TypeReferencePlace, Any, str]:
        """What matches this list to the same list of another version of the Type."""
        return self.place, self.owner, self.key


def _external_links(render_meta: dict[str, Any]) -> Any:
    """
    The external links the structure rules read - the current key, else the legacy one

    Args:
        render_meta (dict[str, Any]): A type's render_meta

    Returns:
        Any: The links, or whatever the key holds
    """
    return render_meta.get(TypeSchemaKey.EXTERNALS.value) or render_meta.get(LEGACY_EXTERNALS_KEY) or []


def reference_lists(type_entry: Any) -> Iterator[_ReferenceList]:
    """
    Every list of field names in a type document: each section's, the summary's and each external link's

    A list is only yielded when it is one - a malformed holder or value is skipped

    Args:
        type_entry (Any): A type document

    Yields:
        _ReferenceList: Each list with its place
    """
    render_meta: Any = type_entry.get(TypeSchemaKey.RENDER_META.value) if isinstance(type_entry, dict) else None

    if not isinstance(render_meta, dict):
        return

    for section in render_meta.get(TypeSchemaKey.SECTIONS.value) or []:
        if isinstance(section, dict):
            for key in SECTION_REFERENCE_KEYS:
                if isinstance(section.get(key), list):
                    yield _ReferenceList(TypeReferencePlace.SECTION, section.get(SectionKey.NAME.value), key, section)

    summary: Any = render_meta.get(TypeSchemaKey.SUMMARY.value)

    if isinstance(summary, dict) and isinstance(summary.get(TypeSchemaKey.FIELDS.value), list):
        yield _ReferenceList(TypeReferencePlace.SUMMARY, None, TypeSchemaKey.FIELDS.value, summary)

    links: Any = _external_links(render_meta)

    for link in links if isinstance(links, list) else []:
        if isinstance(link, dict) and isinstance(link.get(TypeSchemaKey.FIELDS.value), list):
            yield _ReferenceList(TypeReferencePlace.EXTERNAL, link.get(EXTERNAL_LINK_NAME_KEY),
                                 TypeSchemaKey.FIELDS.value, link)


def resolves(place: TypeReferencePlace, name: Any, declared: set[str]) -> bool:
    """
    Whether a name in a reference list names something the Type offers - read the way the structure rules read it

    A section entry counts only as a string; the summary and the external links compare every entry as text, and an
    external link may also name the object's own ``object_id``

    Args:
        place (TypeReferencePlace): Where the name is
        name (Any): The entry
        declared (set[str]): The names of the fields the Type declares

    Returns:
        bool: True when the entry is no unresolvable name
    """
    if place is TypeReferencePlace.SECTION:
        return not isinstance(name, str) or name in declared

    if place is TypeReferencePlace.EXTERNAL and name == EXTERNAL_LINK_OBJECT_ID:
        return True

    return str(name) in declared


def drop_unresolvable_references(type_entry: Any, stored: dict[str, Any] | None = None) -> list[DroppedReference]:
    """
    Drops, in place, the field names in a type's sections, summary and external links that name no declared field

    With a stored Type (an update) only the names that are no choice of this write are dropped: one the stored Type
    carried in the same list, or one naming a field the stored Type declared. Without one (an import) every
    unresolvable name is dropped

    Args:
        type_entry (Any): The type document, modified in place
        stored (dict[str, Any] | None): The stored Type on an update; None to drop every unresolvable name

    Returns:
        list[DroppedReference]: The names dropped, in document order
    """
    if not isinstance(type_entry, dict):
        return []

    declared: set[str] = read_type_structure(type_entry).known_fields
    stored_declared: set[str] = read_type_structure(stored).known_fields if stored is not None else set()
    stored_lists: dict[tuple[TypeReferencePlace, Any, str], list[Any]] = {
        reference.identity: reference.names for reference in reference_lists(stored)
    }
    dropped: list[DroppedReference] = []

    for reference in reference_lists(type_entry):
        stored_names: list[Any] = stored_lists.get(reference.identity, [])
        kept: list[Any] = []

        for name in reference.names:
            droppable: bool = stored is None or name in stored_names or (
                isinstance(name, str) and name in stored_declared
            )

            if droppable and not resolves(reference.place, name, declared):
                dropped.append(DroppedReference(reference.place, reference.owner, reference.key, name))
            else:
                kept.append(name)

        if len(kept) != len(reference.names):
            reference.holder[reference.key] = kept

    return dropped
