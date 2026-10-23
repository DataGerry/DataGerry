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
Unit tests for configuration_transfer_routes.configuration_transfer_validation

Pure tests: no Mongo; the type rules (`unchanged_type_save_problem`, which read stored types) are replaced by a
recording stub - they run for real in the integration tests. What is pinned here: a valid file has no problem; the
envelope and the version stop the check; every component's own rules and the file's coherence rules (unique
public_ids and names, every reference resolving inside the file) each name the component and the entry; a refused
route rule is reused through its 400; the type rules see a copy without the acl; an entry is judged as an unchanged
save (a relation name or a template pattern a system may keep passes); the unchanged-save type sequence leaves out
exactly the rules that judge changes; the pre-migration check refuses a newer file only; a type's copies of its
global templates are reconciled in place with the seeded and the file's global templates, a foreign field named;
every registered component has rules; and the context is built from the tenant, the licence and the seeded
templates
"""
from copy import deepcopy
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.exceptions import BadRequest

from cmdb.framework.configuration_transfer import (
    TRANSFER_COMPONENT_NAMES,
    TransferComponentName,
    TransferFileKey,
    build_component_section,
    build_transfer_file,
)
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.interface.rest_api.routes.configuration_transfer_routes import configuration_transfer_validation as module
from cmdb.interface.rest_api.routes.configuration_transfer_routes.configuration_transfer_validation import (
    COMPONENT_VALIDATORS,
    ImportContext,
    build_import_context,
    collect_refusal,
    entry_name,
    find_file_problems,
    find_import_problems,
    reconcile_template_copies,
    unchanged_type_save_problem,
    flatten_ids,
    public_id_problems,
    referenced_type_ids,
    repeated_values,
    unknown_ids,
)
from cmdb.interface.rest_api.routes.configuration_transfer_routes import (
    configuration_transfer_validation_constants as messages,
)
# -------------------------------------------------------------------------------------------------------------------- #

# What the transfer file is called in its information section
EXPORT_NAME: str = 'Test export'

DB_VERSION: int = 20261014
OTHER_DB_VERSION: int = 20261013
TEMPLATES: str = TransferComponentName.SECTION_TEMPLATES.value
TYPES: str = TransferComponentName.TYPES.value
CATEGORIES: str = TransferComponentName.CATEGORIES.value
RELATIONS: str = TransferComponentName.RELATIONS.value
PREDEFINED_NAME: str = 'dg-predefined-template'
ROUTER_ID: int = 4
SWITCH_ID: int = 21
CATEGORY_ID: int = 7
CHILD_CATEGORY_ID: int = 8
UNKNOWN_ID: int = 99
TYPE_RULE_REFUSAL: str = 'the type rule refused it'


def _template(public_id: int = 3, name: str = 'user-template') -> dict[str, Any]:
    """A section template the template routes accept"""
    return {'public_id': public_id, 'name': name, 'label': 'User Template', 'is_global': True,
            'predefined': False, 'type': 'section',
            'fields': [{'name': f'{name}-field', 'label': 'Field', 'type': 'text'}]}


def _type(public_id: int, name: str, **extra: Any) -> dict[str, Any]:
    """A type entry (its create rules are stubbed here)"""
    return {'public_id': public_id, 'name': name, 'label': name.title(), 'fields': [],
            'render_meta': {'sections': []}, **extra}


def _category(public_id: int = CATEGORY_ID, name: str = 'network', types: list[Any] | None = None,
              parent: Any = None) -> dict[str, Any]:
    """A category the category schema accepts"""
    return {'public_id': public_id, 'name': name, 'label': 'Network', 'parent': parent,
            'types': [ROUTER_ID] if types is None else types, 'meta': {'icon': '', 'order': None}}


def _relation(public_id: int = 2, name: str = 'connects', parents: list[Any] | None = None,
              children: list[Any] | None = None) -> dict[str, Any]:
    """A relation the relation schema and structure guard accept"""
    return {'public_id': public_id, 'relation_name': name, 'relation_name_parent': 'connects to',
            'relation_name_child': 'is connected by',
            'parent_type_ids': [ROUTER_ID] if parents is None else parents,
            'child_type_ids': [SWITCH_ID] if children is None else children,
            'sections': [], 'fields': []}


def _file(templates: list[dict[str, Any]] | None = None, types: list[dict[str, Any]] | None = None,
          categories: list[dict[str, Any]] | None = None, relations: list[dict[str, Any]] | None = None,
          db_version: int = DB_VERSION) -> dict[str, Any]:
    """A transfer file; every argument left out takes the valid default"""
    sections: dict[str, list[dict[str, Any]]] = {
        TEMPLATES: [_template()] if templates is None else templates,
        TYPES: [_type(ROUTER_ID, 'router'), _type(SWITCH_ID, 'switch')] if types is None else types,
        CATEGORIES: [_category()] if categories is None else categories,
        RELATIONS: [_relation()] if relations is None else relations,
    }

    return build_transfer_file(db_version, {name: build_component_section(len(items) + 10, items)
                                            for name, items in sections.items()}, name=EXPORT_NAME)


PREDEFINED_TEMPLATE: dict[str, Any] = {'name': PREDEFINED_NAME, 'label': 'Seeded', 'type': 'section',
                                       'is_global': True, 'predefined': True,
                                       'fields': [{'name': 'seeded-field', 'label': 'Seeded', 'type': 'text'}]}


def _context(ipam_locked: bool = False) -> ImportContext:
    """An importing system seeding one predefined template"""
    return ImportContext(types_manager=MagicMock(name='types_manager'), ipam_locked=ipam_locked,
                         predefined_templates=(deepcopy(PREDEFINED_TEMPLATE),))


@pytest.fixture(name='type_rule')
def fixture_type_rule(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """The type rules, replaced by a stub that passes - and records what it was handed"""
    stub: MagicMock = MagicMock(return_value=None)
    monkeypatch.setattr(module, 'unchanged_type_save_problem', stub)

    return stub


def _problems(data: dict[str, Any], context: ImportContext | None = None) -> list[str]:
    """The file's problems against DB_VERSION"""
    return find_import_problems(data, DB_VERSION, context or _context())


