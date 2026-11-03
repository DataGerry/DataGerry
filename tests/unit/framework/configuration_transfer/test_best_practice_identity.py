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
Unit tests for ``configuration_transfer.best_practice_identity`` - what two models' entries of one name are compared on

Pure: entries are dicts. Each test pins one rule: an ignored key does not make two entries differ, a compared one
does, ids are compared by the names they stand for in their own file, target lists as sets, field order counts
"""
from copy import deepcopy
from typing import Any

import pytest

from cmdb.framework.configuration_transfer.best_practice_constants import (
    RELATION_IGNORED_KEYS,
    TYPE_IGNORED_KEYS,
)
from cmdb.framework.configuration_transfer.best_practice_identity import (
    comparable_category,
    comparable_relation,
    comparable_section_template,
    comparable_type,
    differing_parts,
    is_id,
    names_by_id,
)
from cmdb.models.category_model.category_constants import CategoryKey, CategoryMetaKey
from cmdb.models.relation_model.relation_constants import RelationKey
from cmdb.models.section_template_model.section_template_constants import SectionTemplateKey
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.section_key_enum import SectionKey
from cmdb.models.type_model.section_reference_key_enum import SectionReferenceKey
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
# -------------------------------------------------------------------------------------------------------------------- #

COMPANY: str = 'company'
SITE: str = 'site'
# The same two types under the ids each of two files gives them
FIRST_NAMES: dict[int, str] = {1: COMPANY, 2: SITE}
OTHER_NAMES: dict[int, str] = {10: COMPANY, 20: SITE}
FIELD_NAME: str = 'company-name'
REF_FIELD: str = 'company-site'
SECTIONS: str = TypeSchemaKey.SECTIONS.value
RENDER_META: str = TypeSchemaKey.RENDER_META.value
FIELDS: str = TypeSchemaKey.FIELDS.value


def _type(site_id: int, public_id: int = 1, **overrides: Any) -> dict[str, Any]:
    """A type with a text field, a reference field to the site and a reference section to the site"""
    item: dict[str, Any] = {
        TypeSchemaKey.PUBLIC_ID.value: public_id,
        TypeSchemaKey.NAME.value: COMPANY,
        TypeSchemaKey.LABEL.value: 'Company',
        FIELDS: [
            {FieldKey.TYPE.value: 'text', FieldKey.NAME.value: FIELD_NAME, FieldKey.LABEL.value: 'Name'},
            {FieldKey.TYPE.value: 'ref', FieldKey.NAME.value: REF_FIELD, FieldKey.LABEL.value: 'Site',
             FieldKey.REF_TYPES.value: [site_id]},
        ],
        RENDER_META: {
            TypeSchemaKey.ICON.value: 'fa-building',
            SECTIONS: [
                {SectionKey.TYPE.value: 'section', SectionKey.NAME.value: 'info', SectionKey.LABEL.value: 'Info',
                 SectionKey.FIELDS.value: [FIELD_NAME, REF_FIELD]},
                {SectionKey.TYPE.value: 'ref-section', SectionKey.NAME.value: 'site-ref',
                 SectionKey.LABEL.value: 'Site', SectionKey.FIELDS.value: [],
                 SectionKey.REFERENCE.value: {SectionReferenceKey.TYPE_ID.value: site_id,
                                              SectionReferenceKey.SECTION_NAME.value: 'info'}},
            ],
            TypeSchemaKey.SUMMARY.value: {FIELDS: [FIELD_NAME]},
        },
        TypeSchemaKey.SPECIAL_TYPE.value: '',
    }
    item.update(overrides)
    return item


def _parts_between_types(first: dict[str, Any], other: dict[str, Any]) -> list[str]:
    """What differs between the first file's type and the other file's"""
    return differing_parts(comparable_type(first, FIRST_NAMES), comparable_type(other, OTHER_NAMES))


class TestIds:
    """`is_id` and `names_by_id`"""

    @pytest.mark.parametrize('value, expected', [(1, True), (0, True), (True, False), ('1', False), (None, False)])
    def test_only_a_whole_number_is_an_id(self, value: Any, expected: bool) -> None:
        """A bool is an int to Python, not an id to us"""
        assert is_id(value) is expected

    def test_names_by_id_reads_each_entry_once(self) -> None:
        """An entry without an id is left out"""
        items = [{TypeSchemaKey.PUBLIC_ID.value: 3, TypeSchemaKey.NAME.value: COMPANY},
                 {TypeSchemaKey.NAME.value: SITE}]

        assert names_by_id(items, TypeSchemaKey.NAME.value) == {3: COMPANY}


class TestComparableType:
    """Two types of one name from two files"""

    def test_the_same_type_under_other_ids_is_equal(self) -> None:
        """Every id is read as the name it stands for in its own file"""
        assert not _parts_between_types(_type(2), _type(20, public_id=10))

    @pytest.mark.parametrize('key', sorted(TYPE_IGNORED_KEYS))
    def test_an_ignored_key_never_differs(self, key: str) -> None:
        """Bookkeeping, the ACL and the description are not what makes a type"""
        assert not _parts_between_types(_type(2, **{key: 'first'}), _type(20, **{key: 'other'}))

    def test_the_icon_never_differs(self) -> None:
        """The first model's icon wins"""
        other = _type(20)
        other[RENDER_META][TypeSchemaKey.ICON.value] = 'fa-other'

        assert not _parts_between_types(_type(2), other)

    def test_a_field_label_differs_as_fields(self) -> None:
        """Every field setting is compared"""
        other = _type(20)
        other[FIELDS][0][FieldKey.LABEL.value] = 'Company name'

        assert _parts_between_types(_type(2), other) == [FIELDS]

    def test_the_field_order_differs(self) -> None:
        """The order is what a user sees"""
        other = _type(20)
        other[FIELDS].reverse()

        assert _parts_between_types(_type(2), other) == [FIELDS]

    def test_a_reference_to_another_type_differs(self) -> None:
        """The same id, but it names the company in the other file, not the site"""
        assert _parts_between_types(_type(2), _type(10)) == [FIELDS, f'{RENDER_META}.{SECTIONS}']

    def test_targets_are_compared_as_a_set(self) -> None:
        """Which types a field may reference matters, not in which order it lists them"""
        first, other = _type(2), _type(20)
        first[FIELDS][1][FieldKey.REF_TYPES.value] = [1, 2]
        other[FIELDS][1][FieldKey.REF_TYPES.value] = [20, [10]]

        assert not _parts_between_types(first, other)

    def test_a_section_change_is_named_inside_render_meta(self) -> None:
        """The nested key, so a message can say what to look at"""
        other = _type(20)
        other[RENDER_META][SECTIONS][0][SectionKey.LABEL.value] = 'Information'

        assert _parts_between_types(_type(2), other) == [f'{RENDER_META}.{SECTIONS}']

    @pytest.mark.parametrize('key, value', [
        (TypeSchemaKey.LABEL.value, 'Firm'),
        (TypeSchemaKey.SPECIAL_TYPE.value, 'SUPERNET'),
        (TypeSchemaKey.USES_PORTS.value, True),
        (TypeSchemaKey.GLOBAL_TEMPLATE_IDS.value, ['dg-tpl']),
    ])
    def test_a_compared_key_differs(self, key: str, value: Any) -> None:
        """A key that is not ignored - also when only one of them has it"""
        assert _parts_between_types(_type(2), _type(20, **{key: value})) == [key]

    def test_the_entry_is_not_changed(self) -> None:
        """The comparable is a copy"""
        item = _type(2)
        loaded = deepcopy(item)

        comparable_type(item, FIRST_NAMES)

        assert item == loaded

    def test_a_type_without_render_meta(self) -> None:
        """Nothing to strip or rewrite there - a missing render_meta on one side differs"""
        first = {key: value for key, value in _type(2).items() if key != RENDER_META}

        assert not differing_parts(comparable_type(first, FIRST_NAMES), comparable_type(dict(first), FIRST_NAMES))
        assert _parts_between_types(first, _type(20)) == [RENDER_META]

    def test_an_unknown_id_only_equals_itself(self) -> None:
        """An id the file does not hold is compared as itself"""
        assert not _parts_between_types(_type(99), _type(99))
        assert _parts_between_types(_type(99), _type(98)) == [FIELDS, f'{RENDER_META}.{SECTIONS}']


