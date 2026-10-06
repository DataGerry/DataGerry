# DATAGERRY - OpenSource Enterprise CMDB
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
Unit tests for cmdb.framework.section_templates.global_template_reconcile

A CmdbType's copy of a global section template is the template's. Pure tests over type documents: every way a copy
can drift (a field's label, kind or options rewritten, a field dropped, the field order, the section's label or
kind, a template field moved to another section, no section at all) comes back as the template's; a claim naming no
template is dropped with its data kept; a foreign field inside the template's section is a conflict; malformed
layouts are left to the structure rules
"""
from copy import deepcopy
from typing import Any
from unittest.mock import MagicMock

from cmdb.framework.section_templates.global_template_reconcile import (
    TemplateSectionConflict,
    claimed_template_names,
    first_template_conflict,
    reconcile_type_with_global_templates,
    resolve_global_templates,
)
# -------------------------------------------------------------------------------------------------------------------- #

TEMPLATE_NAME: str = 'dg-modelspec'
OTHER_TEMPLATE_NAME: str = 'dg-other'
OWN_FIELD: str = 'own-name'
TEMPLATE_FIELDS: list[dict[str, Any]] = [
    {'type': 'text', 'name': 'dg-modelspec-manufacturer', 'label': 'Manufacturer'},
    {'type': 'text', 'name': 'dg-modelspec-model', 'label': 'Model name'},
    {'type': 'select', 'name': 'dg-modelspec-kind', 'label': 'Kind', 'options': [{'name': 'a', 'label': 'A'}]},
]
TEMPLATE_FIELD_NAMES: list[str] = [field['name'] for field in TEMPLATE_FIELDS]
TEMPLATE: dict[str, Any] = {
    'name': TEMPLATE_NAME, 'label': 'Model specifications', 'type': 'section', 'is_global': True,
    'fields': TEMPLATE_FIELDS,
}
TEMPLATES: dict[str, dict[str, Any]] = {TEMPLATE_NAME: TEMPLATE}


def _faithful_type() -> dict[str, Any]:
    """A type document carrying an exact copy of the template next to a section of its own"""
    return {
        'name': 'server',
        'global_template_ids': [TEMPLATE_NAME],
        'fields': [{'type': 'text', 'name': OWN_FIELD, 'label': 'Name'}] + deepcopy(TEMPLATE_FIELDS),
        'render_meta': {'sections': [
            {'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [OWN_FIELD]},
            {'type': 'section', 'name': TEMPLATE_NAME, 'label': 'Model specifications',
             'fields': list(TEMPLATE_FIELD_NAMES)},
        ]},
    }


def _field(document: dict[str, Any], name: str) -> dict[str, Any]:
    """One field definition of the document"""
    return next(field for field in document['fields'] if field['name'] == name)


def _section(document: dict[str, Any], name: str) -> dict[str, Any]:
    """One section of the document"""
    return next(section for section in document['render_meta']['sections'] if section['name'] == name)


class TestAFaithfulCopy:
    """What the frontend sends is stored unchanged"""

    def test_nothing_changes(self) -> None:
        """No conflict, no dropped claim, the same document"""
        document = _faithful_type()

        outcome = reconcile_type_with_global_templates(document, TEMPLATES)

        assert document == _faithful_type()
        assert outcome.conflicts == [] and outcome.dropped_claims == []

    def test_a_type_without_claims_is_not_touched(self) -> None:
        """Nothing is claimed, nothing is reconciled - not even with templates at hand"""
        document = {'name': 'plain', 'fields': [], 'render_meta': {'sections': []}}

        reconcile_type_with_global_templates(document, TEMPLATES)

        assert document == {'name': 'plain', 'fields': [], 'render_meta': {'sections': []}}


class TestADriftedCopyIsTheTemplates:
    """Each way a copy drifts comes back as the template's"""

    def test_a_rewritten_label_is_replaced(self) -> None:
        """The field definition is the template's"""
        document = _faithful_type()
        _field(document, TEMPLATE_FIELD_NAMES[0])['label'] = 'HACKED'

        reconcile_type_with_global_templates(document, TEMPLATES)

        assert _field(document, TEMPLATE_FIELD_NAMES[0]) == TEMPLATE_FIELDS[0]

    def test_a_changed_kind_is_replaced(self) -> None:
        """A text field turned into a select is a text field again"""
        document = _faithful_type()
        _field(document, TEMPLATE_FIELD_NAMES[1]).update({'type': 'select', 'options': [{'name': 'x'}]})

        reconcile_type_with_global_templates(document, TEMPLATES)

        assert _field(document, TEMPLATE_FIELD_NAMES[1]) == TEMPLATE_FIELDS[1]

    def test_added_options_are_replaced(self) -> None:
        """A select keeps exactly the template's options"""
        document = _faithful_type()
        _field(document, TEMPLATE_FIELD_NAMES[2])['options'].append({'name': 'injected', 'label': 'Injected'})

        reconcile_type_with_global_templates(document, TEMPLATES)

        assert _field(document, TEMPLATE_FIELD_NAMES[2])['options'] == TEMPLATE_FIELDS[2]['options']

    def test_a_dropped_field_is_restored(self) -> None:
        """Its definition is added and the section lists it again"""
        document = _faithful_type()
        document['fields'] = [field for field in document['fields'] if field['name'] != TEMPLATE_FIELD_NAMES[2]]
        _section(document, TEMPLATE_NAME)['fields'].remove(TEMPLATE_FIELD_NAMES[2])

        reconcile_type_with_global_templates(document, TEMPLATES)

        assert _field(document, TEMPLATE_FIELD_NAMES[2]) == TEMPLATE_FIELDS[2]
        assert _section(document, TEMPLATE_NAME)['fields'] == TEMPLATE_FIELD_NAMES

    def test_the_section_takes_the_template_order_label_and_kind(self) -> None:
        """The layout of the section is the template's"""
        document = _faithful_type()
        section = _section(document, TEMPLATE_NAME)
        section.update({'label': 'MY LABEL', 'type': 'multi-data-section', 'fields': TEMPLATE_FIELD_NAMES[::-1]})

        reconcile_type_with_global_templates(document, TEMPLATES)

        assert _section(document, TEMPLATE_NAME) == {
            'type': 'section', 'name': TEMPLATE_NAME, 'label': 'Model specifications', 'fields': TEMPLATE_FIELD_NAMES,
        }

    def test_a_template_field_in_another_section_is_moved_back(self) -> None:
        """Listed once, in the template's section - the definition is untouched"""
        document = _faithful_type()
        _section(document, 'main')['fields'].append(TEMPLATE_FIELD_NAMES[0])
        _section(document, TEMPLATE_NAME)['fields'].remove(TEMPLATE_FIELD_NAMES[0])

        reconcile_type_with_global_templates(document, TEMPLATES)

        assert _section(document, 'main')['fields'] == [OWN_FIELD]
        assert _section(document, TEMPLATE_NAME)['fields'] == TEMPLATE_FIELD_NAMES

    def test_a_missing_section_is_built_from_the_template(self) -> None:
        """Appended at the end of the layout, with the template's fields"""
        document = _faithful_type()
        document['render_meta']['sections'] = [_section(document, 'main')]

        reconcile_type_with_global_templates(document, TEMPLATES)

        assert document['render_meta']['sections'][-1] == {
            'name': TEMPLATE_NAME, 'fields': TEMPLATE_FIELD_NAMES, 'type': 'section', 'label': 'Model specifications',
        }

    def test_the_own_fields_keep_their_place(self) -> None:
        """A replaced definition stays where it was in the field list"""
        document = _faithful_type()

        reconcile_type_with_global_templates(document, TEMPLATES)

        assert [field['name'] for field in document['fields']] == [OWN_FIELD] + TEMPLATE_FIELD_NAMES

    def test_the_stored_template_is_never_shared_with_the_type(self) -> None:
        """The definitions are copies - changing the type's afterwards leaves the template alone"""
        document = _faithful_type()
        template = deepcopy(TEMPLATE)

        reconcile_type_with_global_templates(document, {TEMPLATE_NAME: template})
        _field(document, TEMPLATE_FIELD_NAMES[2])['options'].append({'name': 'later'})

        assert template == TEMPLATE

    def test_an_mds_template_makes_an_mds_section(self) -> None:
        """The kind comes from the template"""
        mds_template = {**TEMPLATE, 'type': 'multi-data-section'}
        document = _faithful_type()

        reconcile_type_with_global_templates(document, {TEMPLATE_NAME: mds_template})

        assert _section(document, TEMPLATE_NAME)['type'] == 'multi-data-section'