def _entry(component: str, entry: Any, problem: str) -> str:
    """One entry's problem as reported"""
    return messages.ENTRY_PROBLEM.format(component=component, entry=entry, problem=problem)


def _whole(component: str, problem: str) -> str:
    """A component's problem as reported"""
    return messages.COMPONENT_PROBLEM.format(component=component, problem=problem)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                      the file                                                        #
# -------------------------------------------------------------------------------------------------------------------- #

@pytest.mark.usefixtures('type_rule')
class TestTheFile:
    """The order of the checks"""

    def test_a_valid_file_has_no_problem(self) -> None:
        """Every component well-formed and coherent -> nothing to report"""
        assert not _problems(_file())

    def test_a_broken_envelope_stops_the_check(self) -> None:
        """Only the envelope's problems - the entries are not read"""
        data: dict[str, Any] = _file(templates=[{'public_id': 'x'}])
        del data[TransferFileKey.EXPORTED_AT.value]

        problems: list[str] = _problems(data)

        assert len(problems) == 1 and TransferFileKey.EXPORTED_AT.value in problems[0]

    def test_another_version_stops_the_check(self) -> None:
        """One problem: the version mismatch - the entries carry another version's shape"""
        problems: list[str] = _problems(_file(templates=[{'public_id': 'x'}], db_version=OTHER_DB_VERSION))

        assert len(problems) == 1
        assert str(OTHER_DB_VERSION) in problems[0] and str(DB_VERSION) in problems[0]

    def test_problems_of_several_components_are_answered_together(self) -> None:
        """A template problem and a relation problem in one answer, in component order"""
        problems: list[str] = _problems(_file(templates=[_template(name=PREDEFINED_NAME)],
                                              relations=[_relation(children=[UNKNOWN_ID])]))

        assert [problem.split(' ')[0] for problem in problems] == [TEMPLATES, RELATIONS]

    def test_the_public_id_rule_runs_on_every_component(self) -> None:
        """Two templates sharing an id are reported through the file check"""
        problems: list[str] = _problems(_file(templates=[_template(3, 'first'), _template(3, 'second')]))

        assert problems == [_whole(TEMPLATES, messages.PUBLIC_ID_REPEATED.format(values=[3]))]

    def test_every_registered_component_has_rules(self) -> None:
        """A component joining the registry fails here until its rules are written"""
        assert set(COMPONENT_VALIDATORS) == set(TRANSFER_COMPONENT_NAMES)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                    shared rules                                                      #
