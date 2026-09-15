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
Unit tests for cmdb.interface.rest_api.routes.importer_routes.importer_type_repairs

The repairs an import applies instead of refusing an entry: the dropped public_id, the optional
top-level defaults, the render_meta icon, and the three that resolve ids belonging to the exporting
system - cross-type references, ACL groups and global section templates. Manager stubs stand in for
the database, so the tests also pin how many queries a repair costs.
"""
import re
from typing import Any

import pytest

from cmdb.models.type_model import CmdbType, TypeSchemaKey
from cmdb.interface.rest_api.routes.importer_routes.importer_type_constants import (
    DEFAULT_TYPE_ICON,
    TypeImportError,
)
from cmdb.interface.rest_api.routes.importer_routes.importer_type_repairs import (
    strip_uploaded_public_id,
    apply_type_defaults,
    apply_render_meta_defaults,
    clear_dangling_type_references,
    clear_dangling_acl_groups,
    deactivate_empty_acl,
    reconcile_global_templates,
    resolve_global_templates,
    normalize_imported_type,
)
from cmdb.interface.rest_api.routes.importer_routes.importer_type_helper import (
    create_type_from_entry,
    update_type_from_entry,
)
from tests.utils.ipam_doc_builders import make_type_doc
from tests.utils.type_import_builders import (
    BOOM,
    EXISTING_PUBLIC_ID,
    NEW_PUBLIC_ID,
    IMPORTER,
    StubTypesManager,
    StubSectionTemplatesManager,
    no_templates,
    ref_section_entry,
    type_field,
    type_structure,
)
# -------------------------------------------------------------------------------------------------------------------- #


class TestApplyRenderMetaDefaults:
    """An upload without an icon gets the placeholder instead of rendering without a symbol."""

    @pytest.mark.parametrize('icon', ['', '   ', None, 42], ids=['empty', 'blank', 'none', 'number'])
    def test_missing_icon_is_defaulted(self, icon: Any) -> None:
        """An unusable icon value is replaced by the default."""
        entry = {'name': 'server', 'render_meta': {'icon': icon, 'sections': []}}

        apply_render_meta_defaults(entry)

        assert entry['render_meta']['icon'] == DEFAULT_TYPE_ICON

    def test_absent_icon_key_is_defaulted(self) -> None:
        """A render_meta without an icon key gets one."""
        entry = {'name': 'server', 'render_meta': {'sections': []}}

        apply_render_meta_defaults(entry)

        assert entry['render_meta']['icon'] == DEFAULT_TYPE_ICON

    def test_uploaded_icon_is_kept(self) -> None:
        """An icon the upload brings is never overwritten."""
        entry = {'name': 'server', 'render_meta': {'icon': 'fas fa-server', 'sections': []}}

        apply_render_meta_defaults(entry)

        assert entry['render_meta']['icon'] == 'fas fa-server'

    @pytest.mark.parametrize('render_meta', [None, 'nonsense'], ids=['absent', 'malformed'])
    def test_missing_render_meta_is_created(self, render_meta: Any) -> None:
        """A type without a usable render_meta still ends up with an icon."""
        entry: dict[str, Any] = {'name': 'server'}

        if render_meta is not None:
            entry['render_meta'] = render_meta

        apply_render_meta_defaults(entry)

        assert entry['render_meta'] == {'icon': DEFAULT_TYPE_ICON}

    @pytest.mark.parametrize('entry', ['a string', 42, None], ids=['str', 'int', 'none'])
    def test_non_dict_entry_is_ignored(self, entry: Any) -> None:
        """A malformed entry is left to the build step rather than crashing here."""
        apply_render_meta_defaults(entry)


class TestApplyTypeDefaults:
    """The optional top-level values are filled in rather than reported."""

    def test_missing_label_falls_back_to_the_title_cased_name(self) -> None:
        """A type is always shown by its label, so it never stays empty."""
        entry: dict[str, Any] = {'name': 'network-device'}

        apply_type_defaults(entry)

        assert entry['label'] == 'Network-Device'

    @pytest.mark.parametrize('label', ['', '   ', None, 42], ids=['empty', 'blank', 'none', 'number'])
    def test_unusable_label_is_replaced(self, label: Any) -> None:
        """An unusable label value is treated as absent."""
        entry = {'name': 'server', 'label': label}

        apply_type_defaults(entry)

        assert entry['label'] == 'Server'

    def test_uploaded_label_is_kept(self) -> None:
        """A label the upload brings survives."""
        entry = {'name': 'server', 'label': 'Physical Server'}

        apply_type_defaults(entry)

        assert entry['label'] == 'Physical Server'

    def test_version_is_forced_to_the_initial_version(self) -> None:
        """The version is server-owned, exactly as in the object import."""
        entry = {'name': 'server', 'version': '9.9.9'}

        apply_type_defaults(entry)

        assert entry['version'] == CmdbType.DEFAULT_VERSION

    def test_ci_explorer_label_defaults_to_none(self) -> None:
        """The CI Explorer falls back to the type label when no explicit one is given."""
        entry: dict[str, Any] = {'name': 'server'}

        apply_type_defaults(entry)

        assert entry['ci_explorer_label'] is None

    def test_uploaded_ci_explorer_label_is_kept(self) -> None:
        """An explicit CI-Explorer label survives."""
        entry = {'name': 'server', 'ci_explorer_label': 'SRV'}

        apply_type_defaults(entry)

        assert entry['ci_explorer_label'] == 'SRV'

    def test_ci_explorer_color_is_defaulted_to_a_random_color(self) -> None:
        """A type without a color gets a random one so it is distinguishable in the graph."""
        entry: dict[str, Any] = {'name': 'server'}

        apply_type_defaults(entry)

        assert re.fullmatch(r'#[0-9A-F]{6}', entry['ci_explorer_color'])

    def test_uploaded_ci_explorer_color_is_kept(self) -> None:
        """A color the upload brings survives."""
        entry = {'name': 'server', 'ci_explorer_color': '#123ABC'}

        apply_type_defaults(entry)

        assert entry['ci_explorer_color'] == '#123ABC'

    def test_missing_acl_defaults_to_access_control_off(self) -> None:
        """A type without an ACL is governed by the normal rights alone."""
        entry: dict[str, Any] = {'name': 'server'}

        apply_type_defaults(entry)

        assert entry['acl'] == {'activated': False, 'groups': {'includes': {}}}

    def test_the_default_acl_is_not_shared_between_entries(self) -> None:
        """Each entry gets its own ACL dict, so mutating one never leaks into the next."""
        first: dict[str, Any] = {'name': 'first'}
        second: dict[str, Any] = {'name': 'second'}

        apply_type_defaults(first)
        apply_type_defaults(second)
        first['acl']['groups']['includes']['1'] = ['READ']

        assert second['acl'] == {'activated': False, 'groups': {'includes': {}}}

    def test_uploaded_acl_is_kept(self) -> None:
        """An ACL the upload brings survives."""
        acl = {'activated': True, 'groups': {'includes': {'2': ['READ']}}}
        entry = {'name': 'server', 'acl': acl}

        apply_type_defaults(entry)

        assert entry['acl'] == acl

    @pytest.mark.parametrize('entry', ['a string', 42, None], ids=['str', 'int', 'none'])
    def test_non_dict_entry_is_ignored(self, entry: Any) -> None:
        """A malformed entry is left to the build step rather than crashing here."""
        apply_type_defaults(entry)

    def test_create_stores_the_defaults(self) -> None:
        """The defaults reach the inserted CmdbType, not just the entry dict."""
        entry = make_type_doc(0, 'imported-type')
        for optional in ('label', 'version', 'ci_explorer_label', 'ci_explorer_color', 'acl'):
            entry.pop(optional, None)

        types_manager = StubTypesManager()

        assert create_type_from_entry(entry, types_manager, no_templates(), IMPORTER) is None

        stored = types_manager.inserted[0]

        assert stored.label == 'Imported-Type'
        assert stored.version == CmdbType.DEFAULT_VERSION
        assert stored.ci_explorer_label is None
        assert re.fullmatch(r'#[0-9A-F]{6}', stored.ci_explorer_color)
        assert stored.active is True
        assert stored.selectable_as_parent is True


class TestStripUploadedPublicId:
    """On the create path the public_id is server-owned, so an uploaded one is dropped."""

    def test_uploaded_public_id_is_dropped(self) -> None:
        """The id of the exporting system is removed from the entry."""
        entry = {'name': 'server', TypeSchemaKey.PUBLIC_ID.value: EXISTING_PUBLIC_ID}

        strip_uploaded_public_id(entry)

        assert TypeSchemaKey.PUBLIC_ID.value not in entry

    def test_entry_without_a_public_id_is_untouched(self) -> None:
        """An upload that already omits the id needs no repair."""
        entry = {'name': 'server'}

        strip_uploaded_public_id(entry)

        assert entry == {'name': 'server'}

    @pytest.mark.parametrize('entry', ['a string', 42, None], ids=['str', 'int', 'none'])
    def test_non_dict_entry_is_ignored(self, entry: Any) -> None:
        """A malformed entry is left to the build step rather than crashing here."""
        strip_uploaded_public_id(entry)

    def test_create_assigns_a_fresh_id_over_the_dropped_one(self) -> None:
        """A create ends up with this system's next public_id, never the uploaded one."""
        entry = make_type_doc(EXISTING_PUBLIC_ID, 'imported-type')
        types_manager = StubTypesManager()

        assert create_type_from_entry(entry, types_manager, no_templates(), IMPORTER) is None
        assert types_manager.inserted[0].public_id == NEW_PUBLIC_ID

    def test_update_keeps_the_uploaded_public_id(self) -> None:
        """The update path identifies the type by its public_id, so it is never dropped."""
        entry = make_type_doc(EXISTING_PUBLIC_ID, 'imported-type')
        types_manager = StubTypesManager()

        assert update_type_from_entry(entry, types_manager, no_templates(), IMPORTER) is None
        assert types_manager.updated[0][0] == EXISTING_PUBLIC_ID


