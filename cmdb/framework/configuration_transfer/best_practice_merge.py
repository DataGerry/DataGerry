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
Combines several best-practice models into one transfer file the configuration import takes

The models arrive in card order, each in the importing database's version. Per component, the entries are taken by
name: the first model's entry of a name is kept, a later model's entry of the same name is dropped when it is
identical (``best_practice_identity``) and named as a conflict when it is not. Categories are the exception: their
types are combined - each type in one category only, across the models - and only their label and parent compared.

The kept entries are numbered anew from 1, in the order they were first met, and every id they hold is rewritten to
the new number of the entry it named in its own file: a field's ``ref_types``, a reference section's ``type_id``, a
category's ``types`` and ``parent``, a relation's two sides. A type claims its global section templates by name, so
template ids are renumbered but nothing names them.

One model is answered as its file is - ids and counters as exported, the way a single model was always applied.
Nothing here reads a database; a conflict never raises, it is collected, so a caller can show every one at once
"""
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any, Callable

from cmdb.models.category_model.category_constants import CategoryKey
from cmdb.models.relation_model.relation_constants import RelationKey
from cmdb.models.section_template_model.section_template_constants import SectionTemplateKey
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.section_key_enum import SectionKey
from cmdb.models.type_model.section_reference_key_enum import SectionReferenceKey
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.framework.configuration_transfer.configuration_transfer_constants import (
    INFORMATION_NAME_MAX_LENGTH,
    TransferComponentName,
    TransferFileKey,
)
from cmdb.framework.configuration_transfer.best_practice_constants import (
    COMBINED_DESCRIPTION,
    COMBINED_NAME_SEPARATOR,
    ENTRY_DIFFERS,
    MODEL_PROBLEM,
    TYPE_IN_TWO_CATEGORIES,
    BestPracticeMetaKey,
    CombinedEntryKind,
)
from cmdb.framework.configuration_transfer.best_practice_catalogue import BestPracticeMeta, BestPracticeModel
from cmdb.framework.configuration_transfer.best_practice_identity import (
    comparable_category,
    comparable_relation,
    comparable_section_template,
    comparable_type,
    differing_parts,
    is_id,
    names_by_id,
)
from cmdb.framework.configuration_transfer.best_practice_preview import component_items, find_preview_problems
from cmdb.framework.configuration_transfer.transfer_file import build_component_section, build_transfer_file
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = ['CombinedModels', 'combine_models']


@dataclass(frozen=True)
class CombinedModels:
    """
    Several best-practice models combined into one file

    Attributes:
        document (dict[str, Any]): The combined transfer file - ready for the configuration import when there is no
            conflict
        meta (BestPracticeMeta): The first model's meta, its category descriptions combined (the first one's wins)
        conflicts (tuple[str, ...]): Why the models cannot be combined - empty when they can
        merged (dict[str, tuple[str, ...]]): Per component, the names more than one model holds and that are created
            once
    """
    document: dict[str, Any]
    meta: BestPracticeMeta
    conflicts: tuple[str, ...]
    merged: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class _Entry:
    """One kept entry: the model it was first met in, and the entry as that model's file holds it"""
    model: BestPracticeModel
    item: dict[str, Any]


@dataclass
class _ModelIndex:
    """One model's names by id, the dictionaries every rewrite reads"""
    type_names: dict[int, Any]
    category_names: dict[int, Any]


# The name key of each component's entries, and what its messages call one
_NAME_KEYS: dict[TransferComponentName, str] = {
    TransferComponentName.SECTION_TEMPLATES: SectionTemplateKey.NAME.value,
    TransferComponentName.TYPES: TypeSchemaKey.NAME.value,
    TransferComponentName.CATEGORIES: CategoryKey.NAME.value,
    TransferComponentName.RELATIONS: RelationKey.RELATION_NAME.value,
}
_KINDS: dict[TransferComponentName, CombinedEntryKind] = {
    TransferComponentName.SECTION_TEMPLATES: CombinedEntryKind.SECTION_TEMPLATE,
    TransferComponentName.TYPES: CombinedEntryKind.TYPE,
    TransferComponentName.CATEGORIES: CombinedEntryKind.CATEGORY,
    TransferComponentName.RELATIONS: CombinedEntryKind.RELATION,
}