# -------------------------------------------------------------------------------------------------------------------- #

class TestSharedRules:
    """What every component is held to"""

    def test_collect_refusal_answers_the_abort_message(self) -> None:
        """A rule that aborts -> its description; one that passes -> None"""
        def _refusing(value: Any) -> None:
            raise BadRequest(description=f'refused {value}')

        assert collect_refusal(_refusing, 1) == 'refused 1'
        assert collect_refusal(lambda value: None, 1) is None

    @pytest.mark.parametrize('item,index,expected', [
        ({'public_id': 5}, 0, '5'),
        ({'public_id': 0}, 2, 'entry #2'),
        ({'public_id': True}, 3, 'entry #3'),
        ({}, 4, 'entry #4'),
    ])
    def test_an_entry_is_named_by_its_public_id_or_its_position(self, item: dict[str, Any], index: int,
                                                                expected: str) -> None:
        """A usable public_id names it; anything else falls back to the position"""
        assert entry_name(item, index) == expected

    def test_public_ids_must_be_positive_whole_numbers(self) -> None:
        """Zero, a string, a bool and a missing id are each named by position"""
        items: list[dict[str, Any]] = [{'public_id': 0}, {'public_id': '3'}, {'public_id': True}, {}]

        assert public_id_problems(TYPES, items) == [
            _entry(TYPES, f'entry #{index}', messages.PUBLIC_ID_NOT_A_NUMBER) for index in range(len(items))
        ]

    def test_public_ids_must_be_unique_per_component(self) -> None:
        """Two entries sharing an id -> one problem for the component"""
        assert public_id_problems(TYPES, [{'public_id': 4}, {'public_id': 4}, {'public_id': 5}]) == [
            _whole(TYPES, messages.PUBLIC_ID_REPEATED.format(values=[4]))
        ]

    def test_unknown_ids_names_the_ids_the_file_lacks(self) -> None:
        """Sorted, each once; what is no id is the schema's business; no list is nothing"""
        assert unknown_ids([9, 4, 9, True, 'x', 2], {4}) == [2, 9]
        assert not unknown_ids(None, {4})
        assert not unknown_ids(4, set())

    def test_repeated_values_skips_what_cannot_be_compared(self) -> None:
        """A list value is the entry rules' business, not a duplicate"""
        assert repeated_values([{'name': ['a']}, {'name': ['a']}, {'name': 'b'}, {'name': 'b'}], 'name') == ['b']

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  section templates                                                   #
# -------------------------------------------------------------------------------------------------------------------- #

@pytest.mark.usefixtures('type_rule')
class TestSectionTemplates:
    """The template routes' rules, plus what the import adds"""

    def test_a_predefined_template_is_refused(self) -> None:
        """DataGerry seeds its own"""
        template: dict[str, Any] = {**_template(), 'predefined': True}

        assert _problems(_file(templates=[template])) == [_entry(TEMPLATES, 3, messages.PREDEFINED_TEMPLATE_IN_FILE)]

    def test_a_name_of_a_predefined_template_is_refused(self) -> None:
        """The seeded template would take the same name"""
        assert _problems(_file(templates=[_template(name=PREDEFINED_NAME)])) == [
            _entry(TEMPLATES, 3, messages.TEMPLATE_NAME_IS_PREDEFINED.format(name=PREDEFINED_NAME))
        ]

    @pytest.mark.parametrize('key', ['name', 'label'])
    def test_a_blank_name_or_label_is_refused_with_the_routes_message(self, key: str) -> None:
        """The route's own text rule, its 400 reused"""
        problems: list[str] = _problems(_file(templates=[{**_template(), key: '  '}]))

        assert problems == [_entry(TEMPLATES, 3, f"The '{key}' of a Section Template must not be empty!")]

    @pytest.mark.parametrize('fields,expected', [
        (None, messages.TEMPLATE_FIELDS_NOT_A_LIST),
        ([None], messages.TEMPLATE_FIELD_NOT_AN_OBJECT),
        ([{'name': 'f', 'label': 'F', 'type': 'no-such-kind'}],
         "The field 'f' of a Section Template declares the unknown type 'no-such-kind'!"),
    ])
    def test_unusable_fields_are_refused(self, fields: Any, expected: str) -> None:
        """No list, a non-object entry, a field the template routes would refuse"""
        assert _problems(_file(templates=[{**_template(), 'fields': fields}])) == [_entry(TEMPLATES, 3, expected)]

    def test_a_pattern_the_template_may_keep_passes(self) -> None:
        """An unchanged save: a field pattern in a dialect the rule now refuses is not judged"""
        template: dict[str, Any] = _template()
        template['fields'][0]['regex'] = '(?i)abc'

        assert not _problems(_file(templates=[template]))

    def test_names_must_be_unique(self) -> None:
        """Two templates sharing a name"""
        assert _problems(_file(templates=[_template(3, 'twin'), _template(4, 'twin')])) == [
            _whole(TEMPLATES, messages.VALUE_REPEATED.format(key='name', values=['twin']))
        ]