class TestClearDanglingTypeReferences:
    """Cross-type references are public_ids of the exporting system, so unresolvable ones are cleared."""

    def test_resolvable_reference_is_kept(self) -> None:
        """A reference to a type that exists here survives untouched."""
        entry = ref_section_entry(7)
        types_manager = StubTypesManager(existing_type_ids={7})

        assert clear_dangling_type_references(entry, types_manager) == []
        assert entry['render_meta']['sections'][0]['reference']['type_id'] == 7

    def test_dangling_reference_is_reset(self) -> None:
        """A reference to an unknown type is reset to the unconfigured shape."""
        entry = ref_section_entry(7)

        assert clear_dangling_type_references(entry, StubTypesManager()) == [7]
        assert entry['render_meta']['sections'][0]['reference'] == {
            'type_id': None, 'section_name': None, 'selected_fields': [],
        }

    def test_dangling_ref_types_are_pruned(self) -> None:
        """Only the unresolvable ids are dropped from a reference field's ref_types."""
        entry = {
            'name': 'server',
            'fields': [{'type': 'ref', 'name': 'owner', 'label': 'Owner', 'ref_types': [3, 7]}],
            'render_meta': {'sections': [{'type': 'section', 'name': 'main', 'fields': ['owner']}]},
        }

        assert clear_dangling_type_references(entry, StubTypesManager(existing_type_ids={3})) == [7]
        assert entry['fields'][0]['ref_types'] == [3]

    def test_all_references_are_resolved_in_one_query(self) -> None:
        """Every referenced id of an entry is looked up together, not one round trip each."""
        entry = ref_section_entry(7)
        entry['fields'].append({'type': 'ref', 'name': 'owner', 'label': 'Owner', 'ref_types': [3]})
        entry['render_meta']['sections'].append(
            {'type': 'section', 'name': 'main', 'fields': ['owner']}
        )
        types_manager = StubTypesManager(existing_type_ids={3, 7})

        clear_dangling_type_references(entry, types_manager)

        assert types_manager.existence_lookups == [[3, 7]]

    def test_a_type_without_references_is_not_queried(self) -> None:
        """A type referencing nothing costs no extra read."""
        types_manager = StubTypesManager()
        entry = make_type_doc(EXISTING_PUBLIC_ID, 'imported-type')

        assert clear_dangling_type_references(entry, types_manager) == []
        assert not types_manager.existence_lookups

    @pytest.mark.parametrize('entry', ['a string', 42, None], ids=['str', 'int', 'none'])
    def test_non_dict_entry_is_ignored(self, entry: Any) -> None:
        """A malformed entry is left to the build step rather than crashing here."""
        assert clear_dangling_type_references(entry, StubTypesManager()) == []