def _index_model(model: BestPracticeModel) -> _ModelIndex:
    """
    Reads one model's type and category names by id

    Args:
        model (BestPracticeModel): The model

    Returns:
        _ModelIndex: Its names by id
    """
    return _ModelIndex(
        type_names=names_by_id(component_items(model.document, TransferComponentName.TYPES),
                               TypeSchemaKey.NAME.value),
        category_names=names_by_id(component_items(model.document, TransferComponentName.CATEGORIES),
                                   CategoryKey.NAME.value),
    )


def _comparer(component: TransferComponentName,
              indexes: dict[str, _ModelIndex]) -> Callable[[dict[str, Any], BestPracticeModel], dict[str, Any]]:
    """
    How one component's entries are made comparable

    Args:
        component (TransferComponentName): The component
        indexes (dict[str, _ModelIndex]): Each model's names by id, by model id

    Returns:
        Callable[[dict[str, Any], BestPracticeModel], dict[str, Any]]: entry, its model -> the comparable entry
    """
    if component == TransferComponentName.TYPES:
        return lambda item, model: comparable_type(item, indexes[model.model_id].type_names)

    if component == TransferComponentName.RELATIONS:
        return lambda item, model: comparable_relation(item, indexes[model.model_id].type_names)

    if component == TransferComponentName.CATEGORIES:
        return lambda item, model: comparable_category(item, indexes[model.model_id].category_names)

    return lambda item, _model: comparable_section_template(item)


def combine_entries(models: list[BestPracticeModel], component: TransferComponentName,
                    indexes: dict[str, _ModelIndex]) -> tuple[dict[Any, _Entry], list[str], list[str]]:
    """
    Takes one component's entries by name: the first of a name is kept, a later one compared with it

    Args:
        models (list[BestPracticeModel]): The models, in card order
        component (TransferComponentName): The component
        indexes (dict[str, _ModelIndex]): Each model's names by id, by model id

    Returns:
        tuple[dict[Any, _Entry], list[str], list[str]]: The kept entries by name (in the order first met), the
            conflicts, and the names more than one model holds
    """
    name_key: str = _NAME_KEYS[component]
    comparable = _comparer(component, indexes)
    kept: dict[Any, _Entry] = {}
    conflicts: list[str] = []
    merged: list[str] = []

    for model in models:
        for item in component_items(model.document, component):
            name: Any = item.get(name_key)
            first: _Entry | None = kept.get(name)

            if first is None:
                kept[name] = _Entry(model, item)
                continue

            if name not in merged:
                merged.append(name)

            parts: list[str] = differing_parts(comparable(first.item, first.model), comparable(item, model))

            if parts:
                conflicts.append(ENTRY_DIFFERS.format(kind=_KINDS[component].value, name=name,
                                                      first=first.model.model_id, other=model.model_id,
                                                      parts=', '.join(parts)))

    return kept, conflicts, merged


def remap_ids(value: Any, old_names: dict[int, Any], new_ids: dict[Any, int]) -> Any:
    """
    Rewrites the ids a stored value holds to the new numbers of the entries they named

    The value keeps its shape: one id, a list of them, a list holding lists (``ref_types``). An id its file does not
    hold is left as it is - the model's own problems name it

    Args:
        value (Any): The stored value
        old_names (dict[int, Any]): The value's file: public_id -> name
        new_ids (dict[Any, int]): The combined file: name -> new public_id

    Returns:
        Any: The rewritten value - a new list where the value is one
    """
    if isinstance(value, list):
        return [remap_ids(nested, old_names, new_ids) for nested in value]

    if is_id(value) and value in old_names:
        return new_ids.get(old_names[value], value)

    return value


def rewrite_type(entry: _Entry, new_id: int, index: _ModelIndex, new_type_ids: dict[Any, int]) -> dict[str, Any]:
    """
    A kept type under its new number, every type id it holds rewritten

    Args:
        entry (_Entry): The kept type
        new_id (int): Its new public_id
        index (_ModelIndex): Its model's names by id
        new_type_ids (dict[Any, int]): The combined file's type name -> new public_id

    Returns:
        dict[str, Any]: A new type entry
    """
    item: dict[str, Any] = deepcopy(entry.item)
    item[TypeSchemaKey.PUBLIC_ID.value] = new_id

    for field in item.get(TypeSchemaKey.FIELDS.value) or []:
        if isinstance(field, dict) and FieldKey.REF_TYPES.value in field:
            field[FieldKey.REF_TYPES.value] = remap_ids(field[FieldKey.REF_TYPES.value], index.type_names,
                                                        new_type_ids)

    render_meta: Any = item.get(TypeSchemaKey.RENDER_META.value)
    sections: Any = render_meta.get(TypeSchemaKey.SECTIONS.value) if isinstance(render_meta, dict) else None

    for section in sections or []:
        reference: Any = section.get(SectionKey.REFERENCE.value) if isinstance(section, dict) else None

        if isinstance(reference, dict) and SectionReferenceKey.TYPE_ID.value in reference:
            reference[SectionReferenceKey.TYPE_ID.value] = remap_ids(
                reference[SectionReferenceKey.TYPE_ID.value], index.type_names, new_type_ids,
            )

    return item


