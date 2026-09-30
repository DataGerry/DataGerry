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
Reference-section dependencies between CmdbTypes

A ref-section stores `{type_id, section_name, selected_fields}` and resolves its target **by name at
render time**, so nothing in the database ties the two types together: removing the referenced section,
renaming it, or removing the fields a dependent pulls all leave that dependent silently showing
nothing. These helpers are what makes that visible - who depends on a section, what an edit would break,
the refusal a write path raises, and the pre-check payload the type builder reads so the UI can disable
the action instead of explaining a 400 afterwards.

Split out of `types_helper.py`: the cluster is one self-contained theme and that module had
grown past pylint's 1,500-line cap. Nothing else moved with it, so the guards a route calls
(`guard_referenced_section_removal`, `referenced_section_field_removal_blocker`) are imported from here
while every other type guard stays in `types_helper`
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import TypesManager

from cmdb.models.type_model.cmdb_type import CmdbType
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.models.type_model.section_key_enum import SectionKey
from cmdb.models.type_model.section_type_enum import SectionType
from cmdb.models.type_model.section_reference_key_enum import SectionReferenceKey
from cmdb.models.type_model.type_reference_section import TypeReferenceSection
from cmdb.models.type_model.type_reference_section_entry import resolve_pulled_field_names
from cmdb.models.user_model.cmdb_user import CmdbUser
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_constants import (
    REFERENCED_SECTION_REMOVAL_MESSAGE,
    REFERENCED_SECTION_DEPENDENT_FORMAT,
    REFERENCED_SECTION_DEPENDENT_TYPE_FORMAT,
    REFERENCED_SECTION_EMPTIED_MESSAGE,
    REFERENCED_SECTION_EMPTIED_DETAIL_FORMAT,
    ReferencedSectionUsageKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

def get_types_referencing_section(
    request_user: CmdbUser,
    referenced_type_id: int,
    section_name: str | None = None,
    exclude_type_id: int | None = None,
) -> list[dict[str, Any]]:
    """
    Returns the CmdbTypes whose reference section pulls fields from the given Type (and section)

    A ref-section stores `{type_id, section_name, selected_fields}` and resolves the section by NAME
    at render time, so removing that section - or renaming it, which is a removal plus an addition -
    leaves the dependent type pointing at nothing: `_merge_reference_section` finds no section and
    drops the whole reference field, silently.

    The section list is matched with `$elemMatch` rather than two dotted paths, because dotted paths
    are satisfied by DIFFERENT array elements: a type with any ref-section plus an unrelated section
    naming this type_id would match, and be refused for a dependency it does not have

    Args:
        request_user (CmdbUser): User performing the request
        referenced_type_id (int): public_id of the CmdbType being referenced
        section_name (str | None): Name of the referenced section; None matches a reference to the
            type regardless of which of its sections is pulled. Defaults to None
        exclude_type_id (int | None): public_id of a CmdbType to leave out of the result - used to
            skip the type being written, whose own sections come from the payload rather than the
            database. Defaults to None

    Returns:
        list[dict[str, Any]]: The dependent types as {public_id, name, label} dicts, empty when none
    """
    return _find_referencing_types(
        request_user,
        referenced_type_id,
        section_name,
        exclude_type_id,
        # Only the identity of the dependents is reported, so whole type documents are never loaded.
        # '_id' is excluded explicitly: dbm.find only drops it when NO projection is passed, and these
        # dicts go straight into a REST response, where an ObjectId is not serialisable
        projection={
            '_id': 0,
            TypeSchemaKey.PUBLIC_ID.value: 1,
            TypeSchemaKey.NAME.value: 1,
            TypeSchemaKey.LABEL.value: 1,
        },
    )


def _find_referencing_types(
    request_user: CmdbUser,
    referenced_type_id: int,
    section_name: str | None,
    exclude_type_id: int | None,
    projection: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Runs the ref-section dependency query with the caller's projection

    Args:
        request_user (CmdbUser): User performing the request
        referenced_type_id (int): public_id of the CmdbType being referenced
        section_name (str | None): Name of the referenced section, None to match any
        exclude_type_id (int | None): public_id of a CmdbType to leave out of the result
        projection (dict[str, Any]): The MongoDB projection to read the dependents with

    Returns:
        list[dict[str, Any]]: The matching type documents, projected
    """
    types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

    reference_key: str = SectionKey.REFERENCE.value
    element_match: dict[str, Any] = {
        SectionKey.TYPE.value: SectionType.REF_SECTION.value,
        f'{reference_key}.{SectionReferenceKey.TYPE_ID.value}': referenced_type_id,
    }

    if section_name is not None:
        element_match[f'{reference_key}.{SectionReferenceKey.SECTION_NAME.value}'] = section_name

    criteria: dict[str, Any] = {
        f'{TypeSchemaKey.RENDER_META.value}.{TypeSchemaKey.SECTIONS.value}': {'$elemMatch': element_match},
    }

    if exclude_type_id is not None:
        criteria[TypeSchemaKey.PUBLIC_ID.value] = {'$ne': exclude_type_id}

    return types_manager.find(criteria=criteria, projection=projection)


def get_removed_section_names(old_type: CmdbType, new_type: CmdbType) -> set[str]:
    """
    Returns the names of the sections an update would remove from a CmdbType

    A rename shows up here as a removal, which is correct: a ref-section resolves its target by name,
    so renaming the target breaks it exactly as deleting it does

    Args:
        old_type (CmdbType): State of the CmdbType before the update
        new_type (CmdbType): State of the CmdbType the update would persist

    Returns:
        set[str]: The removed section names, empty when the update removes none
    """
    old_names: set[str] = {section.name for section in old_type.get_sections()}
    new_names: set[str] = {section.name for section in new_type.get_sections()}

    return old_names - new_names


def get_own_section_references(type_instance: CmdbType, referenced_type_id: int) -> list[dict[str, Any]]:
    """
    Returns the reference sections of one Type that point at another Type's sections

    Needed for the self-referencing case: a CmdbType may hold a ref-section aimed at its own
    sections. That dependency cannot be read from the database during an update, because the type's
    sections are exactly what the payload is replacing - it has to be read from the payload

    Args:
        type_instance (CmdbType): The CmdbType whose reference sections are inspected
        referenced_type_id (int): public_id of the referenced CmdbType

    Returns:
        list[dict[str, Any]]: One {section_name, selected_fields} entry per matching reference section
    """
    return [
        {
            SectionReferenceKey.SECTION_NAME.value: section.reference.section_name,
            SectionReferenceKey.SELECTED_FIELDS.value: getattr(section.reference, 'selected_fields', None) or [],
        }
        for section in type_instance.get_sections()
        if isinstance(section, TypeReferenceSection)
        and getattr(section.reference, 'type_id', None) == referenced_type_id
        and getattr(section.reference, 'section_name', None)
    ]


def get_own_referenced_section_names(type_instance: CmdbType, referenced_type_id: int) -> set[str]:
    """
    Returns the section names of one Type that another Type's OWN reference sections point at

    Args:
        type_instance (CmdbType): The CmdbType whose reference sections are inspected
        referenced_type_id (int): public_id of the referenced CmdbType

    Returns:
        set[str]: The referenced section names, empty when none point at that type
    """
    return {
        reference[SectionReferenceKey.SECTION_NAME.value]
        for reference in get_own_section_references(type_instance, referenced_type_id)
    }


def describe_section_dependents(dependents: list[dict[str, Any]]) -> str:
    """
    Renders the dependent CmdbTypes of one section for a refusal message

    Args:
        dependents (list[dict[str, Any]]): The dependent types as {public_id, name, label} dicts

    Returns:
        str: The dependents as a comma separated "'label' (ID:n)" list
    """
    return ', '.join(
        REFERENCED_SECTION_DEPENDENT_TYPE_FORMAT.format(
            label=dependent.get(TypeSchemaKey.LABEL.value) or dependent.get(TypeSchemaKey.NAME.value),
            public_id=dependent.get(TypeSchemaKey.PUBLIC_ID.value),
        )
        for dependent in dependents
    )


def get_section_reference_selections(
    request_user: CmdbUser,
    referenced_type_id: int,
    section_name: str,
    exclude_type_id: int | None = None,
) -> list[dict[str, Any]]:
    """
    Returns each dependent of one referenced section together with the fields it pulls

    Same query as `get_types_referencing_section`, but it also reads the dependents' reference entries,
    because deciding whether an edit would leave a dependent with nothing to show needs its selection.
    A dependent holding two reference sections aimed at the same section yields one entry per section

    Args:
        request_user (CmdbUser): User performing the request
        referenced_type_id (int): public_id of the CmdbType being referenced
        section_name (str): Name of the referenced section
        exclude_type_id (int | None): public_id of a CmdbType to leave out. Defaults to None

    Returns:
        list[dict[str, Any]]: One {public_id, name, label, selected_fields} entry per reference
    """
    sections_path: str = f'{TypeSchemaKey.RENDER_META.value}.{TypeSchemaKey.SECTIONS.value}'

    dependents: list[dict[str, Any]] = _find_referencing_types(
        request_user,
        referenced_type_id,
        section_name,
        exclude_type_id,
        projection={
            '_id': 0,
            TypeSchemaKey.PUBLIC_ID.value: 1,
            TypeSchemaKey.NAME.value: 1,
            TypeSchemaKey.LABEL.value: 1,
            sections_path: 1,
        },
    )

    selections: list[dict[str, Any]] = []

    for dependent in dependents:
        render_meta: dict[str, Any] = dependent.get(TypeSchemaKey.RENDER_META.value) or {}

        for section in render_meta.get(TypeSchemaKey.SECTIONS.value) or []:
            reference: dict[str, Any] = section.get(SectionKey.REFERENCE.value) or {}

            # The query matched the DOCUMENT; which of its sections matched has to be re-established
            # here, because the projection returns the whole sections list
            if (section.get(SectionKey.TYPE.value) == SectionType.REF_SECTION.value
                    and reference.get(SectionReferenceKey.TYPE_ID.value) == referenced_type_id
                    and reference.get(SectionReferenceKey.SECTION_NAME.value) == section_name):
                selections.append({
                    TypeSchemaKey.PUBLIC_ID.value: dependent.get(TypeSchemaKey.PUBLIC_ID.value),
                    TypeSchemaKey.NAME.value: dependent.get(TypeSchemaKey.NAME.value),
                    TypeSchemaKey.LABEL.value: dependent.get(TypeSchemaKey.LABEL.value),
                    SectionReferenceKey.SELECTED_FIELDS.value:
                        reference.get(SectionReferenceKey.SELECTED_FIELDS.value) or [],
                })

    return selections


def get_section_field_names(type_instance: CmdbType) -> dict[str, list[str]]:
    """
    Returns the field names of every section of a CmdbType, keyed by section name

    Args:
        type_instance (CmdbType): The CmdbType to read

    Returns:
        dict[str, list[str]]: Section name mapped to its field names, in the section's own order
    """
    return {
        section.name: list(getattr(section, 'fields', None) or [])
        for section in type_instance.get_sections()
    }


def referenced_section_field_removal_blocker(
    request_user: CmdbUser,
    old_type: CmdbType,
    new_type: CmdbType,
) -> str | None:
    """
    Reports why an update may not leave a referenced section with nothing to show, if it may not

    The field-side half of the reference guard. A ref-section keeps working while at least one field
    it pulls is still in the referenced section: losing the column of a field that was just deleted is
    the direct consequence of deleting it, and moving fields between sections has to stay possible. But
    once the LAST pulled field leaves, the dependent renders an empty block - the same blank area a
    deleted section produces, reached from the field side. That is what this refuses.

    The trigger is a field leaving the SECTION, not the type: moving a field to a sibling section
    breaks a dependent identically. A section that already showed nothing is not protected, so an
    already-broken configuration cannot block unrelated edits.

    The reason is returned instead of raised so both write paths can use it: the route aborts with it
    (`guard_referenced_section_removal`), the type import reports it per entry

    Args:
        request_user (CmdbUser): User performing the request
        old_type (CmdbType): State of the CmdbType before the update
        new_type (CmdbType): State of the CmdbType the update would persist

    Returns:
        str | None: The reason the update is refused, or None when it is allowed
    """
    old_section_fields: dict[str, list[str]] = get_section_field_names(old_type)
    new_section_fields: dict[str, list[str]] = get_section_field_names(new_type)
    type_id: int = old_type.get_public_id()
    blocked: list[str] = []

    for section_name, old_field_names in old_section_fields.items():
        # A removed section is the other blocker's business; an unchanged one costs no lookup
        if section_name not in new_section_fields:
            continue

        new_field_names: list[str] = new_section_fields[section_name]

        if new_field_names == old_field_names:
            continue

        emptied: list[dict[str, Any]] = [
            selection for selection in _selections_of_section(request_user, new_type, type_id, section_name)
            if _reference_would_be_emptied(selection, old_field_names, new_field_names)
        ]

        if emptied:
            blocked.append(REFERENCED_SECTION_EMPTIED_DETAIL_FORMAT.format(
                section_name=section_name,
                dependents=describe_section_dependents(emptied),
            ))

    if not blocked:
        return None

    return REFERENCED_SECTION_EMPTIED_MESSAGE.format(details='; '.join(blocked))


def _selections_of_section(
    request_user: CmdbUser,
    new_type: CmdbType,
    type_id: int,
    section_name: str,
) -> list[dict[str, Any]]:
    """
    Returns every reference aimed at one section: the other Types' and the Type's own

    The stored copy of the type being written is excluded from the query and its own references are
    read from the payload instead, for the same reason as in the section-removal blocker: during its
    own update, what the database holds about its sections is already stale

    Args:
        request_user (CmdbUser): User performing the request
        new_type (CmdbType): State of the CmdbType the update would persist
        type_id (int): public_id of the CmdbType being written
        section_name (str): Name of the referenced section

    Returns:
        list[dict[str, Any]]: One {public_id, name, label, selected_fields} entry per reference
    """
    selections: list[dict[str, Any]] = get_section_reference_selections(
        request_user, type_id, section_name, exclude_type_id=type_id,
    )

    for own_reference in get_own_section_references(new_type, type_id):
        if own_reference[SectionReferenceKey.SECTION_NAME.value] == section_name:
            selections.append({
                TypeSchemaKey.PUBLIC_ID.value: type_id,
                TypeSchemaKey.NAME.value: new_type.name,
                TypeSchemaKey.LABEL.value: new_type.label,
                SectionReferenceKey.SELECTED_FIELDS.value:
                    own_reference[SectionReferenceKey.SELECTED_FIELDS.value],
            })

    return selections


def _reference_would_be_emptied(
    selection: dict[str, Any],
    old_field_names: list[str],
    new_field_names: list[str],
) -> bool:
    """
    Reports whether an update takes the last field a single reference section shows

    Both sides are resolved through the model's own selection rule, so this cannot disagree with what
    the renderer displays - including the case that makes a plain intersection wrong, an EMPTY
    selection meaning "every field of the section"

    Args:
        selection (dict[str, Any]): One reference's {..., selected_fields} entry
        old_field_names (list[str]): Field names the section carried before the update
        new_field_names (list[str]): Field names the section would carry after it

    Returns:
        bool: True when the reference showed something before and would show nothing after
    """
    selected_fields: list[str] = selection.get(SectionReferenceKey.SELECTED_FIELDS.value) or []

    shown_before: list[str] = resolve_pulled_field_names(selected_fields, old_field_names)
    shown_after: list[str] = resolve_pulled_field_names(selected_fields, new_field_names)

    return bool(shown_before) and not shown_after


def referenced_section_removal_blocker(
    request_user: CmdbUser,
    old_type: CmdbType,
    new_type: CmdbType,
) -> str | None:
    """
    Reports why an update may not remove a section another CmdbType references, if it may not

    A section may only be removed once no other CmdbType pulls its fields through a ref-section,
    otherwise that reference is left dangling and the dependent type's object view loses the whole
    referenced block without a word. An update that removes the section AND the ref-section pointing
    at it in the same payload is allowed - the self-reference is therefore judged against the NEW
    type, and the stored copy of the type being written is excluded from the database lookup.

    The reason is returned instead of raised so both write paths can use it: the route aborts with it
    (`guard_referenced_section_removal`), the type import reports it per entry

    Args:
        request_user (CmdbUser): User performing the request
        old_type (CmdbType): State of the CmdbType before the update
        new_type (CmdbType): State of the CmdbType the update would persist

    Returns:
        str | None: The reason the removal is refused, or None when the update is allowed
    """
    removed_sections: set[str] = get_removed_section_names(old_type, new_type)

    if not removed_sections:
        return None

    type_id: int = old_type.get_public_id()
    self_referenced: set[str] = get_own_referenced_section_names(new_type, type_id)
    blocked: list[str] = []

    for section_name in sorted(removed_sections):
        dependents: list[dict[str, Any]] = get_types_referencing_section(
            request_user, type_id, section_name, exclude_type_id=type_id,
        )

        if section_name in self_referenced:
            dependents = dependents + [{
                TypeSchemaKey.PUBLIC_ID.value: type_id,
                TypeSchemaKey.NAME.value: new_type.name,
                TypeSchemaKey.LABEL.value: new_type.label,
            }]

        if dependents:
            blocked.append(REFERENCED_SECTION_DEPENDENT_FORMAT.format(
                section_name=section_name,
                dependents=describe_section_dependents(dependents),
            ))

    if not blocked:
        return None

    return REFERENCED_SECTION_REMOVAL_MESSAGE.format(details='; '.join(blocked))


def guard_referenced_section_removal(request_user: CmdbUser, old_type: CmdbType, new_type: CmdbType) -> None:
    """
    Aborts 400 when an update breaks a section another CmdbType references in a ref-section

    The route-level wrapper around both halves of the rule: `referenced_section_removal_blocker`
    (the section itself is gone or renamed) and `referenced_section_field_removal_blocker` (the
    section survives but no longer carries any field the dependent shows)

    Args:
        request_user (CmdbUser): User performing the request
        old_type (CmdbType): State of the CmdbType before the update
        new_type (CmdbType): State of the CmdbType the update would persist

    Raises:
        HTTPException: 400 when the section may not be removed
    """
    blocker: str | None = (
        referenced_section_removal_blocker(request_user, old_type, new_type)
        or referenced_section_field_removal_blocker(request_user, old_type, new_type)
    )

    if blocker:
        abort(400, blocker)


def _group_dependents_by_section(
    dependents: list[dict[str, Any]],
    referenced_type_id: int,
) -> dict[str, list[dict[str, Any]]]:
    """
    Groups the dependents of a CmdbType by the section each of them pulls

    Built from ONE already-loaded result rather than by asking the database once per section: every
    dependent's own reference entries name the section they target, so the per-section map is a
    regrouping of what the single query returned. Asked per section, a type with twenty would cost twenty-one
    queries on every type-builder page load.

    A dependent is listed under a section name it names even if this type has no such section - the
    caller reports that as "referenced, but under no section", which is the state left by data written
    before the guard existed

    Args:
        dependents (list[dict[str, Any]]): The referencing types, projected WITH their sections
        referenced_type_id (int): public_id of the CmdbType being referenced

    Returns:
        dict[str, list[dict[str, Any]]]: {section name: [{public_id, name, label}, ...]}
    """
    sections: dict[str, list[dict[str, Any]]] = {}

    for dependent in dependents:
        render_meta: dict[str, Any] = dependent.get(TypeSchemaKey.RENDER_META.value) or {}
        identity: dict[str, Any] = {
            TypeSchemaKey.PUBLIC_ID.value: dependent.get(TypeSchemaKey.PUBLIC_ID.value),
            TypeSchemaKey.NAME.value: dependent.get(TypeSchemaKey.NAME.value),
            TypeSchemaKey.LABEL.value: dependent.get(TypeSchemaKey.LABEL.value),
        }

        for section in render_meta.get(TypeSchemaKey.SECTIONS.value) or []:
            reference: dict[str, Any] = section.get(SectionKey.REFERENCE.value) or {}

            # The query matched the DOCUMENT; which of its sections matched has to be re-established
            # here, because the projection returns the whole sections list
            if (section.get(SectionKey.TYPE.value) != SectionType.REF_SECTION.value
                    or reference.get(SectionReferenceKey.TYPE_ID.value) != referenced_type_id):
                continue

            section_name: Any = reference.get(SectionReferenceKey.SECTION_NAME.value)

            if section_name is None:
                continue

            # A dependent holding two reference sections aimed at the same section is one dependent
            if identity not in sections.setdefault(section_name, []):
                sections[section_name].append(identity)

    return sections


def build_referenced_section_usage_payload(request_user: CmdbUser, target_type: CmdbType) -> dict[str, Any]:
    """
    Builds the "which of this Type's sections are referenced elsewhere" pre-check payload

    REFERENCING_TYPE_IDS answers whether the type may be deleted at all; SECTIONS answers it per
    section, so the type builder can disable the delete action on exactly the sections another Type
    depends on instead of learning about it from a 400 after the fact.

    A dependent naming a section that does not exist (data from before the guard) shows up in
    REFERENCING_TYPE_IDS but under no section, which is correct: no section of this type may be
    deleted on its account, but the type itself is still referenced

    Args:
        request_user (CmdbUser): User performing the request
        target_type (CmdbType): The CmdbType to inspect

    Returns:
        dict[str, Any]: {in_use, count, referencing_type_ids, sections}
    """
    type_id: int = target_type.get_public_id()
    dependents: list[dict[str, Any]] = _find_referencing_types(
        request_user,
        type_id,
        None,
        type_id,
        projection={
            '_id': 0,
            TypeSchemaKey.PUBLIC_ID.value: 1,
            TypeSchemaKey.NAME.value: 1,
            TypeSchemaKey.LABEL.value: 1,
            f'{TypeSchemaKey.RENDER_META.value}.{TypeSchemaKey.SECTIONS.value}': 1,
        },
    )
    referencing_type_ids: list[int] = sorted(
        dependent[TypeSchemaKey.PUBLIC_ID.value] for dependent in dependents
    )
    sections: dict[str, list[dict[str, Any]]] = _group_dependents_by_section(dependents, type_id)

    return {
        ReferencedSectionUsageKey.IN_USE.value: bool(referencing_type_ids),
        ReferencedSectionUsageKey.COUNT.value: len(referencing_type_ids),
        ReferencedSectionUsageKey.REFERENCING_TYPE_IDS.value: referencing_type_ids,
        ReferencedSectionUsageKey.SECTIONS.value: sections,
    }
