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
Unit tests for ``configuration_transfer.best_practice_merge`` - several models combined into one transfer file

Pure: the two fixture models (``tests.utils.best_practice_model_fixture``) share the company under other ids and the
contact category; the second adds a supplier referencing the company and a relation. What is pinned: one entry per
name, the new numbers and every id rewritten to them, the first model winning what is not compared, every conflict
collected, and a combined file the import's envelope check accepts
"""
from copy import deepcopy
from typing import Any

import pytest

from cmdb.framework.configuration_transfer import (
    BestPracticeModel,
    TRANSFER_COMPONENT_NAMES,
    combine_models,
    find_preview_problems,
    find_transfer_file_problems,
)
from cmdb.framework.configuration_transfer.best_practice_catalogue import build_meta
from cmdb.framework.configuration_transfer.best_practice_constants import (
    COMBINED_DESCRIPTION,
    ENTRY_DIFFERS,
    MODEL_PROBLEM,
    TYPE_IN_TWO_CATEGORIES,
    BestPracticeMetaKey,
    CombinedEntryKind,
)
from cmdb.framework.configuration_transfer.best_practice_merge import remap_ids
from cmdb.framework.configuration_transfer.best_practice_preview import component_items
from cmdb.framework.configuration_transfer.configuration_transfer_constants import (
    TransferComponentName,
    TransferFileKey,
    TransferInformationKey,
    TransferSectionKey,
)
from cmdb.models.category_model.category_constants import CategoryKey, CategoryMetaKey
from cmdb.models.relation_model.relation_constants import RelationKey
from cmdb.models.section_template_model.section_template_constants import SectionTemplateKey
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from tests.utils.best_practice_model_fixture import (
    COMPANY_NAME,
    CONTACT_DESCRIPTION,
    CONTACT_NAME,
    CUSTOMER_NAME,
    EMPLOYER_FIELD,
    RELATION_NAME,
    SECOND_COMPANY_DESCRIPTION,
    SECOND_COMPANY_ICON,
    SECOND_CATEGORY_DESCRIPTION,
    SECOND_CATEGORY_ICON,
    SUPERNET_NAME,
    SUPPLIER_FIELD,
    SUPPLIER_NAME,
    SUPPLIES_RELATION_NAME,
    model_document,
    model_meta,
    second_model_document,
    second_model_meta,
)
# -------------------------------------------------------------------------------------------------------------------- #

FIRST_ID: str = 'first'
SECOND_ID: str = 'second'
OTHER_LABEL: str = 'Company name'
OTHER_CATEGORY: str = 'bp-partners'
TEMPLATE_NAME: str = 'bp-template'
# The combined file's numbers, in the order the entries are first met
NEW_COMPANY, NEW_CUSTOMER, NEW_SUPERNET, NEW_SUPPLIER = 1, 2, 3, 4
NEW_WORKS_FOR, NEW_SUPPLIES = 1, 2


def _model(model_id: str, document: dict[str, Any], meta: dict[str, Any]) -> BestPracticeModel:
    """A model as the catalogue holds it: the meta section in the document and built"""
    return BestPracticeModel(model_id, build_meta(meta), {**document, TransferFileKey.META.value: meta})


def _first() -> BestPracticeModel:
    """The first fixture model - company, customer, Supernet; the contact category; works_for"""
    return _model(FIRST_ID, model_document(), model_meta())


def _second(document: dict[str, Any] | None = None) -> BestPracticeModel:
    """The second fixture model - the company again, a supplier; the contact category; supplies"""
    return _model(SECOND_ID, second_model_document() if document is None else document, second_model_meta())


def _items(document: dict[str, Any], component: TransferComponentName) -> list[dict[str, Any]]:
    """One component's entries of a combined file"""
    return component_items(document, component)


def _raw_items(document: dict[str, Any], component: TransferComponentName) -> list[dict[str, Any]]:
    """One component's stored entry list - appending to it adds an entry"""
    return document[TransferFileKey.COMPONENTS.value][component.value][TransferSectionKey.ITEMS.value]