def rewrite_relation(entry: _Entry, new_id: int, index: _ModelIndex, new_type_ids: dict[Any, int]) -> dict[str, Any]:
    """
    A kept relation under its new number, both sides rewritten

    Args:
        entry (_Entry): The kept relation
        new_id (int): Its new public_id
        index (_ModelIndex): Its model's names by id
        new_type_ids (dict[Any, int]): The combined file's type name -> new public_id

    Returns:
        dict[str, Any]: A new relation entry
    """
    item: dict[str, Any] = deepcopy(entry.item)
    item[RelationKey.PUBLIC_ID.value] = new_id

    for side in (RelationKey.PARENT_TYPE_IDS.value, RelationKey.CHILD_TYPE_IDS.value):
        if side in item:
            item[side] = remap_ids(item[side], index.type_names, new_type_ids)

    return item


def combine_category_types(models: list[BestPracticeModel],
                           indexes: dict[str, _ModelIndex]) -> tuple[dict[Any, list[Any]], list[str]]:
    """
    Collects each category's types by name across the models - each type in one category only

    A type one model files under one category and a later model under another is a conflict: the import keeps a type
    in one category. Inside one model that is the import's own rule to judge

    Args:
        models (list[BestPracticeModel]): The models, in card order
        indexes (dict[str, _ModelIndex]): Each model's names by id, by model id

    Returns:
        tuple[dict[Any, list[Any]], list[str]]: Category name -> its type names (first met first, each once), and
            the conflicts
    """
    types_of: dict[Any, list[Any]] = {}
    home: dict[Any, tuple[Any, str]] = {}
    conflicts: list[str] = []

    for model in models:
        type_names: dict[int, Any] = indexes[model.model_id].type_names

        for category in component_items(model.document, TransferComponentName.CATEGORIES):
            category_name: Any = category.get(CategoryKey.NAME.value)
            names: list[Any] = types_of.setdefault(category_name, [])

            for type_id in category.get(CategoryKey.TYPES.value) or []:
                type_name: Any = type_names.get(type_id, type_id)
                first_home: tuple[Any, str] | None = home.get(type_name)

                if first_home is not None and first_home[0] != category_name and first_home[1] != model.model_id:
                    conflicts.append(TYPE_IN_TWO_CATEGORIES.format(
                        name=type_name, first_category=first_home[0], first=first_home[1],
                        other_category=category_name, other=model.model_id,
                    ))
                    continue

                home.setdefault(type_name, (category_name, model.model_id))

                if type_name not in names:
                    names.append(type_name)

    return types_of, conflicts


def build_categories(kept: dict[Any, _Entry], types_of: dict[Any, list[Any]], indexes: dict[str, _ModelIndex],
                     new_type_ids: dict[Any, int]) -> list[dict[str, Any]]:
    """
    The combined categories: renumbered, the parent by its new number, the combined types by theirs

    Args:
        kept (dict[Any, _Entry]): The kept categories by name, in the order first met
        types_of (dict[Any, list[Any]]): Category name -> its combined type names
        indexes (dict[str, _ModelIndex]): Each model's names by id, by model id
        new_type_ids (dict[Any, int]): The combined file's type name -> new public_id

    Returns:
        list[dict[str, Any]]: The category entries
    """
    new_category_ids: dict[Any, int] = {name: position for position, name in enumerate(kept, start=1)}
    categories: list[dict[str, Any]] = []

    for name, entry in kept.items():
        item: dict[str, Any] = deepcopy(entry.item)
        item[CategoryKey.PUBLIC_ID.value] = new_category_ids[name]
        item[CategoryKey.PARENT.value] = remap_ids(item.get(CategoryKey.PARENT.value),
                                                   indexes[entry.model.model_id].category_names, new_category_ids)
        item[CategoryKey.TYPES.value] = [new_type_ids.get(type_name, type_name) for type_name in types_of[name]]
        categories.append(item)

    return categories