class TestMalformedRenderMetaIsTolerated:
    """Nonsense in the presentation data is skipped rather than crashing a rule."""

    @pytest.mark.parametrize(
        'reference',
        ['nonsense', {'type_id': None}, {'type_id': 'seven'}, {'type_id': True}],
        ids=['not-a-dict', 'none', 'string', 'bool'],
    )
    def test_reference_without_a_usable_type_id_is_not_looked_up(self, reference: Any) -> None:
        """Only an integer type_id is a reference worth resolving."""
        entry = ref_section_entry(7)
        entry['render_meta']['sections'][0]['reference'] = reference
        types_manager = StubTypesManager()

        assert clear_dangling_type_references(entry, types_manager) == []
        assert not types_manager.existence_lookups

    def test_non_integer_ref_types_are_left_alone(self) -> None:
        """A ref_types list holding something other than ids is not resolved or pruned."""
        entry = {
            'name': 'server',
            'fields': [{'type': 'ref', 'name': 'owner', 'label': 'Owner', 'ref_types': ['seven']}],
            'render_meta': {'sections': [{'type': 'section', 'name': 'main', 'fields': ['owner']}]},
        }
        types_manager = StubTypesManager()

        assert clear_dangling_type_references(entry, types_manager) == []
        assert entry['fields'][0]['ref_types'] == ['seven']
        assert not types_manager.existence_lookups

    def test_update_reports_a_failing_reference_lookup_per_entry(self) -> None:
        """A failing existence lookup fails this entry of an update, not the whole batch."""
        entry = ref_section_entry(7)
        entry[TypeSchemaKey.PUBLIC_ID.value] = EXISTING_PUBLIC_ID
        entry[TypeSchemaKey.AUTHOR_ID.value] = 1
        types_manager = StubTypesManager(existence_error=RuntimeError(BOOM))

        assert update_type_from_entry(entry, types_manager, no_templates(), IMPORTER) \
            == TypeImportError.NORMALIZATION_FAILED.format(detail=BOOM)
        assert not types_manager.updated