def _by_name(document: dict[str, Any], component: TransferComponentName, key: str) -> dict[str, dict[str, Any]]:
    """One component's entries by name"""
    return {item[key]: item for item in _items(document, component)}


@pytest.fixture(name='combined')
def fixture_combined() -> Any:
    """The two fixture models combined"""
    return combine_models([_first(), _second()])


class TestOneModel:
    """A single model is applied as its file is"""

    def test_the_file_is_answered_as_it_is(self) -> None:
        """Ids and counters as exported - a copy"""
        model = _first()

        combined = combine_models([model])

        assert combined.document == model.document and combined.document is not model.document
        assert (combined.meta, combined.conflicts, combined.merged) == (model.meta, (), {})


class TestOneEntryPerName:
    """Every name is created once, renumbered from 1 in the order first met"""

    def test_the_types(self, combined: Any) -> None:
        """The shared company once; the first model's types first"""
        names = [(item[TypeSchemaKey.PUBLIC_ID.value], item[TypeSchemaKey.NAME.value])
                 for item in _items(combined.document, TransferComponentName.TYPES)]

        assert names == [(NEW_COMPANY, COMPANY_NAME), (NEW_CUSTOMER, CUSTOMER_NAME), (NEW_SUPERNET, SUPERNET_NAME),
                         (NEW_SUPPLIER, SUPPLIER_NAME)]

    def test_the_relations(self, combined: Any) -> None:
        """Both, each side rewritten to the new type numbers"""
        relations = _by_name(combined.document, TransferComponentName.RELATIONS, RelationKey.RELATION_NAME.value)

        assert {name: (item[RelationKey.PUBLIC_ID.value], item[RelationKey.PARENT_TYPE_IDS.value],
                       item[RelationKey.CHILD_TYPE_IDS.value]) for name, item in relations.items()} == {
            RELATION_NAME: (NEW_WORKS_FOR, [NEW_COMPANY], [NEW_CUSTOMER]),
            SUPPLIES_RELATION_NAME: (NEW_SUPPLIES, [NEW_COMPANY], [NEW_SUPPLIER]),
        }

    def test_the_shared_category_holds_both_models_types(self, combined: Any) -> None:
        """The types combined, each once, the first model's first"""
        categories = _items(combined.document, TransferComponentName.CATEGORIES)

        assert [(item[CategoryKey.PUBLIC_ID.value], item[CategoryKey.NAME.value], item[CategoryKey.TYPES.value])
                for item in categories] == [(1, CONTACT_NAME, [NEW_COMPANY, NEW_CUSTOMER, NEW_SUPPLIER])]

    def test_every_counter_is_its_entry_count(self, combined: Any) -> None:
        """The entries are numbered 1..n"""
        sections = combined.document[TransferFileKey.COMPONENTS.value]

        assert {name: section[TransferSectionKey.COUNTER.value] for name, section in sections.items()} == {
            TransferComponentName.SECTION_TEMPLATES.value: 0, TransferComponentName.TYPES.value: 4,
            TransferComponentName.CATEGORIES.value: 1, TransferComponentName.RELATIONS.value: 2,
        }

    def test_what_was_merged_is_named(self, combined: Any) -> None:
        """Per component, the names more than one model holds"""
        assert combined.merged == {TransferComponentName.TYPES.value: (COMPANY_NAME,),
                                   TransferComponentName.CATEGORIES.value: (CONTACT_NAME,)}
        assert not combined.conflicts


