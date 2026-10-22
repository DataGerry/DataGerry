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
What the start assistant shows about one best-practice model, computed from its transfer file

Pure functions over the decoded file and its description - no database. ``build_model_preview`` answers the counts
(exactly what the import creates: categories, types, every declared field, relations), the category -> type ->
section -> field tree with every reference target resolved to the type it names, the relations, and the licensed
features the model needs. ``find_preview_problems`` names what does not resolve inside the file - the catalogue test
fails a bundle on it.

A model file is an export, so every document has the stored shape; anything else (a key missing, a value of the wrong
kind) reads as empty here rather than raising, because a preview must never fail the assistant. A reference to a
type the file does not hold is left out of the preview and named by ``find_preview_problems``
"""
from dataclasses import dataclass
from typing import Any

from cmdb.framework.configuration_transfer.best_practice_catalogue import BestPracticeMeta
from cmdb.framework.configuration_transfer.best_practice_constants import (
    UNORDERED_CATEGORY_POSITION,
    UNKNOWN_CATEGORY_TYPE,
    UNKNOWN_DESCRIBED_CATEGORY,
    UNKNOWN_FIELD_TARGET,
    UNKNOWN_RELATION_SIDE,
    UNKNOWN_SECTION_TARGET,
)
from cmdb.framework.configuration_transfer.configuration_transfer_constants import (
    TransferComponentName,
    TransferFileKey,
    TransferSectionKey,
)
from cmdb.models.category_model.category_constants import CategoryKey, CategoryMetaKey
from cmdb.models.relation_model.relation_constants import RelationKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model import TypeSchemaKey
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.section_key_enum import SectionKey
from cmdb.models.type_model.section_reference_key_enum import SectionReferenceKey
from cmdb.security.license.license_constants import LicenseFeature
# -------------------------------------------------------------------------------------------------------------------- #


@dataclass(frozen=True)
class TypeRef:
    """
    A type named in the preview - a reference target, a relation side

    Attributes:
        name (str): The type's unique name
        label (str): What the screens show
    """
    name: str
    label: str


@dataclass(frozen=True)
class FieldPreview:
    """
    One field of a section

    Attributes:
        name (str): The field's identifier
        label (str): What the screens show
        field_type (str): Its ``FieldType`` value
        targets (tuple[TypeRef, ...]): The types a reference field points at; empty for any other field
    """
    name: str
    label: str
    field_type: str
    targets: tuple[TypeRef, ...]


@dataclass(frozen=True)
class SectionPreview:
    """
    One section of a type

    Attributes:
        name (str): The section's identifier
        label (str): What the screens show
        section_type (str): Its ``SectionType`` value
        fields (tuple[FieldPreview, ...]): The fields it shows, in its order
        referenced_type (TypeRef | None): For a reference section, the type it pulls its fields from
    """
    name: str
    label: str
    section_type: str
    fields: tuple[FieldPreview, ...]
    referenced_type: TypeRef | None


@dataclass(frozen=True)
class TypePreview:
    """
    One type of the model

    Attributes:
        name (str): The type's unique name
        label (str): What the screens show
        description (str | None): The type's own description
        special_type (str | None): Its SpecialType marker, None for an ordinary type
        field_count (int): Every field it declares
        sections (tuple[SectionPreview, ...]): Its sections, in its order
    """
    name: str
    label: str
    description: str | None
    special_type: str | None
    field_count: int
    sections: tuple[SectionPreview, ...]


@dataclass(frozen=True)
class CategoryPreview:
    """
    One category of the model with its types

    Attributes:
        name (str): The category's unique name
        label (str): What the screens show
        description (str | None): The line the description file gives it
        parent (str | None): The name of the category it is nested in
        types (tuple[TypePreview, ...]): Its types, in its order
    """
    name: str
    label: str
    description: str | None
    parent: str | None
    types: tuple[TypePreview, ...]


@dataclass(frozen=True)
class RelationPreview:
    """
    One relation of the model

    Attributes:
        name (str): The relation's unique name
        description (str | None): Its description
        parent_label (str | None): How the parent side calls it
        child_label (str | None): How the child side calls it
        parent_types (tuple[TypeRef, ...]): The types allowed on the parent side
        child_types (tuple[TypeRef, ...]): The types allowed on the child side
        field_count (int): The fields the relation itself carries
    """
    name: str
    description: str | None
    parent_label: str | None
    child_label: str | None
    parent_types: tuple[TypeRef, ...]
    child_types: tuple[TypeRef, ...]
    field_count: int


@dataclass(frozen=True)
class PreviewCounts:
    """
    The numbers on a model's card and its details - what the import creates

    Attributes:
        categories (int): Categories
        types (int): Types
        fields (int): Every field the types declare
        relations (int): Relations
    """
    categories: int
    types: int
    fields: int
    relations: int


@dataclass(frozen=True)
class ModelPreview:
    """
    Everything the assistant shows about one model

    Attributes:
        counts (PreviewCounts): The numbers
        categories (tuple[CategoryPreview, ...]): The categories with their types, in category order
        uncategorized (tuple[TypePreview, ...]): The types no category holds
        relations (tuple[RelationPreview, ...]): The relations, by name
        required_features (tuple[str, ...]): The ``LicenseFeature`` values applying the model needs, sorted
    """
    counts: PreviewCounts
    categories: tuple[CategoryPreview, ...]
    uncategorized: tuple[TypePreview, ...]
    relations: tuple[RelationPreview, ...]
    required_features: tuple[str, ...]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  READING THE FILE                                                    #
# -------------------------------------------------------------------------------------------------------------------- #

def component_items(document: dict[str, Any], component: TransferComponentName) -> list[dict[str, Any]]:
    """
    The documents of one component of a transfer file

    Args:
        document (dict[str, Any]): The decoded transfer file
        component (TransferComponentName): The component

    Returns:
        list[dict[str, Any]]: Its documents; anything that is no document is skipped
    """
    components: Any = document.get(TransferFileKey.COMPONENTS.value)
    section: Any = components.get(component.value) if isinstance(components, dict) else None
    items: Any = section.get(TransferSectionKey.ITEMS.value) if isinstance(section, dict) else None

    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def as_list(value: Any) -> list[Any]:
    """
    A stored list, or nothing

    Args:
        value (Any): The stored value

    Returns:
        list[Any]: The list, empty for anything else
    """
    return value if isinstance(value, list) else []


def as_id_list(value: Any) -> list[int]:
    """
    The type ids a stored value names - one id or a list of them, as ``ref_types`` and the relation sides store them

    Args:
        value (Any): The stored value

    Returns:
        list[int]: The whole numbers it holds (booleans are none)
    """
    values: list[Any] = value if isinstance(value, list) else [value]

    return [item for item in values if isinstance(item, int) and not isinstance(item, bool)]


def text_or_none(value: Any) -> str | None:
    """
    A stored text, or None for anything else (an empty text included)

    Args:
        value (Any): The stored value

    Returns:
        str | None: The text
    """
    return value if isinstance(value, str) and value else None


def index_by_public_id(documents: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """
    The documents of one component by their public_id

    Args:
        documents (list[dict[str, Any]]): The documents

    Returns:
        dict[int, dict[str, Any]]: public_id -> document, for every document with an integer public_id
    """
    return {doc[TypeSchemaKey.PUBLIC_ID.value]: doc for doc in documents
            if as_id_list(doc.get(TypeSchemaKey.PUBLIC_ID.value))}


def type_ref(type_doc: dict[str, Any]) -> TypeRef:
    """
    How the preview names a type

    Args:
        type_doc (dict[str, Any]): The type document

    Returns:
        TypeRef: Its name and label (the name when it has no label)
    """
    name: str = text_or_none(type_doc.get(TypeSchemaKey.NAME.value)) or ''

    return TypeRef(name=name, label=text_or_none(type_doc.get(TypeSchemaKey.LABEL.value)) or name)


def resolve_types(type_ids: list[int], types_by_id: dict[int, dict[str, Any]]) -> tuple[TypeRef, ...]:
    """
    The types a list of ids names, in its order - an id the file does not hold is left out

    Args:
        type_ids (list[int]): The ids
        types_by_id (dict[int, dict[str, Any]]): The file's types by public_id

    Returns:
        tuple[TypeRef, ...]: The named types
    """
    return tuple(type_ref(types_by_id[type_id]) for type_id in type_ids if type_id in types_by_id)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    THE PREVIEW                                                       #
# -------------------------------------------------------------------------------------------------------------------- #

def build_field_preview(field: dict[str, Any], types_by_id: dict[int, dict[str, Any]]) -> FieldPreview:
    """
    One field as the preview shows it

    Args:
        field (dict[str, Any]): The field definition of the type
        types_by_id (dict[int, dict[str, Any]]): The file's types by public_id

    Returns:
        FieldPreview: The field, its reference targets resolved
    """
    name: str = text_or_none(field.get(FieldKey.NAME.value)) or ''

    return FieldPreview(
        name=name,
        label=text_or_none(field.get(FieldKey.LABEL.value)) or name,
        field_type=text_or_none(field.get(FieldKey.TYPE.value)) or '',
        targets=resolve_types(as_id_list(field.get(FieldKey.REF_TYPES.value)), types_by_id),
    )


def build_section_preview(
        section: dict[str, Any],
        fields_by_name: dict[str, dict[str, Any]],
        types_by_id: dict[int, dict[str, Any]]) -> SectionPreview:
    """
    One section as the preview shows it

    Args:
        section (dict[str, Any]): The section of the type's render_meta
        fields_by_name (dict[str, dict[str, Any]]): The type's field definitions by name
        types_by_id (dict[int, dict[str, Any]]): The file's types by public_id

    Returns:
        SectionPreview: The section with the fields it names, in its order - a name the type does not declare is
            left out (the type structure rules refuse such a type on import)
    """
    name: str = text_or_none(section.get(SectionKey.NAME.value)) or ''
    reference: Any = section.get(SectionKey.REFERENCE.value)
    referenced: tuple[TypeRef, ...] = resolve_types(
        as_id_list(reference.get(SectionReferenceKey.TYPE_ID.value)) if isinstance(reference, dict) else [],
        types_by_id,
    )

    return SectionPreview(
        name=name,
        label=text_or_none(section.get(SectionKey.LABEL.value)) or name,
        section_type=text_or_none(section.get(SectionKey.TYPE.value)) or '',
        fields=tuple(build_field_preview(fields_by_name[field_name], types_by_id)
                     for field_name in as_list(section.get(SectionKey.FIELDS.value))
                     if isinstance(field_name, str) and field_name in fields_by_name),
        referenced_type=referenced[0] if referenced else None,
    )


def type_sections(type_doc: dict[str, Any]) -> list[dict[str, Any]]:
    """
    The sections of a type's render_meta

    Args:
        type_doc (dict[str, Any]): The type document

    Returns:
        list[dict[str, Any]]: Its sections; anything that is no section is skipped
    """
    render_meta: Any = type_doc.get(TypeSchemaKey.RENDER_META.value)
    sections: Any = render_meta.get(TypeSchemaKey.SECTIONS.value) if isinstance(render_meta, dict) else None

    return [section for section in as_list(sections) if isinstance(section, dict)]


def type_fields(type_doc: dict[str, Any]) -> list[dict[str, Any]]:
    """
    The field definitions of a type

    Args:
        type_doc (dict[str, Any]): The type document

    Returns:
        list[dict[str, Any]]: Its fields; anything that is no field is skipped
    """
    return [field for field in as_list(type_doc.get(TypeSchemaKey.FIELDS.value)) if isinstance(field, dict)]


def build_type_preview(type_doc: dict[str, Any], types_by_id: dict[int, dict[str, Any]]) -> TypePreview:
    """
    One type as the preview shows it

    Args:
        type_doc (dict[str, Any]): The type document
        types_by_id (dict[int, dict[str, Any]]): The file's types by public_id

    Returns:
        TypePreview: The type with its sections
    """
    fields: list[dict[str, Any]] = type_fields(type_doc)
    fields_by_name: dict[str, dict[str, Any]] = {
        field[FieldKey.NAME.value]: field for field in fields if isinstance(field.get(FieldKey.NAME.value), str)
    }
    ref: TypeRef = type_ref(type_doc)

    return TypePreview(
        name=ref.name,
        label=ref.label,
        description=text_or_none(type_doc.get(TypeSchemaKey.DESCRIPTION.value)),
        special_type=text_or_none(type_doc.get(TypeSchemaKey.SPECIAL_TYPE.value)),
        field_count=len(fields),
        sections=tuple(build_section_preview(section, fields_by_name, types_by_id)
                       for section in type_sections(type_doc)),
    )


def category_order(category: dict[str, Any]) -> tuple[int, str]:
    """
    Where a category stands among the categories: its stored order (none last), then its name

    Args:
        category (dict[str, Any]): The category document

    Returns:
        tuple[int, str]: The sort key
    """
    meta: Any = category.get(CategoryKey.META.value)
    order: list[int] = as_id_list(meta.get(CategoryMetaKey.ORDER.value)) if isinstance(meta, dict) else []

    name: str = text_or_none(category.get(CategoryKey.NAME.value)) or ''

    return (order[0] if order else UNORDERED_CATEGORY_POSITION, name)


def build_category_previews(
        categories: list[dict[str, Any]],
        type_previews: dict[int, TypePreview],
        meta: BestPracticeMeta) -> tuple[CategoryPreview, ...]:
    """
    The categories with their types, in category order

    Args:
        categories (list[dict[str, Any]]): The category documents
        type_previews (dict[int, TypePreview]): The previewed types by public_id
        meta (BestPracticeMeta): The model's description - the category descriptions

    Returns:
        tuple[CategoryPreview, ...]: The categories
    """
    names_by_id: dict[int, str] = {
        public_id: text_or_none(category.get(CategoryKey.NAME.value)) or ''
        for public_id, category in index_by_public_id(categories).items()
    }
    previews: list[CategoryPreview] = []

    for category in sorted(categories, key=category_order):
        name: str = text_or_none(category.get(CategoryKey.NAME.value)) or ''
        parent_ids: list[int] = as_id_list(category.get(CategoryKey.PARENT.value))
        previews.append(CategoryPreview(
            name=name,
            label=text_or_none(category.get(CategoryKey.LABEL.value)) or name,
            description=meta.category_descriptions.get(name),
            parent=names_by_id.get(parent_ids[0]) if parent_ids else None,
            types=tuple(type_previews[type_id] for type_id in as_id_list(category.get(CategoryKey.TYPES.value))
                        if type_id in type_previews),
        ))

    return tuple(previews)


def build_relation_preview(relation: dict[str, Any], types_by_id: dict[int, dict[str, Any]]) -> RelationPreview:
    """
    One relation as the preview shows it

    Args:
        relation (dict[str, Any]): The relation document
        types_by_id (dict[int, dict[str, Any]]): The file's types by public_id

    Returns:
        RelationPreview: The relation, both sides resolved
    """
    return RelationPreview(
        name=text_or_none(relation.get(RelationKey.RELATION_NAME.value)) or '',
        description=text_or_none(relation.get(RelationKey.DESCRIPTION.value)),
        parent_label=text_or_none(relation.get(RelationKey.RELATION_NAME_PARENT.value)),
        child_label=text_or_none(relation.get(RelationKey.RELATION_NAME_CHILD.value)),
        parent_types=resolve_types(as_id_list(relation.get(RelationKey.PARENT_TYPE_IDS.value)), types_by_id),
        child_types=resolve_types(as_id_list(relation.get(RelationKey.CHILD_TYPE_IDS.value)), types_by_id),
        field_count=len([field for field in as_list(relation.get(RelationKey.FIELDS.value))
                         if isinstance(field, dict)]),
    )


def required_features(types: list[dict[str, Any]]) -> tuple[str, ...]:
    """
    The licensed features applying a model needs - what the type routes would refuse without them

    A license-gated SpecialType (``SpecialType.is_license_gated``) and a type with ``uses_ports`` (Port Connectivity)
    each need ``LicenseFeature.IPAM`` - the one gating feature there is

    Args:
        types (list[dict[str, Any]]): The type documents

    Returns:
        tuple[str, ...]: The ``LicenseFeature`` values, sorted; empty when the model needs none
    """
    needs_ipam: bool = any(
        SpecialType.is_license_gated(type_doc.get(TypeSchemaKey.SPECIAL_TYPE.value))
        or type_doc.get(TypeSchemaKey.USES_PORTS.value) is True
        for type_doc in types
    )

    return (LicenseFeature.IPAM.value,) if needs_ipam else ()


def build_model_preview(document: dict[str, Any], meta: BestPracticeMeta) -> ModelPreview:
    """
    Everything the assistant shows about one model

    Args:
        document (dict[str, Any]): The decoded transfer file
        meta (BestPracticeMeta): The model's description

    Returns:
        ModelPreview: The counts, the category tree, the uncategorized types, the relations and the features
    """
    types: list[dict[str, Any]] = component_items(document, TransferComponentName.TYPES)
    categories: list[dict[str, Any]] = component_items(document, TransferComponentName.CATEGORIES)
    relations: list[dict[str, Any]] = component_items(document, TransferComponentName.RELATIONS)
    types_by_id: dict[int, dict[str, Any]] = index_by_public_id(types)
    type_previews: dict[int, TypePreview] = {
        public_id: build_type_preview(type_doc, types_by_id) for public_id, type_doc in types_by_id.items()
    }
    categorized: set[int] = {type_id for category in categories
                             for type_id in as_id_list(category.get(CategoryKey.TYPES.value))}

    return ModelPreview(
        counts=PreviewCounts(
            categories=len(categories),
            types=len(types),
            fields=sum(len(type_fields(type_doc)) for type_doc in types),
            relations=len(relations),
        ),
        categories=build_category_previews(categories, type_previews, meta),
        uncategorized=tuple(preview for public_id, preview in type_previews.items() if public_id not in categorized),
        relations=tuple(sorted((build_relation_preview(relation, types_by_id) for relation in relations),
                               key=lambda relation: relation.name)),
        required_features=required_features(types),
    )


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    CONSISTENCY                                                       #
# -------------------------------------------------------------------------------------------------------------------- #

def find_type_problems(type_doc: dict[str, Any], types_by_id: dict[int, dict[str, Any]]) -> list[str]:
    """
    The references of one type that do not resolve inside the file: field targets and reference sections

    Args:
        type_doc (dict[str, Any]): The type document
        types_by_id (dict[int, dict[str, Any]]): The file's types by public_id

    Returns:
        list[str]: The problems, in field then section order
    """
    type_name: str = type_ref(type_doc).name
    problems: list[str] = [
        UNKNOWN_FIELD_TARGET.format(field=field.get(FieldKey.NAME.value), type=type_name, target=target)
        for field in type_fields(type_doc)
        for target in as_id_list(field.get(FieldKey.REF_TYPES.value)) if target not in types_by_id
    ]

    for section in type_sections(type_doc):
        reference: Any = section.get(SectionKey.REFERENCE.value)
        targets: list[int] = (as_id_list(reference.get(SectionReferenceKey.TYPE_ID.value))
                              if isinstance(reference, dict) else [])
        problems.extend(
            UNKNOWN_SECTION_TARGET.format(section=section.get(SectionKey.NAME.value), type=type_name, target=target)
            for target in targets if target not in types_by_id
        )

    return problems


def find_preview_problems(document: dict[str, Any], meta: BestPracticeMeta) -> list[str]:
    """
    What does not resolve inside a model's file pair - every problem, so a bundle's author sees them together

    A category description naming no category of the file, a field or a reference section targeting a type the file
    does not hold, a relation side or a category entry naming one

    Args:
        document (dict[str, Any]): The decoded transfer file
        meta (BestPracticeMeta): The model's description

    Returns:
        list[str]: The problems, empty for a consistent pair
    """
    types: list[dict[str, Any]] = component_items(document, TransferComponentName.TYPES)
    categories: list[dict[str, Any]] = component_items(document, TransferComponentName.CATEGORIES)
    types_by_id: dict[int, dict[str, Any]] = index_by_public_id(types)
    category_names: set[str] = {text_or_none(category.get(CategoryKey.NAME.value)) or '' for category in categories}

    problems: list[str] = [UNKNOWN_DESCRIBED_CATEGORY.format(name=name)
                           for name in sorted(meta.category_descriptions) if name not in category_names]

    for type_doc in types:
        problems.extend(find_type_problems(type_doc, types_by_id))

    for relation in component_items(document, TransferComponentName.RELATIONS):
        sides: list[int] = (as_id_list(relation.get(RelationKey.PARENT_TYPE_IDS.value))
                            + as_id_list(relation.get(RelationKey.CHILD_TYPE_IDS.value)))
        problems.extend(UNKNOWN_RELATION_SIDE.format(relation=relation.get(RelationKey.RELATION_NAME.value),
                                                     target=target)
                        for target in sides if target not in types_by_id)

    for category in categories:
        problems.extend(UNKNOWN_CATEGORY_TYPE.format(category=category.get(CategoryKey.NAME.value), target=target)
                        for target in as_id_list(category.get(CategoryKey.TYPES.value)) if target not in types_by_id)

    return problems