# -------------------------------------------------------------------------------------------------------------------- #
#                                                         types                                                        #
# -------------------------------------------------------------------------------------------------------------------- #

class TestTypes:
    """The type import's create rules, plus references into the file"""

    def test_the_create_rules_see_a_copy_without_the_acl(self, type_rule: MagicMock) -> None:
        """The import drops the acl, so its shape is not judged; the file's entry is left untouched"""
        router: dict[str, Any] = _type(ROUTER_ID, 'router', acl={'activated': True, 'groups': {}})
        data: dict[str, Any] = _file(types=[router])
        context: ImportContext = _context(ipam_locked=True)
        untouched: dict[str, Any] = deepcopy(router)

        find_import_problems(data, DB_VERSION, context)

        entry, manager, locked = type_rule.call_args.args
        assert TypeSchemaKey.ACL.value not in entry
        assert entry == {key: value for key, value in untouched.items() if key != TypeSchemaKey.ACL.value}
        assert (manager, locked) == (context.types_manager, True)
        assert data[TransferFileKey.COMPONENTS.value][TYPES]['items'][0] == untouched

    def test_a_create_rule_refusal_is_a_problem(self, type_rule: MagicMock) -> None:
        """The first refusal of the create rules, named by the entry"""
        type_rule.return_value = TYPE_RULE_REFUSAL

        problems: list[str] = _problems(_file(types=[_type(ROUTER_ID, 'router')], categories=[], relations=[]))

        assert problems == [_entry(TYPES, ROUTER_ID, TYPE_RULE_REFUSAL)]

    @pytest.mark.usefixtures('type_rule')
    def test_references_must_resolve_inside_the_file(self) -> None:
        """A reference field and a reference section naming a type the file does not carry"""
        router: dict[str, Any] = _type(
            ROUTER_ID, 'router',
            fields=[{'name': 'peer', 'type': 'ref', 'ref_types': [SWITCH_ID, [UNKNOWN_ID]]}],
            render_meta={'sections': [{'type': 'ref-section', 'name': 'ref',
                                       'reference': {'type_id': UNKNOWN_ID + 1}}]},
        )

        assert _problems(_file(types=[router, _type(SWITCH_ID, 'switch')])) == [
            _entry(TYPES, ROUTER_ID, messages.TYPE_REFERENCES_UNKNOWN_TYPES.format(
                type_ids=[UNKNOWN_ID, UNKNOWN_ID + 1]))
        ]

    @pytest.mark.usefixtures('type_rule')
    def test_names_and_special_types_must_be_unique(self) -> None:
        """Two types named alike, two claiming one special type; unclaimed (None) is no claim"""
        types: list[dict[str, Any]] = [
            _type(ROUTER_ID, 'router', special_type='RACK'),
            _type(SWITCH_ID, 'router', special_type='RACK'),
            _type(30, 'cable', special_type=None),
            _type(31, 'patch', special_type=None),
        ]

        assert _problems(_file(types=types)) == [
            _whole(TYPES, messages.SPECIAL_TYPE_REPEATED.format(values=['RACK'])),
            _whole(TYPES, messages.VALUE_REPEATED.format(key='name', values=['router'])),
        ]

    def test_referenced_type_ids_reads_fields_and_sections(self) -> None:
        """ref_types (nested lists flattened) of every field, type_id of every render_meta section; junk skipped"""
        entry: dict[str, Any] = {
            'fields': [{'ref_types': [1, [2, 3]]}, {'name': 'plain'}, 'junk'],
            'render_meta': {'sections': [{'reference': {'type_id': 4}}, {'name': 'plain'}, 'junk']},
            # A top-level 'sections' key is not where a type keeps its sections
            'sections': [{'reference': {'type_id': 5}}],
        }

        assert referenced_type_ids(entry) == [1, 2, 3, 4]
        assert not referenced_type_ids({'fields': None, 'render_meta': 'x'})

    def test_flatten_ids(self) -> None:
        """One level of nesting, as the schema allows; no list -> nothing"""
        assert flatten_ids([1, [2, 3], 4]) == [1, 2, 3, 4]
        assert not flatten_ids(None)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                      categories                                                      #