class TestThreeModels:
    """A name the second and the third model share with the first"""

    def test_a_name_held_by_three_models_is_named_once(self) -> None:
        """Merged once, created once"""
        third = _model('third', second_model_document(), second_model_meta(order=2))

        combined = combine_models([_first(), _second(), third])

        assert combined.merged[TransferComponentName.TYPES.value] == (COMPANY_NAME, SUPPLIER_NAME)
        assert not combined.conflicts
        assert len(_items(combined.document, TransferComponentName.TYPES)) == 4

    def test_a_relation_without_a_side_keeps_it_missing(self) -> None:
        """Only a side that is there is rewritten - the import judges the rest"""
        document = second_model_document()
        del component_items(document, TransferComponentName.RELATIONS)[0][RelationKey.CHILD_TYPE_IDS.value]

        combined = combine_models([_first(), _second(document)])
        supplies = _by_name(combined.document, TransferComponentName.RELATIONS,
                            RelationKey.RELATION_NAME.value)[SUPPLIES_RELATION_NAME]

        assert RelationKey.CHILD_TYPE_IDS.value not in supplies
        assert supplies[RelationKey.PARENT_TYPE_IDS.value] == [NEW_COMPANY]


class TestReferences:
    """Every type id a type holds names the new number of the type it named in its own file"""

    @staticmethod
    def _targets(document: dict[str, Any], type_name: str, field_name: str) -> Any:
        """The ref_types of one field of one type"""
        item = _by_name(document, TransferComponentName.TYPES, TypeSchemaKey.NAME.value)[type_name]

        return next(field[FieldKey.REF_TYPES.value] for field in item[TypeSchemaKey.FIELDS.value]
                    if field[FieldKey.NAME.value] == field_name)

    def test_the_first_models_reference(self, combined: Any) -> None:
        """The customer's employer: the company, 41 in its file"""
        assert self._targets(combined.document, CUSTOMER_NAME, EMPLOYER_FIELD) == [NEW_COMPANY]

    def test_the_second_models_reference_meets_the_kept_company(self, combined: Any) -> None:
        """The supplier's company was 7 in its file; the company of the first model is the one created"""
        assert self._targets(combined.document, SUPPLIER_NAME, SUPPLIER_FIELD) == [NEW_COMPANY]

    def test_a_reference_section_is_rewritten(self) -> None:
        """A reference section's type_id, like a field's targets"""
        document = second_model_document()
        supplier = component_items(document, TransferComponentName.TYPES)[1]
        supplier[TypeSchemaKey.RENDER_META.value][TypeSchemaKey.SECTIONS.value].append(
            {'type': 'ref-section', 'name': 'company-ref', 'label': 'Company', 'fields': [],
             'reference': {'type_id': 7, 'section_name': 'information'}})

        combined = combine_models([_first(), _second(document)])
        kept = _by_name(combined.document, TransferComponentName.TYPES, TypeSchemaKey.NAME.value)[SUPPLIER_NAME]

        assert kept[TypeSchemaKey.RENDER_META.value][TypeSchemaKey.SECTIONS.value][-1]['reference']['type_id'] \
            == NEW_COMPANY

    def test_a_category_parent_is_rewritten(self) -> None:
        """A sub-category of the second model points at the combined parent"""
        document = second_model_document()
        _raw_items(document, TransferComponentName.CATEGORIES).append({
            CategoryKey.PUBLIC_ID.value: 9, CategoryKey.NAME.value: OTHER_CATEGORY, CategoryKey.LABEL.value: 'Sub',
            CategoryKey.META.value: {CategoryMetaKey.ICON.value: '', CategoryMetaKey.ORDER.value: 1},
            CategoryKey.PARENT.value: 3, CategoryKey.TYPES.value: [],
        })

        combined = combine_models([_first(), _second(document)])
        sub = _by_name(combined.document, TransferComponentName.CATEGORIES, CategoryKey.NAME.value)[OTHER_CATEGORY]

        assert (sub[CategoryKey.PUBLIC_ID.value], sub[CategoryKey.PARENT.value]) == (2, 1)