class TestTheClaims:
    """global_template_ids after the reconcile"""

    def test_an_unknown_claim_is_dropped_and_its_data_kept(self) -> None:
        """No such template here: the type stops claiming it, the section and fields stay as its own data"""
        document = _faithful_type()
        document['global_template_ids'].append(OTHER_TEMPLATE_NAME)
        document['render_meta']['sections'].append({'type': 'section', 'name': OTHER_TEMPLATE_NAME, 'fields': []})

        outcome = reconcile_type_with_global_templates(document, TEMPLATES)

        assert document['global_template_ids'] == [TEMPLATE_NAME]
        assert outcome.dropped_claims == [OTHER_TEMPLATE_NAME]
        assert _section(document, OTHER_TEMPLATE_NAME) == {'type': 'section', 'name': OTHER_TEMPLATE_NAME, 'fields': []}

    def test_a_claim_listed_twice_is_kept_once(self) -> None:
        """And reconciled once"""
        document = _faithful_type()
        document['global_template_ids'] = [TEMPLATE_NAME, TEMPLATE_NAME]

        reconcile_type_with_global_templates(document, TEMPLATES)

        assert document['global_template_ids'] == [TEMPLATE_NAME]

    def test_claims_that_are_no_names_are_left_out(self) -> None:
        """A number or a null is no template name"""
        assert claimed_template_names({'global_template_ids': [TEMPLATE_NAME, 7, None]}) == [TEMPLATE_NAME]
        assert not claimed_template_names({'global_template_ids': 'dg-modelspec'})
        assert not claimed_template_names({})