def _acl_entry(includes: Any) -> dict[str, Any]:
    """An uploaded type carrying the given ACL group grants."""
    return {'name': 'server', 'acl': {'activated': True, 'groups': {'includes': includes}}}


class TestClearDanglingAclGroups:
    """ACL grants name groups of the exporting system, so unresolvable ones are dropped."""

    def test_a_resolvable_group_keeps_its_grant(self) -> None:
        """A group that exists here survives untouched."""
        entry = _acl_entry({'2': ['READ']})

        assert clear_dangling_acl_groups(entry, StubTypesManager(existing_group_ids={2})) == []
        assert entry['acl']['groups']['includes'] == {'2': ['READ']}

    def test_an_unknown_group_is_dropped(self) -> None:
        """Nobody decided to grant the group holding that id here, so the entry goes."""
        entry = _acl_entry({'2': ['READ'], '3': ['UPDATE']})

        assert clear_dangling_acl_groups(entry, StubTypesManager(existing_group_ids={2})) == ['3']
        assert entry['acl']['groups']['includes'] == {'2': ['READ']}

    def test_an_unparsable_key_is_dropped(self) -> None:
        """A key that is not a public_id at all can never resolve."""
        entry = _acl_entry({'not-an-id': ['READ']})

        assert clear_dangling_acl_groups(entry, StubTypesManager()) == ['not-an-id']
        assert entry['acl']['groups']['includes'] == {}

    def test_integer_keys_are_understood(self) -> None:
        """A payload that kept its keys as numbers resolves the same way."""
        entry = _acl_entry({4: ['READ']})

        assert clear_dangling_acl_groups(entry, StubTypesManager(existing_group_ids={4})) == []
        assert entry['acl']['groups']['includes'] == {4: ['READ']}

    def test_all_groups_are_resolved_in_one_query(self) -> None:
        """One read per entry, whatever the number of grants."""
        types_manager = StubTypesManager(existing_group_ids={2, 3})

        clear_dangling_acl_groups(_acl_entry({'2': ['READ'], '3': ['UPDATE']}), types_manager)

        (collection, requirements), = types_manager.group_lookups

        assert collection == 'management.groups'
        assert requirements == {'public_id': {'$in': [2, 3]}}

    @pytest.mark.parametrize(
        'entry',
        [{'name': 'x'}, {'name': 'x', 'acl': None}, {'name': 'x', 'acl': {'groups': {'includes': {}}}},
         {'name': 'x', 'acl': {'groups': 'nonsense'}}, 'not-a-dict'],
        ids=['no-acl', 'null-acl', 'empty', 'malformed', 'not-a-dict'],
    )
    def test_nothing_to_resolve_costs_no_query(self, entry: Any) -> None:
        """An entry without usable grants is left alone and never read for."""
        types_manager = StubTypesManager()

        assert clear_dangling_acl_groups(entry, types_manager) == []
        assert not types_manager.group_lookups