class TestComparableRelation:
    """Two relations of one name"""

    @staticmethod
    def _relation(parent: list[int], child: list[int], **overrides: Any) -> dict[str, Any]:
        """A relation between the given sides"""
        return {RelationKey.PUBLIC_ID.value: 1, RelationKey.RELATION_NAME.value: 'located_at',
                RelationKey.PARENT_TYPE_IDS.value: parent, RelationKey.CHILD_TYPE_IDS.value: child,
                RelationKey.FIELDS.value: [], **overrides}

    def test_the_sides_are_compared_by_name_as_a_set(self) -> None:
        """Other ids, other order - the same types"""
        first = comparable_relation(self._relation([1, 2], [2]), FIRST_NAMES)
        other = comparable_relation(self._relation([20, 10], [20]), OTHER_NAMES)

        assert not differing_parts(first, other)

    def test_a_side_naming_another_type_differs(self) -> None:
        """The parent is the company in one file and the site in the other"""
        first = comparable_relation(self._relation([1], [2]), FIRST_NAMES)
        other = comparable_relation(self._relation([20], [20]), OTHER_NAMES)

        assert differing_parts(first, other) == [RelationKey.PARENT_TYPE_IDS.value]

    @pytest.mark.parametrize('key', sorted(RELATION_IGNORED_KEYS - {RelationKey.PUBLIC_ID.value}))
    def test_the_description_and_the_drawing_never_differ(self, key: str) -> None:
        """How a relation is described and drawn is the first model's"""
        first = comparable_relation(self._relation([1], [2], **{key: 'first'}), FIRST_NAMES)
        other = comparable_relation(self._relation([10], [20], **{key: 'other'}), OTHER_NAMES)

        assert not differing_parts(first, other)

    def test_a_missing_side_is_left_missing(self) -> None:
        """Only a side that is there is rewritten - one lacking it differs"""
        first = self._relation([1], [2])
        del first[RelationKey.CHILD_TYPE_IDS.value]

        assert RelationKey.CHILD_TYPE_IDS.value not in comparable_relation(first, FIRST_NAMES)
        assert differing_parts(comparable_relation(first, FIRST_NAMES),
                               comparable_relation(self._relation([10], [20]), OTHER_NAMES)) == [
            RelationKey.CHILD_TYPE_IDS.value]

    def test_its_fields_differ(self) -> None:
        """The relation's own fields are compared"""
        first = comparable_relation(self._relation([1], [2]), FIRST_NAMES)
        other = comparable_relation(self._relation([10], [20], fields=[{FieldKey.NAME.value: 'since'}]), OTHER_NAMES)

        assert differing_parts(first, other) == [RelationKey.FIELDS.value]


