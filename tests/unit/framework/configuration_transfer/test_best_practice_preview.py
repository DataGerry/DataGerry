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
Unit tests for the best-practice model preview (``best_practice_preview``)

One fixture model holds every shape the screens show - ordered, unordered and nested categories, a type no category
holds, plain, multi-data and reference sections, reference fields in both stored forms, a licensed SpecialType, a
port-bearing type and a relation - with a distinct value per document, so a swapped key or a wrong lookup shows. The
consistency check is driven by breaking one reference at a time, and the bundled models are checked to be consistent
"""
from typing import Any

import pytest

from cmdb.framework.configuration_transfer.best_practice_catalogue import (
    BestPracticeMeta,
    get_best_practice_catalogue,
)
from cmdb.framework.configuration_transfer.best_practice_constants import (
    UNKNOWN_CATEGORY_TYPE,
    UNKNOWN_DESCRIBED_CATEGORY,
    UNKNOWN_FIELD_TARGET,
    UNKNOWN_RELATION_SIDE,
    UNKNOWN_SECTION_TARGET,
)
from cmdb.framework.configuration_transfer.best_practice_preview import (
    CategoryPreview,
    FieldPreview,
    PreviewCounts,
    RelationPreview,
    SectionPreview,
    TypeRef,
    as_id_list,
    build_model_preview,
    component_items,
    find_preview_problems,
    required_features,
)
from cmdb.framework.configuration_transfer.configuration_transfer_constants import (
    TransferComponentName,
    TransferFileKey,
)
from cmdb.framework.configuration_transfer.transfer_components import TRANSFER_COMPONENT_NAMES
from cmdb.framework.configuration_transfer.transfer_file import build_component_section, build_transfer_file
from cmdb.models.category_model.category_constants import CategoryKey, CategoryMetaKey
from cmdb.models.relation_model.relation_constants import RelationKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model import TypeSchemaKey
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.section_key_enum import SectionKey
from cmdb.models.type_model.section_reference_key_enum import SectionReferenceKey
from cmdb.models.type_model.section_type_enum import SectionType
from cmdb.security.license.license_constants import LicenseFeature
# -------------------------------------------------------------------------------------------------------------------- #

DB_VERSION: int = 20261021

COMPANY_ID: int = 11
CUSTOMER_ID: int = 12
SUPERNET_ID: int = 13
SWITCH_ID: int = 14
BRANCH_ID: int = 15
LOOSE_ID: int = 16
UNKNOWN_ID: int = 99

CONTACT_ID: int = 21
NETWORK_ID: int = 22
SITES_ID: int = 23
CONTACT_ORDER: int = 2
NETWORK_ORDER: int = 1

COMPANY_NAME, CUSTOMER_NAME, SUPERNET_NAME = 'company', 'customer_user', 'supernet'
SWITCH_NAME, BRANCH_NAME, LOOSE_NAME = 'switch', 'branch', 'loose'
CONTACT_NAME, NETWORK_NAME, SITES_NAME = 'contact', 'network', 'sites'
CONTACT_DESCRIPTION: str = 'People and organizations that use or own assets'

COMPANY_TYPE: TypeRef = TypeRef(COMPANY_NAME, 'Company')
CUSTOMER_TYPE: TypeRef = TypeRef(CUSTOMER_NAME, 'Customer User')

ADDRESS_SECTION: str = 'address'
RELATION_NAME: str = 'works_for'


def _field(name: str, label: str | None = None, kind: FieldType = FieldType.TEXT, **extra: Any) -> dict[str, Any]:
    """A field definition; no label stores none"""
    field: dict[str, Any] = {FieldKey.TYPE.value: kind.value, FieldKey.NAME.value: name, **extra}

    if label is not None:
        field[FieldKey.LABEL.value] = label

    return field


def _section(name: str, fields: list[str], kind: SectionType = SectionType.SECTION, **extra: Any) -> dict[str, Any]:
    """A section of a type's render_meta"""
    return {SectionKey.TYPE.value: kind.value, SectionKey.NAME.value: name, SectionKey.LABEL.value: name.title(),
            SectionKey.FIELDS.value: fields, **extra}