def _template(name: str, fields: list[dict[str, Any]], section_type: str = 'section') -> dict[str, Any]:
    """A stored global section template."""
    return {
        'public_id': 7, 'name': name, 'label': name.title(), 'type': section_type,
        'fields': fields, 'is_global': True,
    }


def _type_claiming(template_name: str, fields: list[dict[str, Any]],
                   sections: list[dict[str, Any]]) -> dict[str, Any]:
    """An uploaded type claiming one global section template."""
    entry = type_structure(fields, sections)
    entry['name'] = 'server'
    entry['global_template_ids'] = [template_name]

    return entry


class TestReconcileGlobalTemplates:
    """The claimed global section templates decide what the type must carry."""

    def test_a_template_that_does_not_exist_here_is_dropped(self) -> None:
        """The inlined section stays - it is real data - but the claim to the template goes."""
        entry = _type_claiming(
            'dg-gone', [type_field('host')], [{'type': 'section', 'name': 'dg-gone', 'fields': ['host']}],
        )

        reconcile_global_templates(entry, StubSectionTemplatesManager())

        assert entry['global_template_ids'] == []
        assert entry['fields'] == [type_field('host')]  # untouched
        assert len(entry['render_meta']['sections']) == 1

    def test_a_resolvable_template_is_kept(self) -> None:
        """A template that exists here stays claimed."""
        template = _template('dg-contact', [type_field('host')])
        entry = _type_claiming(
            'dg-contact', [type_field('host')],
            [{'type': 'section', 'name': 'dg-contact', 'fields': ['host']}],
        )

        reconcile_global_templates(entry, StubSectionTemplatesManager([template]))

        assert entry['global_template_ids'] == ['dg-contact']

    def test_a_missing_template_field_is_added_to_the_type_and_its_section(self) -> None:
        """The template evolved since the export, so the type is topped up."""
        template = _template('dg-contact', [type_field('host'), type_field('phone')])
        entry = _type_claiming(
            'dg-contact', [type_field('host')],
            [{'type': 'section', 'name': 'dg-contact', 'fields': ['host']}],
        )

        reconcile_global_templates(entry, StubSectionTemplatesManager([template]))

        assert [field['name'] for field in entry['fields']] == ['host', 'phone']
        assert entry['render_meta']['sections'][0]['fields'] == ['host', 'phone']

    def test_the_added_field_is_a_copy_of_the_template_definition(self) -> None:
        """Editing the imported type must not reach back into the stored template."""
        template = _template('dg-contact', [type_field('phone')])
        entry = _type_claiming('dg-contact', [], [{'type': 'section', 'name': 'dg-contact', 'fields': []}])

        reconcile_global_templates(entry, StubSectionTemplatesManager([template]))
        entry['fields'][0]['label'] = 'Changed'

        assert template['fields'][0]['label'] == 'phone'

    def test_a_field_the_type_already_defines_is_never_added_twice(self) -> None:
        """A name identifies exactly one field, so the type's own definition wins."""
        template = _template('dg-contact', [{'type': 'text', 'name': 'host', 'label': 'From template'}])
        entry = _type_claiming(
            'dg-contact', [type_field('host')],
            [{'type': 'section', 'name': 'dg-contact', 'fields': ['host']}],
        )

        reconcile_global_templates(entry, StubSectionTemplatesManager([template]))

        assert [field['name'] for field in entry['fields']] == ['host']
        assert entry['fields'][0]['label'] == 'host'  # the type's own definition

    def test_a_field_used_elsewhere_on_the_type_is_not_duplicated(self) -> None:
        """The name is taken by another section's field, so the template's copy is skipped."""
        template = _template('dg-contact', [type_field('host')])
        entry = _type_claiming(
            'dg-contact', [type_field('host')],
            [
                {'type': 'section', 'name': 'main', 'fields': ['host']},
                {'type': 'section', 'name': 'dg-contact', 'fields': []},
            ],
        )

        reconcile_global_templates(entry, StubSectionTemplatesManager([template]))

        assert [field['name'] for field in entry['fields']] == ['host']
        assert entry['render_meta']['sections'][1]['fields'] == []

    def test_the_section_is_rebuilt_when_the_type_does_not_carry_it(self) -> None:
        """A type claiming a template it has no section for gets the section from the template."""
        template = _template('dg-contact', [type_field('phone')], section_type='multi-data-section')
        entry = _type_claiming(
            'dg-contact', [type_field('host')], [{'type': 'section', 'name': 'main', 'fields': ['host']}],
        )

        reconcile_global_templates(entry, StubSectionTemplatesManager([template]))

        rebuilt = entry['render_meta']['sections'][1]

        assert rebuilt == {
            'type': 'multi-data-section', 'name': 'dg-contact', 'label': 'Dg-Contact', 'fields': ['phone'],
        }

    def test_all_templates_are_resolved_in_one_query(self) -> None:
        """One read per entry, and only global templates are considered."""
        section_templates = StubSectionTemplatesManager([_template('dg-contact', [])])
        entry = _type_claiming(
            'dg-contact', [type_field('host')], [{'type': 'section', 'name': 'main', 'fields': ['host']}],
        )
        entry['global_template_ids'] = ['dg-contact', 'dg-other']

        reconcile_global_templates(entry, section_templates)

        (query,) = section_templates.queries

        assert query == {'name': {'$in': ['dg-contact', 'dg-other']}, 'is_global': True}

    @pytest.mark.parametrize('claimed', [None, [], [7]], ids=['absent', 'empty', 'not-a-name'])
    def test_a_type_claiming_nothing_costs_no_query(self, claimed: Any) -> None:
        """Nothing to reconcile means no read at all."""
        section_templates = StubSectionTemplatesManager()
        entry: dict[str, Any] = {'name': 'server'}

        if claimed is not None:
            entry['global_template_ids'] = claimed

        reconcile_global_templates(entry, section_templates)

        assert not section_templates.queries

    def test_a_non_dict_entry_is_ignored(self) -> None:
        """A malformed entry is left to the build step rather than crashing here."""
        reconcile_global_templates('not-a-dict', StubSectionTemplatesManager())