# -------------------------------------------------------------------------------------------------------------------- #

@pytest.mark.usefixtures('type_rule')
class TestCategories:
    """The category schema, its types and parent, and the file's coherence"""

    def test_the_schema_is_applied(self) -> None:
        """A name the schema refuses"""
        problems: list[str] = _problems(_file(categories=[_category(name='')]))

        assert len(problems) == 1 and problems[0].startswith(f'{CATEGORIES} {CATEGORY_ID}: ') and 'name' in problems[0]

    @pytest.mark.parametrize('types,expected', [
        ([ROUTER_ID, True], messages.CATEGORY_TYPES_NOT_IDS.format(values=[True])),
        ([ROUTER_ID, ROUTER_ID], messages.CATEGORY_TYPES_REPEATED.format(type_ids=[ROUTER_ID])),
        ([ROUTER_ID, UNKNOWN_ID], messages.CATEGORY_TYPES_UNKNOWN.format(type_ids=[UNKNOWN_ID])),
    ])
    def test_types_must_be_ids_once_each_and_in_the_file(self, types: list[Any], expected: str) -> None:
        """No boolean, no repeat, no type the file lacks"""
        problems: list[str] = _problems(_file(categories=[_category(types=types)]))

        assert _entry(CATEGORIES, CATEGORY_ID, expected) in problems

    @pytest.mark.parametrize('parent', [UNKNOWN_ID, CATEGORY_ID])
    def test_the_parent_must_be_another_category_of_the_file(self, parent: int) -> None:
        """An unknown parent and the category itself are refused"""
        assert _problems(_file(categories=[_category(parent=parent)])) == [
            _entry(CATEGORIES, CATEGORY_ID, messages.CATEGORY_PARENT_UNKNOWN.format(parent=parent))
        ]

    def test_a_parent_in_the_file_is_accepted(self) -> None:
        """A child under another category of the file"""
        categories: list[dict[str, Any]] = [_category(),
                                            _category(CHILD_CATEGORY_ID, 'child', [SWITCH_ID], CATEGORY_ID)]

        assert not _problems(_file(categories=categories))

    def test_a_type_belongs_to_one_category_and_names_are_unique(self) -> None:
        """Two categories holding the router, and sharing a name"""
        categories: list[dict[str, Any]] = [_category(), _category(CHILD_CATEGORY_ID, 'network', [ROUTER_ID])]

        assert _problems(_file(categories=categories)) == [
            _whole(CATEGORIES, messages.TYPE_IN_SEVERAL_CATEGORIES.format(type_ids=[ROUTER_ID])),
            _whole(CATEGORIES, messages.VALUE_REPEATED.format(key='name', values=['network'])),
        ]

# -------------------------------------------------------------------------------------------------------------------- #
#                                                       relations                                                      #
# -------------------------------------------------------------------------------------------------------------------- #