class TestComparableTemplateAndCategory:
    """Section templates on everything but their id; categories on their label and parent only"""

    def test_a_template_under_another_id_is_equal(self) -> None:
        """Only the id is ignored"""
        template = {SectionTemplateKey.PUBLIC_ID.value: 1, SectionTemplateKey.NAME.value: 'tpl',
                    SectionTemplateKey.FIELDS.value: []}

        assert not differing_parts(comparable_section_template(template),
                                   comparable_section_template({**template, SectionTemplateKey.PUBLIC_ID.value: 9}))

    def test_a_template_label_differs(self) -> None:
        """Everything else is compared"""
        template = {SectionTemplateKey.NAME.value: 'tpl', SectionTemplateKey.LABEL.value: 'A'}

        assert differing_parts(comparable_section_template(template), comparable_section_template(
            {**template, SectionTemplateKey.LABEL.value: 'B'})) == [SectionTemplateKey.LABEL.value]

    @staticmethod
    def _category(parent: int | None, label: str = 'Network', icon: str = 'fa-a') -> dict[str, Any]:
        """A category under a parent, holding a type"""
        return {CategoryKey.PUBLIC_ID.value: 5, CategoryKey.NAME.value: 'network', CategoryKey.LABEL.value: label,
                CategoryKey.PARENT.value: parent, CategoryKey.TYPES.value: [parent or 0],
                CategoryKey.META.value: {CategoryMetaKey.ICON.value: icon}}

    def test_a_category_is_its_label_and_its_parents_name(self) -> None:
        """Its types and its meta are not compared"""
        first = comparable_category(self._category(1), {1: 'infrastructure'})
        other = comparable_category(self._category(7, icon='fa-b'), {7: 'infrastructure'})

        assert first == {CategoryKey.LABEL.value: 'Network', CategoryKey.PARENT.value: 'infrastructure'}
        assert not differing_parts(first, other)

    def test_another_parent_or_label_differs(self) -> None:
        """Both are what a user sees in the tree"""
        first = comparable_category(self._category(1), {1: 'infrastructure'})
        other = comparable_category(self._category(7, label='Networks'), {7: 'locations'})

        assert differing_parts(first, other) == [CategoryKey.LABEL.value, CategoryKey.PARENT.value]

    def test_no_parent_stays_none(self) -> None:
        """A root category"""
        assert comparable_category(self._category(None), {})[CategoryKey.PARENT.value] is None