class TestNormalizeImportedType:
    """normalize_imported_type applies every repair, in one place, for both verbs."""

    def test_every_repair_runs(self) -> None:
        """Defaults, icon, references, ACL groups and templates are all applied to one entry."""
        entry = _type_claiming(
            'dg-gone', [type_field('host')], [{'type': 'section', 'name': 'dg-gone', 'fields': ['host']}],
        )
        entry['acl'] = {'activated': True, 'groups': {'includes': {'9': ['READ']}}}
        entry['fields'].append({'type': 'ref', 'name': 'owner', 'label': 'Owner', 'ref_types': [404]})

        normalize_imported_type(entry, StubTypesManager(), StubSectionTemplatesManager())

        assert entry['label'] == 'Server'                       # apply_type_defaults
        assert entry['render_meta']['icon'] == DEFAULT_TYPE_ICON  # apply_render_meta_defaults
        assert entry['fields'][1]['ref_types'] == []            # clear_dangling_type_references
        assert entry['acl']['groups']['includes'] == {}         # clear_dangling_acl_groups
        assert entry['global_template_ids'] == []               # reconcile_global_templates


class TestTemplateReconciliationToleratesNonsense:
    """A malformed type still has to survive the template repair - the rules judge it, not this."""

    def test_a_non_list_fields_value_is_left_alone(self) -> None:
        """Nothing can be added to something that is not a field list."""
        template = _template('dg-contact', [type_field('phone')])
        entry = {'name': 'server', 'global_template_ids': ['dg-contact'], 'fields': 'nonsense'}

        reconcile_global_templates(entry, StubSectionTemplatesManager([template]))

        assert entry['fields'] == 'nonsense'

    def test_a_non_list_sections_value_leaves_the_layout_alone(self) -> None:
        """The field is still added to the type; the unusable layout is not touched."""
        template = _template('dg-contact', [type_field('phone')])
        entry = {
            'name': 'server', 'global_template_ids': ['dg-contact'],
            'fields': [], 'render_meta': {'sections': 'nonsense'},
        }

        reconcile_global_templates(entry, StubSectionTemplatesManager([template]))

        assert [field['name'] for field in entry['fields']] == ['phone']
        assert entry['render_meta']['sections'] == 'nonsense'

    def test_a_non_dict_render_meta_is_replaced(self) -> None:
        """A type whose render_meta is nonsense still gets its template section."""
        template = _template('dg-contact', [type_field('phone')])
        entry = {'name': 'server', 'global_template_ids': ['dg-contact'], 'fields': [],
                 'render_meta': 'nonsense'}

        reconcile_global_templates(entry, StubSectionTemplatesManager([template]))

        assert entry['render_meta']['sections'][0]['name'] == 'dg-contact'

    def test_a_section_whose_fields_value_is_unusable_is_left_alone(self) -> None:
        """The definition is added, the broken section list is not extended."""
        template = _template('dg-contact', [type_field('phone')])
        entry = {
            'name': 'server', 'global_template_ids': ['dg-contact'], 'fields': [],
            'render_meta': {'sections': [{'type': 'section', 'name': 'dg-contact', 'fields': 'nonsense'}]},
        }

        reconcile_global_templates(entry, StubSectionTemplatesManager([template]))

        assert [field['name'] for field in entry['fields']] == ['phone']
        assert entry['render_meta']['sections'][0]['fields'] == 'nonsense'

    def test_a_template_without_fields_adds_nothing(self) -> None:
        """An empty template has nothing to top the type up with."""
        entry = _type_claiming('dg-contact', [], [{'type': 'section', 'name': 'dg-contact', 'fields': []}])

        reconcile_global_templates(entry, StubSectionTemplatesManager([_template('dg-contact', [])]))

        assert entry['fields'] == []