@pytest.mark.usefixtures('type_rule')
class TestRelations:
    """The relation schema, structure guard, name rule and the file's coherence"""

    def test_the_schema_is_applied(self) -> None:
        """A relation without its parent-side name; the structure guard is not asked of it"""
        relation: dict[str, Any] = _relation()
        del relation['relation_name_parent']

        problems: list[str] = _problems(_file(relations=[relation]))

        assert len(problems) == 1 and 'relation_name_parent' in problems[0]

    def test_the_structure_guard_is_applied(self) -> None:
        """Two fields sharing an identifier"""
        relation: dict[str, Any] = {**_relation(), 'fields': [{'name': 'f', 'label': 'F', 'type': 'text'},
                                                               {'name': 'f', 'label': 'G', 'type': 'text'}]}

        problems: list[str] = _problems(_file(relations=[relation]))

        assert len(problems) == 1 and problems[0].startswith(f'{RELATIONS} 2: ')

    def test_a_name_the_system_may_keep_passes(self) -> None:
        """An unchanged save: a name stored before the shape rule (a space) is not judged"""
        assert not _problems(_file(relations=[_relation(name='has part')]))

    def test_both_type_lists_must_resolve_inside_the_file(self) -> None:
        """Each side named with its own unknown ids"""
        assert _problems(_file(relations=[_relation(parents=[UNKNOWN_ID], children=[UNKNOWN_ID + 1])])) == [
            _entry(RELATIONS, 2, messages.RELATION_TYPES_UNKNOWN.format(key='parent_type_ids',
                                                                       type_ids=[UNKNOWN_ID])),
            _entry(RELATIONS, 2, messages.RELATION_TYPES_UNKNOWN.format(key='child_type_ids',
                                                                       type_ids=[UNKNOWN_ID + 1])),
        ]

    def test_names_must_be_unique(self) -> None:
        """Two relations sharing a technical name"""
        assert _problems(_file(relations=[_relation(2, 'twin'), _relation(3, 'twin')])) == [
            _whole(RELATIONS, messages.VALUE_REPEATED.format(key='relation_name', values=['twin']))
        ]

# -------------------------------------------------------------------------------------------------------------------- #
#                                                      the context                                                     #
# -------------------------------------------------------------------------------------------------------------------- #

def test_build_import_context_reads_the_tenant_the_licence_and_the_seeded_templates() -> None:
    """The tenant's types manager, the IPAM lock for the user, the names the seeding code inserts"""
    user: MagicMock = MagicMock(name='user')
    manager: MagicMock = MagicMock(name='types_manager')
    seeded: list[dict[str, Any]] = [{'name': 'dg-a'}, {'name': 'dg-b'}]

    with patch.object(module.ManagerProvider, 'get_manager', return_value=manager) as get_manager, \
            patch.object(module, 'feature_locked', return_value=True) as feature_locked, \
            patch.object(module.SectionTemplateCreator, 'get_predefined_templates', return_value=seeded):
        context: ImportContext = build_import_context(user)

    assert context == ImportContext(types_manager=manager, ipam_locked=True,
                                    predefined_templates=({'name': 'dg-a'}, {'name': 'dg-b'}))
    assert context.predefined_template_names == frozenset({'dg-a', 'dg-b'})
    get_manager.assert_called_once_with(module.ManagerType.TYPES, user)
    feature_locked.assert_called_once_with(module.LicenseFeature.IPAM, user)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  unchanged-save types                                                #
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_RULES: tuple[str, ...] = (
    'validate_create_special_type', 'validate_type_structure', 'normalize_boolean_flags',
    'uses_ports_license_error', 'missing_type_name_error', 'type_name_conflict_error',
)


def test_the_unchanged_save_runs_the_save_rules_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """Special type, structure, flags, ports licence, name, name conflict - each handed what it judges"""
    calls: list[tuple[str, tuple[Any, ...]]] = []

    for name in TYPE_RULES:
        monkeypatch.setattr(module, name, lambda *args, rule=name: calls.append((rule, args)))

    entry: dict[str, Any] = {'name': 'router'}
    manager: MagicMock = MagicMock(name='types_manager')

    assert unchanged_type_save_problem(entry, manager, True) is None
    assert calls == [
        ('validate_create_special_type', (entry, manager, True)),
        ('validate_type_structure', (entry,)),
        ('normalize_boolean_flags', (entry,)),
        ('uses_ports_license_error', (entry, True)),
        ('missing_type_name_error', (entry,)),
        ('type_name_conflict_error', (entry, manager)),
    ]