class TestTheConflict:
    """A foreign field inside a template's section"""

    def test_a_foreign_field_is_reported(self) -> None:
        """Named with its template - the caller refuses the write"""
        document = _faithful_type()
        _section(document, TEMPLATE_NAME)['fields'].append(OWN_FIELD)

        outcome = reconcile_type_with_global_templates(document, TEMPLATES)

        assert outcome.conflicts == [TemplateSectionConflict(TEMPLATE_NAME, OWN_FIELD)]

    def test_the_first_template_is_named_with_its_fields_sorted(self) -> None:
        """What the refusal message says"""
        outcome = reconcile_type_with_global_templates(_faithful_type(), TEMPLATES)._replace(conflicts=[
            TemplateSectionConflict(TEMPLATE_NAME, 'z'), TemplateSectionConflict(OTHER_TEMPLATE_NAME, 'q'),
            TemplateSectionConflict(TEMPLATE_NAME, 'a'),
        ])

        assert first_template_conflict(outcome) == (TEMPLATE_NAME, ['a', 'z'])

    def test_no_conflict_names_nothing(self) -> None:
        """None to refuse"""
        assert first_template_conflict(reconcile_type_with_global_templates(_faithful_type(), TEMPLATES)) is None


class TestMalformedLayouts:
    """The structure rules judge a malformed type - the reconcile neither crashes on it nor reads it as names"""

    def test_a_field_list_that_is_no_list_is_left_alone(self) -> None:
        """Nothing is replaced in it"""
        document = {**_faithful_type(), 'fields': 'nonsense'}

        reconcile_type_with_global_templates(document, TEMPLATES)

        assert document['fields'] == 'nonsense'

    def test_a_section_list_that_is_no_list_is_left_alone(self) -> None:
        """No section to reconcile, so no conflict either"""
        document = {**_faithful_type(), 'render_meta': {'sections': 'nonsense'}}

        outcome = reconcile_type_with_global_templates(document, TEMPLATES)

        assert document['render_meta']['sections'] == 'nonsense'
        assert outcome.conflicts == []

    def test_a_section_field_list_that_is_no_list_is_never_read_as_names(self) -> None:
        """A string would otherwise be scanned letter by letter"""
        document = _faithful_type()
        _section(document, TEMPLATE_NAME)['fields'] = 'nonsense'

        outcome = reconcile_type_with_global_templates(document, TEMPLATES)

        assert outcome.conflicts == []
        assert _section(document, TEMPLATE_NAME)['fields'] == TEMPLATE_FIELD_NAMES

    def test_no_render_meta_gets_the_template_section(self) -> None:
        """A missing layout is started"""
        document = {'global_template_ids': [TEMPLATE_NAME]}

        reconcile_type_with_global_templates(document, TEMPLATES)

        assert document['render_meta']['sections'][0]['fields'] == TEMPLATE_FIELD_NAMES
        assert [field['name'] for field in document['fields']] == TEMPLATE_FIELD_NAMES


class TestResolveGlobalTemplates:
    """The one lookup of the claimed templates"""

    def test_asks_once_for_the_global_templates_by_name(self) -> None:
        """Sorted, de-duplicated names, global only - answered by name"""
        manager = MagicMock()
        manager.find.return_value = [TEMPLATE]

        assert resolve_global_templates(manager, [TEMPLATE_NAME, TEMPLATE_NAME]) == TEMPLATES
        manager.find.assert_called_once_with({'name': {'$in': [TEMPLATE_NAME]}, 'is_global': True})

    def test_no_names_asks_nothing(self) -> None:
        """No query for a type that claims nothing"""
        manager = MagicMock()

        assert resolve_global_templates(manager, []) == {}
        manager.find.assert_not_called()