class TestDeactivateEmptyAcl:
    """An access control list granting nothing denies everyone, so it is switched off."""

    def test_an_emptied_acl_is_switched_off(self) -> None:
        """Whatever emptied it, an active list with no grant is unusable."""
        entry = _acl_entry({})

        assert deactivate_empty_acl(entry) is True
        assert entry['acl']['activated'] is False

    def test_the_repair_and_the_deactivation_work_together(self) -> None:
        """clear_dangling_acl_groups drops the last grant, this switches the list off."""
        entry = _acl_entry({'4711': ['READ']})

        clear_dangling_acl_groups(entry, StubTypesManager())

        assert deactivate_empty_acl(entry) is True
        assert entry['acl'] == {'activated': False, 'groups': {'includes': {}}}

    def test_a_list_that_still_grants_something_is_left_on(self) -> None:
        """One surviving grant is a real access rule."""
        entry = _acl_entry({'2': ['READ']})

        assert deactivate_empty_acl(entry) is False
        assert entry['acl']['activated'] is True

    @pytest.mark.parametrize(
        'entry',
        [{'name': 'x'}, {'name': 'x', 'acl': 'nonsense'},
         {'name': 'x', 'acl': {'activated': False, 'groups': {'includes': {}}}},
         'not-a-dict'],
        ids=['no-acl', 'malformed', 'already-off', 'not-a-dict'],
    )
    def test_nothing_to_switch_off(self, entry: Any) -> None:
        """An absent, malformed or already inactive list is left exactly as it is."""
        assert deactivate_empty_acl(entry) is False

    def test_an_active_list_without_a_groups_section_is_switched_off(self) -> None:
        """No groups section at all grants nothing either."""
        entry = {'name': 'x', 'acl': {'activated': True}}

        deactivate_empty_acl(entry)

        assert entry['acl']['activated'] is False