def test_the_unchanged_save_answers_the_first_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    """The first rule that refuses wins; the rules after it are not asked"""
    asked: list[str] = []

    for name in TYPE_RULES:
        monkeypatch.setattr(module, name, lambda *args, rule=name: asked.append(rule) or (
            TYPE_RULE_REFUSAL if rule == 'normalize_boolean_flags' else None))

    assert unchanged_type_save_problem({}, MagicMock(), False) == TYPE_RULE_REFUSAL
    assert asked == list(TYPE_RULES[:3])


def test_the_unchanged_save_leaves_out_the_change_rules() -> None:
    """The identifier and pattern rules judge only changes - an unchanged save has none"""
    assert not hasattr(module, 'new_identifiers_error')
    assert not hasattr(module, 'field_patterns_error')

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  pre-migration check                                                 #
# -------------------------------------------------------------------------------------------------------------------- #

def test_find_file_problems_accepts_the_same_and_an_older_version() -> None:
    """An older file is migrated, not refused"""
    assert not find_file_problems(_file(), DB_VERSION)
    assert not find_file_problems(_file(db_version=OTHER_DB_VERSION), DB_VERSION)


def test_find_file_problems_refuses_a_newer_version() -> None:
    """Nothing could migrate a file from the future; both versions named"""
    problems: list[str] = find_file_problems(_file(db_version=DB_VERSION), OTHER_DB_VERSION)

    assert len(problems) == 1 and str(DB_VERSION) in problems[0] and str(OTHER_DB_VERSION) in problems[0]


def test_find_file_problems_stops_at_a_broken_envelope() -> None:
    """The envelope's problems only"""
    assert find_file_problems(None, DB_VERSION) == find_import_problems(None, DB_VERSION, _context())

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 global template copies                                               #
# -------------------------------------------------------------------------------------------------------------------- #

def _claiming(public_id: int, claims: list[str], section_fields: list[str],
              fields: list[dict[str, Any]]) -> dict[str, Any]:
    """A type claiming global templates, carrying one section named like the first claim"""
    return _type(public_id, f'type-{public_id}', global_template_ids=claims, fields=fields,
                 render_meta={'sections': [{'type': 'section', 'name': claims[0], 'label': 'Old',
                                            'fields': section_fields}]})


def test_a_copy_is_brought_in_line_with_the_seeded_template() -> None:
    """The section takes the seeded template's label and fields - in the file's entry itself"""
    router: dict[str, Any] = _claiming(ROUTER_ID, [PREDEFINED_NAME], [], [])
    data: dict[str, Any] = _file(types=[router], categories=[], relations=[])

    assert not reconcile_template_copies(data, _context())

    section: dict[str, Any] = router['render_meta']['sections'][0]
    assert (section['label'], section['fields']) == ('Seeded', ['seeded-field'])
    assert [field['name'] for field in router['fields']] == ['seeded-field']


def test_a_copy_of_a_global_template_of_the_file_is_reconciled_too() -> None:
    """A user template flagged global is a template the type meets; one not flagged global is not"""
    user_global: dict[str, Any] = {**_template(3, 'user-global'), 'is_global': True}
    user_local: dict[str, Any] = {**_template(5, 'user-local'), 'is_global': False}
    router: dict[str, Any] = _claiming(ROUTER_ID, ['user-global', 'user-local'], [], [])

    assert not reconcile_template_copies(_file(templates=[user_global, user_local], types=[router],
                                               categories=[], relations=[]), _context())
    assert router['global_template_ids'] == ['user-global']


def test_a_foreign_field_inside_a_template_section_is_a_problem() -> None:
    """A field the template does not own, placed in its section, names type, field and template"""
    router: dict[str, Any] = _claiming(ROUTER_ID, [PREDEFINED_NAME], ['own-field'],
                                       [{'name': 'own-field', 'label': 'Own', 'type': 'text'}])

    assert reconcile_template_copies(_file(types=[router], categories=[], relations=[]), _context()) == [
        _entry(TYPES, ROUTER_ID, messages.TEMPLATE_COPY_CONFLICT.format(field='own-field', template=PREDEFINED_NAME))
    ]


def test_a_type_claiming_nothing_is_left_alone() -> None:
    """No claim, nothing to reconcile"""
    router: dict[str, Any] = _type(ROUTER_ID, 'router')
    untouched: dict[str, Any] = deepcopy(router)

    assert not reconcile_template_copies(_file(types=[router], categories=[], relations=[]), _context())
    assert router == untouched