class TestTheFirstModelWins:
    """What is not compared is taken from the first model in card order"""

    def test_the_type_keeps_the_first_icon_and_description(self, combined: Any) -> None:
        """The second model's company is dropped whole"""
        company = _by_name(combined.document, TransferComponentName.TYPES, TypeSchemaKey.NAME.value)[COMPANY_NAME]

        assert company[TypeSchemaKey.RENDER_META.value][TypeSchemaKey.ICON.value] != SECOND_COMPANY_ICON
        assert company.get(TypeSchemaKey.DESCRIPTION.value) != SECOND_COMPANY_DESCRIPTION

    def test_the_category_keeps_the_first_meta(self, combined: Any) -> None:
        """Icon and order of the first model's category"""
        category = _items(combined.document, TransferComponentName.CATEGORIES)[0]

        assert category[CategoryKey.META.value][CategoryMetaKey.ICON.value] != SECOND_CATEGORY_ICON

    def test_the_category_description_is_the_first_models(self, combined: Any) -> None:
        """In the meta and in the file's meta section"""
        section = combined.document[TransferFileKey.META.value][BestPracticeMetaKey.CATEGORY_DESCRIPTIONS.value]

        assert combined.meta.category_descriptions == section == {CONTACT_NAME: CONTACT_DESCRIPTION}
        assert SECOND_CATEGORY_DESCRIPTION not in section.values()


class TestTheCombinedFile:
    """A file the configuration import takes"""

    def test_its_envelope_is_accepted(self, combined: Any) -> None:
        """Counts match the entries, every key there"""
        assert not find_transfer_file_problems(combined.document, TRANSFER_COMPONENT_NAMES)

    def test_every_id_resolves_inside_it(self, combined: Any) -> None:
        """No reference, category entry or relation side names a missing type"""
        assert not find_preview_problems(combined.document, combined.meta)

    def test_its_information_names_the_models(self, combined: Any) -> None:
        """The titles joined, the ids in the description"""
        information = combined.document[TransferFileKey.INFORMATION.value]

        assert information[TransferInformationKey.NAME.value] == 'Fixture model + Second fixture model'
        assert information[TransferInformationKey.DESCRIPTION.value] == COMBINED_DESCRIPTION.format(
            model_ids=f'{FIRST_ID}, {SECOND_ID}')

    def test_the_models_are_not_changed(self) -> None:
        """The catalogue keeps its documents"""
        first, second = _first(), _second()
        loaded = deepcopy((first.document, second.document))

        combine_models([first, second])

        assert (first.document, second.document) == loaded