def combine_meta(models: list[BestPracticeModel]) -> tuple[BestPracticeMeta, dict[str, Any]]:
    """
    The combined meta: the first model's, its category descriptions joined (the first model's description of a
    category wins)

    Args:
        models (list[BestPracticeModel]): The models, in card order

    Returns:
        tuple[BestPracticeMeta, dict[str, Any]]: The meta, and the file's meta section
    """
    descriptions: dict[str, str] = {}

    for model in models:
        for name, text in model.meta.category_descriptions.items():
            descriptions.setdefault(name, text)

    meta: BestPracticeMeta = replace(models[0].meta, category_descriptions=descriptions)
    section: dict[str, Any] = deepcopy(models[0].document.get(TransferFileKey.META.value) or {})
    section[BestPracticeMetaKey.CATEGORY_DESCRIPTIONS.value] = dict(descriptions)

    return meta, section


def model_problems(models: list[BestPracticeModel]) -> list[str]:
    """
    What does not resolve inside each model's own file - an id naming no entry would be rewritten to nothing

    Args:
        models (list[BestPracticeModel]): The models

    Returns:
        list[str]: Every problem, prefixed with its model
    """
    return [MODEL_PROBLEM.format(model_id=model.model_id, problem=problem)
            for model in models for problem in find_preview_problems(model.document, model.meta)]


def combine_models(models: list[BestPracticeModel]) -> CombinedModels:
    """
    Combines best-practice models into one transfer file - one entry per name, every id renumbered

    Args:
        models (list[BestPracticeModel]): At least one model, in card order, each in the importing version

    Returns:
        CombinedModels: The combined file, its meta, every conflict and what was merged
    """
    problems: list[str] = model_problems(models)

    if len(models) == 1:
        return CombinedModels(deepcopy(models[0].document), models[0].meta, tuple(problems), {})

    indexes: dict[str, _ModelIndex] = {model.model_id: _index_model(model) for model in models}
    kept: dict[TransferComponentName, dict[Any, _Entry]] = {}
    merged: dict[str, tuple[str, ...]] = {}

    for component in _NAME_KEYS:
        kept[component], conflicts, merged_names = combine_entries(models, component, indexes)
        problems += conflicts

        if merged_names:
            merged[component.value] = tuple(merged_names)

    types_of, category_conflicts = combine_category_types(models, indexes)
    problems += category_conflicts
    new_type_ids: dict[Any, int] = {name: position for position, name
                                    in enumerate(kept[TransferComponentName.TYPES], start=1)}

    items: dict[TransferComponentName, list[dict[str, Any]]] = {
        TransferComponentName.SECTION_TEMPLATES: [
            {**deepcopy(entry.item), SectionTemplateKey.PUBLIC_ID.value: position}
            for position, entry in enumerate(kept[TransferComponentName.SECTION_TEMPLATES].values(), start=1)
        ],
        TransferComponentName.TYPES: [
            rewrite_type(entry, position, indexes[entry.model.model_id], new_type_ids)
            for position, entry in enumerate(kept[TransferComponentName.TYPES].values(), start=1)
        ],
        TransferComponentName.CATEGORIES: build_categories(kept[TransferComponentName.CATEGORIES], types_of,
                                                           indexes, new_type_ids),
        TransferComponentName.RELATIONS: [
            rewrite_relation(entry, position, indexes[entry.model.model_id], new_type_ids)
            for position, entry in enumerate(kept[TransferComponentName.RELATIONS].values(), start=1)
        ],
    }

    meta, meta_section = combine_meta(models)
    document: dict[str, Any] = build_transfer_file(
        models[0].document[TransferFileKey.DB_VERSION.value],
        {component.value: build_component_section(len(entries), entries) for component, entries in items.items()},
        name=COMBINED_NAME_SEPARATOR.join(model.meta.title for model in models)[:INFORMATION_NAME_MAX_LENGTH],
        description=COMBINED_DESCRIPTION.format(model_ids=', '.join(model.model_id for model in models)),
    )
    document[TransferFileKey.META.value] = meta_section

    return CombinedModels(document, meta, tuple(problems), merged)