def _type(public_id: int, name: str, label: str | None, fields: list[dict[str, Any]],
          sections: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    """A type document as an export stores it"""
    doc: dict[str, Any] = {
        TypeSchemaKey.PUBLIC_ID.value: public_id, TypeSchemaKey.NAME.value: name,
        TypeSchemaKey.FIELDS.value: fields,
        TypeSchemaKey.RENDER_META.value: {TypeSchemaKey.SECTIONS.value: sections}, **extra,
    }

    if label is not None:
        doc[TypeSchemaKey.LABEL.value] = label

    return doc


def _category(public_id: int, name: str, types: list[int], order: int | None = None,
              parent: int | None = None) -> dict[str, Any]:
    """A category document"""
    return {
        CategoryKey.PUBLIC_ID.value: public_id, CategoryKey.NAME.value: name, CategoryKey.LABEL.value: name.upper(),
        CategoryKey.META.value: {CategoryMetaKey.ORDER.value: order}, CategoryKey.PARENT.value: parent,
        CategoryKey.TYPES.value: types,
    }


def _types() -> list[dict[str, Any]]:
    """Every type of the fixture model"""
    return [
        _type(COMPANY_ID, COMPANY_NAME, COMPANY_TYPE.label,
              [_field('name', 'Name'), _field('street', 'Street'), _field('city')],
              [_section('information', ['name']), _section(ADDRESS_SECTION, ['street', 'city', 'undeclared'])],
              description='An organization'),
        _type(CUSTOMER_ID, CUSTOMER_NAME, CUSTOMER_TYPE.label,
              [_field('name', 'Name'), _field('employer', 'Company', FieldType.REFERENCE, ref_types=[COMPANY_ID]),
               _field('manager', 'Manager', FieldType.REFERENCE, ref_types=CUSTOMER_ID)],
              [_section('information', ['name', 'employer', 'manager'])]),
        _type(SUPERNET_ID, SUPERNET_NAME, 'Supernet', [_field('network', 'Network')],
              [_section('information', ['network'])], special_type=SpecialType.SUPERNET.value),
        _type(SWITCH_ID, SWITCH_NAME, 'Switch',
              [_field('name', 'Name'), _field('vlan', 'VLAN'), _field('port', 'Port')],
              [_section('information', ['name']), _section('vlans', ['vlan', 'port'], SectionType.MDS_SECTION)],
              uses_ports=True),
        _type(BRANCH_ID, BRANCH_NAME, None,
              [_field('company-address', 'Company address', FieldType.REF_SECTION, ref_types=[COMPANY_ID])],
              [_section('company-address', ['company-address'], SectionType.REF_SECTION, reference={
                  SectionReferenceKey.TYPE_ID.value: COMPANY_ID,
                  SectionReferenceKey.SECTION_NAME.value: ADDRESS_SECTION,
                  SectionReferenceKey.SELECTED_FIELDS.value: [],
              })]),
        _type(LOOSE_ID, LOOSE_NAME, 'Loose', [], []),
    ]


def _categories() -> list[dict[str, Any]]:
    """Every category: two ordered, one nested without an order"""
    return [
        _category(CONTACT_ID, CONTACT_NAME, [CUSTOMER_ID, COMPANY_ID], order=CONTACT_ORDER),
        _category(NETWORK_ID, NETWORK_NAME, [SWITCH_ID, SUPERNET_ID], order=NETWORK_ORDER),
        _category(SITES_ID, SITES_NAME, [BRANCH_ID], parent=CONTACT_ID),
    ]


def _relations() -> list[dict[str, Any]]:
    """One relation: a customer user works for a company"""
    return [{
        RelationKey.PUBLIC_ID.value: 31, RelationKey.RELATION_NAME.value: RELATION_NAME,
        RelationKey.DESCRIPTION.value: 'Who works where', RelationKey.RELATION_NAME_PARENT.value: 'employs',
        RelationKey.RELATION_NAME_CHILD.value: 'works for', RelationKey.PARENT_TYPE_IDS.value: [COMPANY_ID],
        RelationKey.CHILD_TYPE_IDS.value: [CUSTOMER_ID], RelationKey.FIELDS.value: [_field('since', 'Since')],
    }]


def _document(types: list[dict[str, Any]] | None = None, categories: list[dict[str, Any]] | None = None,
              relations: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The fixture model's transfer file - each component replaceable"""
    items: dict[str, list[dict[str, Any]]] = {
        TransferComponentName.SECTION_TEMPLATES.value: [],
        TransferComponentName.TYPES.value: _types() if types is None else types,
        TransferComponentName.CATEGORIES.value: _categories() if categories is None else categories,
        TransferComponentName.RELATIONS.value: _relations() if relations is None else relations,
    }

    return build_transfer_file(DB_VERSION, {name: build_component_section(len(items[name]), items[name])
                                            for name in TRANSFER_COMPONENT_NAMES})


def _meta(category_descriptions: dict[str, str] | None = None) -> BestPracticeMeta:
    """A description naming the contact category"""
    return BestPracticeMeta(
        title='Fixture', badge='Test', summary='Summary', description='Description', suited_for=(), profiles=(),
        category_descriptions={CONTACT_NAME: CONTACT_DESCRIPTION} if category_descriptions is None
        else category_descriptions,
        order=0,
    )


def _type_preview(type_name: str) -> Any:
    """One type of the fixture model's preview, wherever it is listed"""
    preview = build_model_preview(_document(), _meta())
    types = [type_ for category in preview.categories for type_ in category.types] + list(preview.uncategorized)

    return next(type_ for type_ in types if type_.name == type_name)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                     the counts                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def test_the_counts_are_what_the_import_creates() -> None:
    """Every category, type, declared field (multi-data and reference-section fields included) and relation"""
    assert build_model_preview(_document(), _meta()).counts == PreviewCounts(
        categories=3, types=6, fields=3 + 3 + 1 + 3 + 1 + 0, relations=1,
    )


def test_an_empty_model_counts_nothing() -> None:
    """No types, categories or relations"""
    preview = build_model_preview(_document(types=[], categories=[], relations=[]), _meta())

    assert preview.counts == PreviewCounts(0, 0, 0, 0)
    assert (preview.categories, preview.uncategorized, preview.relations, preview.required_features) == ((), (), (), ())


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    the categories                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCategories:
    """The categories with their types, in category order"""

    def test_ordered_categories_come_first_by_order_the_rest_by_name(self) -> None:
        """network (1), contact (2), then sites, which stores no order"""
        preview = build_model_preview(_document(), _meta())

        assert [category.name for category in preview.categories] == [NETWORK_NAME, CONTACT_NAME, SITES_NAME]

    def test_a_category_carries_its_description_parent_and_types_in_its_order(self) -> None:
        """The description from the description file; the parent by name; the types as the category lists them"""
        preview = build_model_preview(_document(), _meta())
        contact, sites = preview.categories[1], preview.categories[2]

        assert (contact.label, contact.description, contact.parent) == (CONTACT_NAME.upper(), CONTACT_DESCRIPTION, None)
        assert [type_.name for type_ in contact.types] == [CUSTOMER_NAME, COMPANY_NAME]
        assert (sites.description, sites.parent) == (None, CONTACT_NAME)

    def test_a_type_id_the_model_does_not_hold_is_left_out(self) -> None:
        """No KeyError; the consistency check names it"""
        categories = [_category(CONTACT_ID, CONTACT_NAME, [UNKNOWN_ID, COMPANY_ID])]

        preview = build_model_preview(_document(categories=categories), _meta())

        assert preview.categories == (CategoryPreview(
            CONTACT_NAME, CONTACT_NAME.upper(), CONTACT_DESCRIPTION, None, (_type_preview(COMPANY_NAME),),
        ),)

    def test_a_type_no_category_holds_is_uncategorized(self) -> None:
        """Only the loose type"""
        assert [type_.name for type_ in build_model_preview(_document(), _meta()).uncategorized] == [LOOSE_NAME]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 types, sections, fields                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTypes:
    """One type: its own values, its sections in order, the fields each names"""

    def test_a_type_carries_its_values(self) -> None:
        """Name, label, description, field count"""
        company = _type_preview(COMPANY_NAME)

        assert (company.label, company.description, company.special_type, company.field_count) == (
            COMPANY_TYPE.label, 'An organization', None, 3)

    def test_the_label_falls_back_to_the_name(self) -> None:
        """A type and a field without a label"""
        branch = _type_preview(BRANCH_NAME)

        assert branch.label == BRANCH_NAME
        assert _type_preview(COMPANY_NAME).sections[1].fields[1].label == 'city'

    def test_a_section_shows_its_fields_in_its_order_and_skips_an_undeclared_name(self) -> None:
        """'undeclared' is named by the section but declared by no field"""
        address = _type_preview(COMPANY_NAME).sections[1]

        assert address == SectionPreview(ADDRESS_SECTION, ADDRESS_SECTION.title(), SectionType.SECTION.value, (
            FieldPreview('street', 'Street', FieldType.TEXT.value, ()),
            FieldPreview('city', 'city', FieldType.TEXT.value, ()),
        ), None)

    def test_reference_targets_resolve_in_both_stored_forms(self) -> None:
        """`ref_types` as a list and as one id"""
        fields = _type_preview(CUSTOMER_NAME).sections[0].fields

        assert fields[1] == FieldPreview('employer', 'Company', FieldType.REFERENCE.value, (COMPANY_TYPE,))
        assert fields[2].targets == (CUSTOMER_TYPE,)

    def test_a_multi_data_section_keeps_its_kind(self) -> None:
        """The screens tell the row sections apart"""
        vlans = _type_preview(SWITCH_NAME).sections[1]

        assert (vlans.section_type, [field.name for field in vlans.fields]) == (
            SectionType.MDS_SECTION.value, ['vlan', 'port'])

    def test_a_reference_section_names_the_type_it_pulls_from(self) -> None:
        """And its field targets that type too"""
        section = _type_preview(BRANCH_NAME).sections[0]

        assert section.referenced_type == COMPANY_TYPE
        assert section.fields[0].targets == (COMPANY_TYPE,)

    def test_a_target_the_model_does_not_hold_is_left_out(self) -> None:
        """No KeyError; the consistency check names it"""
        types = [_type(CUSTOMER_ID, CUSTOMER_NAME, CUSTOMER_TYPE.label,
                       [_field('employer', 'Company', FieldType.REFERENCE, ref_types=[UNKNOWN_ID, CUSTOMER_ID])],
                       [_section('information', ['employer'])])]

        preview = build_model_preview(_document(types=types, categories=[], relations=[]), _meta())

        assert preview.uncategorized[0].sections[0].fields[0].targets == (CUSTOMER_TYPE,)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                     relations                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def test_a_relation_names_both_sides() -> None:
    """Its labels, both sides resolved, its own field count"""
    assert build_model_preview(_document(), _meta()).relations == (RelationPreview(
        RELATION_NAME, 'Who works where', 'employs', 'works for', (COMPANY_TYPE,), (CUSTOMER_TYPE,), 1,
    ),)


def test_relations_are_listed_by_name() -> None:
    """Whatever order the file holds them in"""
    second = {**_relations()[0], RelationKey.RELATION_NAME.value: 'assigned_to'}

    preview = build_model_preview(_document(relations=[_relations()[0], second]), _meta())

    assert [relation.name for relation in preview.relations] == ['assigned_to', RELATION_NAME]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    licences                                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class TestRequiredFeatures:
    """What the type routes would refuse without a licence"""

    @pytest.mark.parametrize('extra', [
        {TypeSchemaKey.SPECIAL_TYPE.value: SpecialType.SUPERNET.value},
        {TypeSchemaKey.SPECIAL_TYPE.value: SpecialType.RACK.value},
        {TypeSchemaKey.USES_PORTS.value: True},
    ], ids=['ipam-type', 'rack', 'ports'])
    def test_a_licensed_type_needs_ipam(self, extra: dict[str, Any]) -> None:
        """A gated SpecialType or a port-bearing type"""
        assert required_features([{TypeSchemaKey.NAME.value: LOOSE_NAME, **extra}]) == (LicenseFeature.IPAM.value,)

    @pytest.mark.parametrize('extra', [
        {}, {TypeSchemaKey.SPECIAL_TYPE.value: None}, {TypeSchemaKey.SPECIAL_TYPE.value: 'unknown'},
        {TypeSchemaKey.USES_PORTS.value: False}, {TypeSchemaKey.USES_PORTS.value: 'true'},
    ], ids=['plain', 'no-special-type', 'unknown-marker', 'no-ports', 'ports-as-text'])
    def test_an_ordinary_type_needs_nothing(self, extra: dict[str, Any]) -> None:
        """Only a real marker and a real True count"""
        assert not required_features([{TypeSchemaKey.NAME.value: LOOSE_NAME, **extra}])

    def test_the_fixture_model_needs_ipam_once(self) -> None:
        """Two licensed types, one feature"""
        assert build_model_preview(_document(), _meta()).required_features == (LicenseFeature.IPAM.value,)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                     robustness                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestUnexpectedShapes:
    """Anything that is not the stored shape reads as empty - a preview never fails the assistant"""

    @pytest.mark.parametrize('components', [None, [], {TransferComponentName.TYPES.value: 'no section'},
                                            {TransferComponentName.TYPES.value: {'items': 'no list'}}],
                             ids=['no-components', 'components-no-object', 'section-no-object', 'items-no-list'])
    def test_a_broken_envelope_has_no_items(self, components: Any) -> None:
        """No error, nothing to show"""
        assert not component_items({TransferFileKey.COMPONENTS.value: components}, TransferComponentName.TYPES)

    def test_odd_documents_are_skipped_and_odd_values_read_as_empty(self) -> None:
        """A non-document item, fields and sections that are no lists, a section's fields that are no names"""
        types = ['not a type', {TypeSchemaKey.PUBLIC_ID.value: LOOSE_ID, TypeSchemaKey.FIELDS.value: 'none',
                                TypeSchemaKey.RENDER_META.value: {TypeSchemaKey.SECTIONS.value: [
                                    'not a section', {SectionKey.FIELDS.value: [7, None]}]}}]

        preview = build_model_preview(_document(types=types, categories=[], relations=[]), _meta())

        assert preview.counts.types == 1
        assert preview.uncategorized[0].field_count == 0
        assert preview.uncategorized[0].sections == (SectionPreview('', '', '', (), None),)

    @pytest.mark.parametrize('value, ids', [(5, [5]), ([5, 6], [5, 6]), (True, []), ([True, 5, '6'], [5]),
                                            (None, []), ('5', [])])
    def test_ids_are_whole_numbers_only(self, value: Any, ids: list[int]) -> None:
        """One id or a list of them; booleans and texts are none"""
        assert as_id_list(value) == ids


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    consistency                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestFindPreviewProblems:
    """What does not resolve inside the pair is named - every problem at once"""

    def test_a_consistent_model_has_none(self) -> None:
        """The fixture model"""
        assert not find_preview_problems(_document(), _meta())

    def test_a_description_for_a_missing_category(self) -> None:
        """Named by the category"""
        problems = find_preview_problems(_document(), _meta({CONTACT_NAME: CONTACT_DESCRIPTION, 'printers': 'x'}))

        assert problems == [UNKNOWN_DESCRIBED_CATEGORY.format(name='printers')]

    def test_a_field_target_the_model_does_not_hold(self) -> None:
        """Named by field, type and id"""
        types = [_type(CUSTOMER_ID, CUSTOMER_NAME, None,
                       [_field('employer', None, FieldType.REFERENCE, ref_types=UNKNOWN_ID)], [])]

        assert find_preview_problems(_document(types=types, categories=[], relations=[]), _meta({})) == [
            UNKNOWN_FIELD_TARGET.format(field='employer', type=CUSTOMER_NAME, target=UNKNOWN_ID)]

    def test_a_reference_section_to_a_missing_type(self) -> None:
        """Named by section, type and id"""
        types = [_type(BRANCH_ID, BRANCH_NAME, None, [], [_section('linked', [], SectionType.REF_SECTION, reference={
            SectionReferenceKey.TYPE_ID.value: UNKNOWN_ID})])]

        assert find_preview_problems(_document(types=types, categories=[], relations=[]), _meta({})) == [
            UNKNOWN_SECTION_TARGET.format(section='linked', type=BRANCH_NAME, target=UNKNOWN_ID)]

    def test_a_relation_side_the_model_does_not_hold(self) -> None:
        """Either side"""
        relations = [{**_relations()[0], RelationKey.CHILD_TYPE_IDS.value: [UNKNOWN_ID]}]

        assert find_preview_problems(_document(relations=relations), _meta()) == [
            UNKNOWN_RELATION_SIDE.format(relation=RELATION_NAME, target=UNKNOWN_ID)]

    def test_a_category_entry_the_model_does_not_hold(self) -> None:
        """Named by category and id"""
        categories = [_category(CONTACT_ID, CONTACT_NAME, [UNKNOWN_ID])]

        assert find_preview_problems(_document(categories=categories), _meta()) == [
            UNKNOWN_CATEGORY_TYPE.format(category=CONTACT_NAME, target=UNKNOWN_ID)]

    def test_every_problem_is_named_at_once(self) -> None:
        """An author sees them together"""
        categories = [_category(CONTACT_ID, CONTACT_NAME, [UNKNOWN_ID])]
        relations = [{**_relations()[0], RelationKey.PARENT_TYPE_IDS.value: [UNKNOWN_ID]}]

        assert len(find_preview_problems(_document(categories=categories, relations=relations),
                                         _meta({CONTACT_NAME: CONTACT_DESCRIPTION, 'printers': 'x'}))) == 3


def test_every_bundled_model_is_consistent_and_previews() -> None:
    """A bundle whose references do not resolve fails here, before it ships"""
    for model in get_best_practice_catalogue().models:
        assert not find_preview_problems(model.document, model.meta), model.model_id
        assert build_model_preview(model.document, model.meta).counts.types >= 0