class TestConflicts:
    """Every conflict is collected; none raises"""

    def test_a_differing_type_is_named_with_its_models_and_parts(self) -> None:
        """The company's field label differs"""
        combined = combine_models([_first(), _second(second_model_document(company_field_label=OTHER_LABEL))])

        assert combined.conflicts == (ENTRY_DIFFERS.format(
            kind=CombinedEntryKind.TYPE.value, name=COMPANY_NAME, first=FIRST_ID, other=SECOND_ID,
            parts=TypeSchemaKey.FIELDS.value),)

    def test_a_differing_category_label(self) -> None:
        """Label and parent are compared"""
        document = second_model_document()
        component_items(document, TransferComponentName.CATEGORIES)[0][CategoryKey.LABEL.value] = 'Contacts'

        assert combine_models([_first(), _second(document)]).conflicts == (ENTRY_DIFFERS.format(
            kind=CombinedEntryKind.CATEGORY.value, name=CONTACT_NAME, first=FIRST_ID, other=SECOND_ID,
            parts=CategoryKey.LABEL.value),)

    def test_a_type_in_two_categories(self) -> None:
        """The second model files the shared company under a category of its own"""
        document = second_model_document()
        component_items(document, TransferComponentName.CATEGORIES)[0][CategoryKey.NAME.value] = OTHER_CATEGORY

        # The second model's meta still describes the renamed category - a problem of its own, named too
        assert TYPE_IN_TWO_CATEGORIES.format(
            name=COMPANY_NAME, first_category=CONTACT_NAME, first=FIRST_ID, other_category=OTHER_CATEGORY,
            other=SECOND_ID) in combine_models([_first(), _second(document)]).conflicts

    def test_a_models_unresolved_id(self) -> None:
        """An id naming no type of its own file would be rewritten to nothing"""
        document = second_model_document()
        supplier = component_items(document, TransferComponentName.TYPES)[1]
        supplier[TypeSchemaKey.FIELDS.value][0][FieldKey.REF_TYPES.value] = [99]

        conflicts = combine_models([_first(), _second(document)]).conflicts

        assert len(conflicts) == 1 and conflicts[0].startswith(MODEL_PROBLEM.format(model_id=SECOND_ID, problem=''))

    def test_section_templates_of_one_name(self) -> None:
        """Identical: created once; different: a conflict"""
        template = {SectionTemplateKey.PUBLIC_ID.value: 1, SectionTemplateKey.NAME.value: TEMPLATE_NAME,
                    SectionTemplateKey.LABEL.value: 'Template', SectionTemplateKey.FIELDS.value: [],
                    SectionTemplateKey.IS_GLOBAL.value: False, SectionTemplateKey.PREDEFINED.value: False,
                    SectionTemplateKey.TYPE.value: 'section'}
        first, second = model_document(), second_model_document()
        _raw_items(first, TransferComponentName.SECTION_TEMPLATES).append(template)
        _raw_items(second, TransferComponentName.SECTION_TEMPLATES).append(
            {**template, SectionTemplateKey.PUBLIC_ID.value: 5})

        combined = combine_models([_model(FIRST_ID, first, model_meta()), _second(second)])
        templates = _items(combined.document, TransferComponentName.SECTION_TEMPLATES)

        assert [(item[SectionTemplateKey.PUBLIC_ID.value], item[SectionTemplateKey.NAME.value])
                for item in templates] == [(1, TEMPLATE_NAME)]
        assert combined.merged[TransferComponentName.SECTION_TEMPLATES.value] == (TEMPLATE_NAME,)

        component_items(second, TransferComponentName.SECTION_TEMPLATES)[0][SectionTemplateKey.LABEL.value] = 'Other'

        assert combine_models([_model(FIRST_ID, first, model_meta()), _second(second)]).conflicts == (
            ENTRY_DIFFERS.format(kind=CombinedEntryKind.SECTION_TEMPLATE.value, name=TEMPLATE_NAME, first=FIRST_ID,
                                 other=SECOND_ID, parts=SectionTemplateKey.LABEL.value),)

    def test_a_relation_of_one_name_that_differs(self) -> None:
        """The second model's supplies is renamed to the first's relation"""
        document = second_model_document()
        component_items(document, TransferComponentName.RELATIONS)[0][RelationKey.RELATION_NAME.value] = \
            RELATION_NAME

        conflicts = combine_models([_first(), _second(document)]).conflicts

        assert conflicts == (ENTRY_DIFFERS.format(
            kind=CombinedEntryKind.RELATION.value, name=RELATION_NAME, first=FIRST_ID, other=SECOND_ID,
            parts=', '.join([RelationKey.CHILD_TYPE_IDS.value, RelationKey.RELATION_NAME_CHILD.value,
                             RelationKey.RELATION_NAME_PARENT.value])),)


class TestRemapIds:
    """`remap_ids` keeps the stored shape"""

    OLD: dict[int, str] = {7: 'a', 8: 'b'}
    NEW: dict[str, int] = {'a': 1, 'b': 2}

    @pytest.mark.parametrize('value, expected', [
        (7, 1), ([7, 8], [1, 2]), ([7, [8]], [1, [2]]), (None, None), (99, 99), (True, True), ('7', '7'),
    ])
    def test_shapes(self, value: Any, expected: Any) -> None:
        """One id, a list, a nested list; anything else and an unknown id as they are"""
        assert remap_ids(value, self.OLD, self.NEW) == expected