class TestGlobalTemplateClaimHygiene:
    """The claim list itself is normalized, not only the fields behind it."""

    def test_a_claim_listed_twice_is_kept_once(self) -> None:
        """A duplicate claim would resolve the same template twice."""
        template = _template('dg-contact', [type_field('phone')])
        entry = _type_claiming(
            'dg-contact', [], [{'type': 'section', 'name': 'dg-contact', 'fields': []}],
        )
        entry['global_template_ids'] = ['dg-contact', 'dg-contact']

        reconcile_global_templates(entry, StubSectionTemplatesManager([template]))

        assert entry['global_template_ids'] == ['dg-contact']
        assert [field['name'] for field in entry['fields']] == ['phone']

    def test_the_claim_order_is_kept(self) -> None:
        """De-duplication must not reshuffle what the user sees."""
        templates = [_template('dg-b', []), _template('dg-a', [])]
        entry = _type_claiming('dg-b', [type_field('host')],
                               [{'type': 'section', 'name': 'main', 'fields': ['host']}])
        entry['global_template_ids'] = ['dg-b', 'dg-a', 'dg-b']

        reconcile_global_templates(entry, StubSectionTemplatesManager(templates))

        assert entry['global_template_ids'] == ['dg-b', 'dg-a']


class TestResolveGlobalTemplates:
    """The shared lookup the repair and the update side effects both use."""

    def test_only_the_templates_that_exist_are_returned(self) -> None:
        """Keyed by name, so the caller can test membership."""
        section_templates = StubSectionTemplatesManager([_template('dg-a', [])])

        resolved = resolve_global_templates(section_templates, ['dg-a', 'dg-b'])

        assert set(resolved) == {'dg-a'}

    def test_an_empty_name_list_costs_no_query(self) -> None:
        """Nothing to resolve, nothing to read."""
        section_templates = StubSectionTemplatesManager()

        assert resolve_global_templates(section_templates, []) == {}
        assert not section_templates.queries
