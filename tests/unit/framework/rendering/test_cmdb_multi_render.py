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
Unit tests for cmdb.framework.rendering.cmdb_multi_render.CmdbMultiRender

Pure tests (no app context, no database): ManagerProvider is patched to hand out mock managers and the
type/object caches are pre-seeded, so real CmdbType/CmdbObject instances drive the render. Covers the
result() skip/empty guards, object/type information, sections, externals, summaries, the user/type/
object linking, the reference merges and the decomposed field/section merge helpers.
"""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cmdb.manager.manager_provider_model import ManagerType
from cmdb.framework.rendering import cmdb_multi_render as mr_module
from cmdb.framework.rendering.cmdb_multi_render import CmdbMultiRender
from cmdb.framework.rendering.render_constants import ANONYMOUS_NAME
from cmdb.framework.rendering.render_result import RenderResult
from cmdb.models.type_model import CmdbType
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.object_model import CmdbObject
from cmdb.errors.models.cmdb_type import CmdbTypeFieldNotFoundError
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

MAIN_TYPE_ID: int = 700
REF_TYPE_ID: int = 701
REFSEC_TYPE_ID: int = 702
MAIN_OBJ_ID: int = 710
REF_OBJ_ID: int = 711
REFSEC_OBJ_ID: int = 712

NAME_FIELD: str = 'dg-name'
REF_FIELD: str = 'ref-field'
LOC_FIELD: str = 'loc-field'
DATE_FIELD: str = 'date-field'
REFSEC_NAME: str = 'refsec'
REFSEC_REF_FIELD: str = 'refsec-field'
EXT_NAME: str = 'ext'

MAIN_NAME_VALUE: str = 'Main'
REF_NAME_VALUE: str = 'RefTarget'
DATE_VALUE: str = '2024-01-02'


def _ref_type() -> CmdbType:
    """Referenced type: a single text field surfaced by a 'main' section."""
    return CmdbType.from_data(make_type_doc(
        REF_TYPE_ID, 'ref-type',
        fields=[{'type': FieldType.TEXT, 'name': NAME_FIELD, 'label': 'Name'}],
        sections=[{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [NAME_FIELD]}],
    ))


def _main_type() -> CmdbType:
    """Main type: text, reference, location and date fields, a summary and one external link."""
    doc = make_type_doc(
        MAIN_TYPE_ID, 'main-type',
        fields=[
            {'type': FieldType.TEXT, 'name': NAME_FIELD, 'label': 'Name'},
            {'type': FieldType.REFERENCE, 'name': REF_FIELD, 'label': 'Ref', 'ref_types': [REF_TYPE_ID]},
            {'type': FieldType.LOCATION, 'name': LOC_FIELD, 'label': 'Loc'},
            {'type': FieldType.DATE, 'name': DATE_FIELD, 'label': 'Date'},
        ],
        sections=[{'type': 'section', 'name': 'main', 'label': 'Main',
                   'fields': [NAME_FIELD, REF_FIELD, LOC_FIELD, DATE_FIELD]}],
    )
    doc['render_meta']['externals'] = [
        {'name': EXT_NAME, 'href': 'http://x/{}', 'label': 'Ext', 'fields': [NAME_FIELD]}
    ]
    return CmdbType.from_data(doc)


def _refsec_type() -> CmdbType:
    """Type with a reference-section pulling the ref type's 'main' section fields."""
    return CmdbType.from_data(make_type_doc(
        REFSEC_TYPE_ID, 'refsec-type',
        fields=[
            {'type': FieldType.TEXT, 'name': NAME_FIELD, 'label': 'Name'},
            {'type': FieldType.REFERENCE, 'name': REFSEC_REF_FIELD, 'label': 'Ref', 'ref_types': [REF_TYPE_ID]},
        ],
        sections=[
            {'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [NAME_FIELD]},
            {'type': 'ref-section', 'name': REFSEC_NAME, 'label': 'Ref Section',
             'reference': {'type_id': REF_TYPE_ID, 'section_name': 'main', 'selected_fields': []},
             'fields': []},
        ],
    ))


def _obj(public_id: int, type_id: int, fields: list[dict], author_id: int = 1) -> CmdbObject:
    """Builds a CmdbObject from a minimal document."""
    return CmdbObject.from_data({
        'public_id': public_id,
        'type_id': type_id,
        'active': True,
        'author_id': author_id,
        'version': '1.0.0',
        'fields': fields,
    })


def _ref_obj() -> CmdbObject:
    """The referenced object of REF_TYPE_ID."""
    return _obj(REF_OBJ_ID, REF_TYPE_ID, [{'type': FieldType.TEXT, 'name': NAME_FIELD, 'value': REF_NAME_VALUE}])


def _main_obj() -> CmdbObject:
    """The main object referencing the ref object via its reference and location fields."""
    return _obj(MAIN_OBJ_ID, MAIN_TYPE_ID, [
        {'type': FieldType.TEXT, 'name': NAME_FIELD, 'value': MAIN_NAME_VALUE},
        {'type': FieldType.REFERENCE, 'name': REF_FIELD, 'value': REF_OBJ_ID},
        {'type': FieldType.LOCATION, 'name': LOC_FIELD, 'value': REF_OBJ_ID},
        {'type': FieldType.DATE, 'name': DATE_FIELD, 'value': DATE_VALUE},
    ])


def _field(fields: list[dict], name: str) -> dict:
    """Returns the rendered field with the given name."""
    return next(f for f in fields if f['name'] == name)


@pytest.fixture(name='managers')
def _managers(monkeypatch) -> SimpleNamespace:
    """Patches ManagerProvider.get_manager to hand out per-type mock managers (empty lookups)."""
    objects_m = Mock(name='objects_manager')
    types_m = Mock(name='types_manager')
    users_m = Mock(name='users_manager')
    objects_m.get_objects_lookup.return_value = {}
    types_m.get_types_lookup.return_value = {}
    users_m.get_user_lookup.return_value = {}

    mapping = {ManagerType.OBJECTS: objects_m, ManagerType.TYPES: types_m, ManagerType.USERS: users_m}
    monkeypatch.setattr(
        mr_module.ManagerProvider, 'get_manager',
        staticmethod(lambda manager_type, request_user: mapping[manager_type]),
    )
    return SimpleNamespace(objects=objects_m, types=types_m, users=users_m)


def _render(managers, to_render, ref_render=False, objects_cache=None, types_cache=None, users_cache=None):
    # managers is the active ManagerProvider patch fixture; requesting it keeps the patch in scope
    # pylint: disable=unused-argument
    """Builds a CmdbMultiRender with the patched managers and pre-seeded shared caches."""
    render = CmdbMultiRender(
        to_render, Mock(name='render_user'), ref_render,
        shared_objects_cache=objects_cache if objects_cache is not None else {},
        shared_types_cache=types_cache if types_cache is not None else {},
        shared_users_cache=users_cache if users_cache is not None else {},
    )
    return render


class TestResult:
    """result() renders each object, skipping those whose type is not cached."""

    def test_renders_object(self, managers) -> None:
        # result(single_object=True) returns a single RenderResult; pylint infers the list union
        # pylint: disable=no-member
        """A cached-type object renders its object/type info, fields, sections and summary line."""
        render = _render(managers, [_main_obj()], types_cache={MAIN_TYPE_ID: _main_type()})

        result = render.result(single_object=True)

        assert result.object_information['object_id'] == MAIN_OBJ_ID
        assert result.type_information['type_id'] == MAIN_TYPE_ID
        assert _field(result.fields, NAME_FIELD)['value'] == MAIN_NAME_VALUE
        assert MAIN_NAME_VALUE in result.summary_line
        assert isinstance(_field(result.fields, DATE_FIELD)['value'], datetime)

    def test_skips_object_with_missing_type(self, managers) -> None:
        """An object whose type is not cached is skipped (empty result list)."""
        render = _render(managers, [_main_obj()], types_cache={})

        assert render.result() == []

    def test_single_object_returns_none_when_empty(self, managers) -> None:
        """single_object returns None (not IndexError) when nothing rendered."""
        render = _render(managers, [_main_obj()], types_cache={})

        assert render.result(single_object=True) is None


class TestObjectAndTypeInformation:
    """The object/type information blocks and the icon fallback."""

    def test_object_information_keys(self, managers) -> None:
        """Object information carries the object id and author placeholder name."""
        render = _render(managers, [_main_obj()], types_cache={MAIN_TYPE_ID: _main_type()})

        info = render._CmdbMultiRender__generate_object_information(_main_obj())

        assert info['object_id'] == MAIN_OBJ_ID
        assert info['author_name'] == ANONYMOUS_NAME

    def test_type_information_icon_fallback(self, managers) -> None:
        """A type whose render_meta has no icon falls back to an empty icon string."""
        main_type = _main_type()
        del main_type.render_meta.__dict__['icon']
        render = _render(managers, [], types_cache={MAIN_TYPE_ID: main_type})

        info = render._CmdbMultiRender__generate_type_information(main_type)

        assert info['icon'] == ''


class TestTypeSections:
    """__get_type_sections serialises the type sections and degrades on error."""

    def test_returns_serialised_sections(self, managers) -> None:
        """The sections of the type are serialised to dicts."""
        render = _render(managers, [], types_cache={MAIN_TYPE_ID: _main_type()})

        sections = render._CmdbMultiRender__get_type_sections(_main_type())

        assert isinstance(sections, list) and len(sections) == 1

    def test_serialisation_error_returns_empty(self, managers) -> None:
        """A section that fails to serialise yields an empty list."""
        render = _render(managers, [], types_cache={})
        bad_type = Mock()
        bad_section = Mock()
        bad_section.to_json.side_effect = RuntimeError('boom')
        bad_type.render_meta.sections = [bad_section]

        assert render._CmdbMultiRender__get_type_sections(bad_type) == []


class TestExternals:
    """__set_externals resolves external links and skips those with missing values."""

    def test_no_externals(self, managers) -> None:
        """A type without external links yields an empty list."""
        render = _render(managers, [], types_cache={REF_TYPE_ID: _ref_type()})

        assert render._CmdbMultiRender__set_externals(_ref_obj(), _ref_type()) == []

    def test_external_resolved(self, managers) -> None:
        """An external link with all required values is filled and returned."""
        render = _render(managers, [], types_cache={MAIN_TYPE_ID: _main_type()})

        externals = render._CmdbMultiRender__set_externals(_main_obj(), _main_type())

        assert len(externals) == 1
        assert externals[0]['href'] == f'http://x/{MAIN_NAME_VALUE}'

    def test_external_missing_value_skipped(self, managers) -> None:
        """An external link whose required field has no value is skipped."""
        obj = _obj(MAIN_OBJ_ID, MAIN_TYPE_ID, [{'type': FieldType.TEXT, 'name': NAME_FIELD, 'value': ''}])
        render = _render(managers, [], types_cache={MAIN_TYPE_ID: _main_type()})

        assert render._CmdbMultiRender__set_externals(obj, _main_type()) == []


class TestCollectFieldValues:
    """_collect_field_values validates and extracts the values an external link needs."""

    def test_no_required_fields(self, managers) -> None:
        """A link whose href has no placeholders needs no fields."""
        render = _render(managers, [], types_cache={})
        ext = Mock()
        ext.link_requires_fields.return_value = False

        assert render._collect_field_values(ext, _main_obj()) == []

    def test_requires_fields_but_none_assigned_raises(self, managers) -> None:
        """A link that requires fields but has none assigned raises ValueError."""
        render = _render(managers, [], types_cache={})
        ext = Mock(name='ext')
        ext.name = EXT_NAME
        ext.link_requires_fields.return_value = True
        ext.has_fields.return_value = False

        with pytest.raises(ValueError):
            render._collect_field_values(ext, _main_obj())

    def test_object_id_and_field_values(self, managers) -> None:
        """object_id resolves to the public_id; other fields resolve to their values."""
        render = _render(managers, [], types_cache={})
        ext = Mock(name='ext')
        ext.name = EXT_NAME
        ext.link_requires_fields.return_value = True
        ext.has_fields.return_value = True
        ext.fields = ['object_id', NAME_FIELD]

        assert render._collect_field_values(ext, _main_obj()) == [MAIN_OBJ_ID, MAIN_NAME_VALUE]

    def test_missing_value_returns_none(self, managers) -> None:
        """A required field whose value is empty makes the collection return None."""
        render = _render(managers, [], types_cache={})
        obj = _obj(MAIN_OBJ_ID, MAIN_TYPE_ID, [{'type': FieldType.TEXT, 'name': NAME_FIELD, 'value': ''}])
        ext = Mock(name='ext')
        ext.name = EXT_NAME
        ext.link_requires_fields.return_value = True
        ext.has_fields.return_value = True
        ext.fields = [NAME_FIELD]

        assert render._collect_field_values(ext, obj) is None


class TestSummaries:
    """__set_summaries fills the summaries/summary line with a default fallback."""

    def test_no_summaries_uses_default_line(self, managers) -> None:
        """A type with no summary fields yields an empty summaries list and the default line."""
        main_type = _main_type()
        main_type.render_meta.summary.fields = []
        render = _render(managers, [], types_cache={MAIN_TYPE_ID: main_type})
        result = render._CmdbMultiRender__set_summaries(RenderResult(), _main_obj(), main_type)

        assert result.summaries == []
        assert result.summary_line == f'{main_type.label} #{MAIN_OBJ_ID}'

    def test_summaries_filled(self, managers) -> None:
        """A configured summary field drives the summaries and summary line."""
        main_type = _main_type()
        render = _render(managers, [], types_cache={MAIN_TYPE_ID: main_type})
        result = render._CmdbMultiRender__set_summaries(RenderResult(), _main_obj(), main_type)

        assert result.summary_line == MAIN_NAME_VALUE

    def test_summary_error_falls_back_to_default(self, managers) -> None:
        """A summary referencing a non-existent field falls back to the default line."""
        main_type = _main_type()
        main_type.render_meta.summary.fields = ['does-not-exist']
        render = _render(managers, [], types_cache={MAIN_TYPE_ID: main_type})
        result = render._CmdbMultiRender__set_summaries(RenderResult(), _main_obj(), main_type)

        assert result.summaries == []
        assert result.summary_line == f'{main_type.label} #{MAIN_OBJ_ID}'


class TestGetUserName:
    """get_user_name resolves cached users, with anonymous/editor fallbacks."""

    def test_missing_user_id_anonymous(self, managers) -> None:
        """A missing user id yields the anonymous placeholder."""
        render = _render(managers, [], types_cache={})

        assert render.get_user_name(None) == ANONYMOUS_NAME

    def test_missing_user_id_editor_none(self, managers) -> None:
        """A missing user id yields None when resolving an editor."""
        render = _render(managers, [], types_cache={})

        assert render.get_user_name(None, for_editor=True) is None

    def test_cached_user_display_name(self, managers) -> None:
        """A cached user resolves to its display name."""
        user = Mock()
        user.get_display_name.return_value = 'Jane'
        render = _render(managers, [], types_cache={}, users_cache={9: user})

        assert render.get_user_name(9) == 'Jane'

    def test_uncached_user_anonymous(self, managers) -> None:
        """An unknown user id resolves to the anonymous placeholder."""
        render = _render(managers, [], types_cache={})

        assert render.get_user_name(123) == ANONYMOUS_NAME


class TestLinkedLookups:
    """get_all_linked_users / _types / _objects collect the ids to bulk-load."""

    def test_linked_users_collects_object_and_type_authors(self, managers) -> None:
        """Object author/editor ids and type author ids are requested (minus cached)."""
        main_type = _main_type()
        obj = _obj(MAIN_OBJ_ID, MAIN_TYPE_ID, [], author_id=1)
        obj.editor_id = 2
        render = _render(managers, [obj], types_cache={MAIN_TYPE_ID: main_type})

        render.users_manager.get_user_lookup.reset_mock()
        render.get_all_linked_users()

        requested = set(render.users_manager.get_user_lookup.call_args[0][0])
        assert {1, 2}.issubset(requested)

    def test_linked_users_none_when_all_cached(self, managers) -> None:
        """No user query is issued when every referenced user is already cached."""
        obj = _obj(MAIN_OBJ_ID, MAIN_TYPE_ID, [], author_id=1)
        render = _render(managers, [obj], types_cache={}, users_cache={1: Mock()})

        assert render.get_all_linked_users() == {}

    def test_linked_types_includes_ref_section_targets(self, managers) -> None:
        """A ref-section's target type is fetched even without a referenced object."""
        render = _render(managers, [], types_cache={REFSEC_TYPE_ID: _refsec_type()})
        render.types_manager.get_types_lookup.return_value = {REF_TYPE_ID: _ref_type()}

        linked = render.get_all_linked_types()

        assert REF_TYPE_ID in linked

    def test_linked_objects_empty_without_ref_render(self, managers) -> None:
        """With ref_render off no referenced objects are collected."""
        render = _render(managers, [_main_obj()], types_cache={MAIN_TYPE_ID: _main_type()}, ref_render=False)

        assert render.get_all_linked_objects() == {}

    def test_linked_objects_collects_reference_ids(self, managers) -> None:
        """Reference field values are collected and bulk-loaded when ref_render is on."""
        render = _render(managers, [], types_cache={MAIN_TYPE_ID: _main_type()}, ref_render=True)
        render.to_render_objects = [_main_obj()]
        render.objects_manager.get_objects_lookup.return_value = {REF_OBJ_ID: _ref_obj()}

        linked = render.get_all_linked_objects()

        assert REF_OBJ_ID in linked

    def test_linked_objects_fallback_resolves_untyped_field(self, managers) -> None:
        """A field missing its 'type' is resolved via the type (fetched once)."""
        obj = _obj(MAIN_OBJ_ID, MAIN_TYPE_ID, [{'name': REF_FIELD, 'value': REF_OBJ_ID}])
        render = _render(managers, [], types_cache={}, ref_render=True)
        render.to_render_objects = [obj]
        render.types_manager.get_type_instance.return_value = _main_type()
        render.objects_manager.get_objects_lookup.return_value = {REF_OBJ_ID: _ref_obj()}

        linked = render.get_all_linked_objects()

        assert REF_OBJ_ID in linked
        render.types_manager.get_type_instance.assert_called_once()

    def test_linked_objects_lookup_error_returns_empty(self, managers) -> None:
        """An error fetching referenced objects degrades to an empty lookup."""
        render = _render(managers, [], types_cache={MAIN_TYPE_ID: _main_type()}, ref_render=True)
        render.to_render_objects = [_main_obj()]
        render.objects_manager.get_objects_lookup.side_effect = RuntimeError('db down')

        assert render.get_all_linked_objects() == {}


class TestMergeFieldContentSection:
    """__merge_field_content_section merges the object value onto a type field."""

    def _merge(self, render, t_field, obj):
        """Invokes the name-mangled __merge_field_content_section."""
        return render._CmdbMultiRender__merge_field_content_section(t_field, obj)

    def test_value_merged_and_default_kept(self, managers) -> None:
        """The object value replaces the field value; a preset value becomes the default."""
        render = _render(managers, [], types_cache={})
        merged = self._merge(render, {'name': NAME_FIELD, 'type': FieldType.TEXT, 'value': 'preset'}, _ref_obj())

        assert merged['value'] == REF_NAME_VALUE
        assert merged['default'] == 'preset'

    def test_missing_object_field_keeps_type_default(self, managers) -> None:
        """When the object has no matching field the type field is returned unchanged (no IndexError)."""
        render = _render(managers, [], types_cache={})
        obj = _obj(REF_OBJ_ID, REF_TYPE_ID, [])

        merged = self._merge(render, {'name': NAME_FIELD, 'type': FieldType.TEXT, 'value': 'keep'}, obj)

        assert merged['value'] == 'keep'

    def test_date_string_parsed(self, managers) -> None:
        """A string date value is coerced to a datetime."""
        render = _render(managers, [], types_cache={})
        obj = _obj(MAIN_OBJ_ID, MAIN_TYPE_ID, [{'type': FieldType.DATE, 'name': DATE_FIELD, 'value': DATE_VALUE}])

        merged = self._merge(render, {'name': DATE_FIELD, 'type': FieldType.DATE, 'value': None}, obj)

        assert isinstance(merged['value'], datetime)

    def test_reference_field_merges_reference_when_ref_render(self, managers) -> None:
        """A reference field with ref_render on gets its reference resolved inline."""
        render = _render(managers, [], ref_render=True, objects_cache={REF_OBJ_ID: _ref_obj()},
                         types_cache={REF_TYPE_ID: _ref_type()})
        merged = self._merge(render, {'name': REF_FIELD, 'type': FieldType.REFERENCE, 'value': None}, _main_obj())

        assert merged['reference']['object_id'] == REF_OBJ_ID


class TestReferenceExpansion:
    """_build_reference_expansion and _build_location_reference build the reference dicts."""

    def test_reference_expansion_resolves(self, managers) -> None:
        """A cached referenced object/type expands to type info and summaries."""
        render = _render(managers, [], objects_cache={REF_OBJ_ID: _ref_obj()},
                         types_cache={REF_TYPE_ID: _ref_type()})

        reference = render._build_reference_expansion(REF_OBJ_ID)

        assert reference['type_id'] == REF_TYPE_ID
        assert reference['object_id'] == REF_OBJ_ID

    def test_reference_expansion_none_when_unresolved(self, managers) -> None:
        """An unresolved reference (object not cached) returns None."""
        render = _render(managers, [], types_cache={})

        assert render._build_reference_expansion(REF_OBJ_ID) is None

    def test_location_reference_shape(self, managers) -> None:
        """The location reference carries the object id and empty type placeholders."""
        render = _render(managers, [], types_cache={})

        reference = render._build_location_reference(REF_OBJ_ID)

        assert reference['object_id'] == REF_OBJ_ID
        assert reference['type_id'] == ''


class TestMergeReferences:
    """__merge_references / _build_reference_summaries resolve a reference field to a TypeReference."""

    def _merge(self, render, field):
        """Invokes the name-mangled __merge_references."""
        return render._CmdbMultiRender__merge_references(field)

    def test_no_value_empty_reference(self, managers) -> None:
        """A field with no value yields an empty reference."""
        render = _render(managers, [], types_cache={})

        assert self._merge(render, {'value': None})['object_id'] == 0

    def test_unresolved_object_empty_reference(self, managers) -> None:
        """A value pointing at an uncached object yields an empty reference."""
        render = _render(managers, [], types_cache={})

        assert self._merge(render, {'value': REF_OBJ_ID})['object_id'] == 0

    def test_resolved_reference(self, managers) -> None:
        """A cached object/type resolves the reference to its id, label and summaries."""
        render = _render(managers, [], objects_cache={REF_OBJ_ID: _ref_obj()},
                         types_cache={REF_TYPE_ID: _ref_type()})

        reference = self._merge(render, {'value': REF_OBJ_ID})

        assert reference['object_id'] == REF_OBJ_ID
        assert reference['type_id'] == REF_TYPE_ID
        assert reference['line'] is None

    def test_get_mds_reference_delegates(self, managers) -> None:
        """get_mds_reference builds a reference from a bare value and never returns None."""
        render = _render(managers, [], objects_cache={REF_OBJ_ID: _ref_obj()},
                         types_cache={REF_TYPE_ID: _ref_type()})

        assert render.get_mds_reference(REF_OBJ_ID)['object_id'] == REF_OBJ_ID

    def test_unresolved_type_empty_reference(self, managers) -> None:
        """A cached object whose type is not cached yields an empty reference."""
        render = _render(managers, [], types_cache={})
        render.objects_cache[REF_OBJ_ID] = _ref_obj()

        assert self._merge(render, {'value': REF_OBJ_ID})['object_id'] == 0


class TestMergeFieldsValue:
    """__merge_fields_value and its section helpers build the merged field list."""

    def test_level_zero_returns_empty(self, managers) -> None:
        """A level of 0 stops the recursion with an empty field list."""
        render = _render(managers, [], types_cache={MAIN_TYPE_ID: _main_type()})

        assert render._CmdbMultiRender__merge_fields_value(_main_obj(), _main_type(), 0) == []

    def test_plain_section_reference_expanded(self, managers) -> None:
        """A reference field in a plain section gets its reference expansion filled."""
        render = _render(managers, [], ref_render=True, objects_cache={REF_OBJ_ID: _ref_obj()},
                         types_cache={MAIN_TYPE_ID: _main_type(), REF_TYPE_ID: _ref_type()})

        fields = render._CmdbMultiRender__merge_fields_value(_main_obj(), _main_type(), 3)

        assert _field(fields, REF_FIELD)['reference']['object_id'] == REF_OBJ_ID
        assert _field(fields, LOC_FIELD)['reference']['object_id'] == REF_OBJ_ID

    def test_reference_field_without_ref_render_clears_value(self, managers) -> None:
        """Without a resolvable reference the field value is cleared to None."""
        render = _render(managers, [], ref_render=False, types_cache={MAIN_TYPE_ID: _main_type()})

        fields = render._CmdbMultiRender__merge_fields_value(_main_obj(), _main_type(), 3)

        assert _field(fields, REF_FIELD)['value'] is None

    def test_reference_section_merged(self, managers) -> None:
        """A ref-section resolves the referenced type/section and merges its fields."""
        refsec_obj = _obj(REFSEC_OBJ_ID, REFSEC_TYPE_ID, [
            {'type': FieldType.TEXT, 'name': NAME_FIELD, 'value': 'Owner'},
            {'type': FieldType.REFERENCE, 'name': REFSEC_REF_FIELD, 'value': REF_OBJ_ID},
        ])
        render = _render(managers, [], ref_render=True, objects_cache={REF_OBJ_ID: _ref_obj()},
                         types_cache={REFSEC_TYPE_ID: _refsec_type(), REF_TYPE_ID: _ref_type()})

        fields = render._CmdbMultiRender__merge_fields_value(refsec_obj, _refsec_type(), 3)

        ref_field = _field(fields, REFSEC_REF_FIELD)
        assert ref_field['references']['type_id'] == REF_TYPE_ID
        merged = _field(ref_field['references']['fields'], NAME_FIELD)
        assert merged['value'] == REF_NAME_VALUE

    def test_reference_section_missing_target_type_skipped(self, managers) -> None:
        """A ref-section whose target type is not cached is skipped."""
        refsec_obj = _obj(REFSEC_OBJ_ID, REFSEC_TYPE_ID, [
            {'type': FieldType.TEXT, 'name': NAME_FIELD, 'value': 'Owner'},
            {'type': FieldType.REFERENCE, 'name': REFSEC_REF_FIELD, 'value': REF_OBJ_ID},
        ])
        render = _render(managers, [], ref_render=True, types_cache={REFSEC_TYPE_ID: _refsec_type()})

        fields = render._CmdbMultiRender__merge_fields_value(refsec_obj, _refsec_type(), 3)

        # only the plain 'main' section field survives; the ref-section is dropped
        assert all('references' not in f for f in fields)


class TestDoesNotMutateCache:
    """Rendering never writes back onto the shared cached type."""

    def test_ref_section_selected_fields_not_written_to_cache(self, managers) -> None:
        """Merging a ref-section with empty selected_fields must not backfill the cached type."""
        refsec_type = _refsec_type()
        refsec_obj = _obj(REFSEC_OBJ_ID, REFSEC_TYPE_ID, [
            {'type': FieldType.TEXT, 'name': NAME_FIELD, 'value': 'Owner'},
            {'type': FieldType.REFERENCE, 'name': REFSEC_REF_FIELD, 'value': REF_OBJ_ID},
        ])
        render = _render(managers, [], ref_render=True, objects_cache={REF_OBJ_ID: _ref_obj()},
                         types_cache={REFSEC_TYPE_ID: refsec_type, REF_TYPE_ID: _ref_type()})

        render._CmdbMultiRender__merge_fields_value(refsec_obj, refsec_type, 3)

        ref_section = refsec_type.render_meta.sections[1]
        assert ref_section.reference.selected_fields == []


class TestMergeReferenceSection:
    """_merge_reference_section handles the selected-fields, missing-section and unresolved branches."""

    def _section(self, refsec_type: CmdbType):
        """Returns the TypeReferenceSection of the refsec type."""
        return refsec_type.render_meta.sections[1]

    def _refsec_obj(self, ref_value=REF_OBJ_ID) -> CmdbObject:
        """A refsec object referencing the ref object (or a bare one when ref_value is None)."""
        fields = [{'type': FieldType.TEXT, 'name': NAME_FIELD, 'value': 'Owner'}]
        if ref_value is not None:
            fields.append({'type': FieldType.REFERENCE, 'name': REFSEC_REF_FIELD, 'value': ref_value})
        return _obj(REFSEC_OBJ_ID, REFSEC_TYPE_ID, fields)

    def test_selected_fields_subset(self, managers) -> None:
        """An explicit selected_fields list restricts the merged referenced fields."""
        refsec_type = _refsec_type()
        section = self._section(refsec_type)
        section.reference.selected_fields = [NAME_FIELD]
        render = _render(managers, [], ref_render=True, objects_cache={REF_OBJ_ID: _ref_obj()},
                         types_cache={REFSEC_TYPE_ID: refsec_type, REF_TYPE_ID: _ref_type()})

        ref_field = render._merge_reference_section(section, self._refsec_obj(), refsec_type, 3)

        assert [f['name'] for f in ref_field['references']['fields']] == [NAME_FIELD]

    def test_missing_referenced_section_returns_none(self, managers) -> None:
        """A ref-section pointing at a non-existent section of the ref type is skipped."""
        refsec_type = _refsec_type()
        section = self._section(refsec_type)
        section.reference.section_name = 'ghost'
        render = _render(managers, [], ref_render=True, objects_cache={REF_OBJ_ID: _ref_obj()},
                         types_cache={REFSEC_TYPE_ID: refsec_type, REF_TYPE_ID: _ref_type()})

        assert render._merge_reference_section(section, self._refsec_obj(), refsec_type, 3) is None

    def test_missing_reference_field_value_degrades(self, managers) -> None:
        """When the object has no reference value the section still emits its (unmerged) fields."""
        refsec_type = _refsec_type()
        section = self._section(refsec_type)
        render = _render(managers, [], ref_render=True, types_cache={REFSEC_TYPE_ID: refsec_type,
                                                                     REF_TYPE_ID: _ref_type()})

        ref_field = render._merge_reference_section(section, self._refsec_obj(ref_value=None), refsec_type, 3)

        assert ref_field['references']['type_id'] == REF_TYPE_ID


class TestMergeReferenceSectionFields:
    """__merge_reference_section_fields recurses only for ref-section-typed fields."""

    def _call(self, render, field, acc, level):
        """Invokes the name-mangled __merge_reference_section_fields."""
        return render._CmdbMultiRender__merge_reference_section_fields(field, acc, level)

    def test_non_ref_section_field_unchanged(self, managers) -> None:
        """A non ref-section field returns the accumulator untouched."""
        render = _render(managers, [], types_cache={})
        acc: list = []

        assert self._call(render, {'type': FieldType.TEXT, 'name': 'x'}, acc, 3) is acc

    def test_ref_section_field_renders_nested(self, managers) -> None:
        """A ref-section field renders the referenced object via a nested render."""
        render = _render(managers, [], ref_render=True, objects_cache={REF_OBJ_ID: _ref_obj()},
                         types_cache={REF_TYPE_ID: _ref_type()})
        field = {'type': FieldType.REF_SECTION, 'name': NAME_FIELD, 'value': REF_OBJ_ID}

        assert isinstance(self._call(render, field, [], 3), list)

    def test_ref_section_field_fetches_uncached_object(self, managers) -> None:
        """An uncached referenced object is fetched through the objects manager."""
        render = _render(managers, [], ref_render=True, types_cache={REF_TYPE_ID: _ref_type()})
        render.objects_manager.get_object.return_value = {
            'public_id': REF_OBJ_ID, 'type_id': REF_TYPE_ID, 'active': True, 'author_id': 1,
            'version': '1.0.0', 'fields': [{'type': FieldType.TEXT, 'name': NAME_FIELD, 'value': REF_NAME_VALUE}],
        }
        field = {'type': FieldType.REF_SECTION, 'name': 'nomatch', 'value': REF_OBJ_ID}

        self._call(render, field, [], 3)

        render.objects_manager.get_object.assert_called_once_with(REF_OBJ_ID)

    def test_ref_section_field_merges_nested_references(self, managers) -> None:
        """A ref-section field pointing at an object whose type has a ref-section merges the nested fields."""
        refsec_obj = _obj(REFSEC_OBJ_ID, REFSEC_TYPE_ID, [
            {'type': FieldType.TEXT, 'name': NAME_FIELD, 'value': 'Owner'},
            {'type': FieldType.REFERENCE, 'name': REFSEC_REF_FIELD, 'value': REF_OBJ_ID},
        ])
        render = _render(managers, [], ref_render=True,
                         objects_cache={REFSEC_OBJ_ID: refsec_obj, REF_OBJ_ID: _ref_obj()},
                         types_cache={REFSEC_TYPE_ID: _refsec_type(), REF_TYPE_ID: _ref_type()})
        # name matches the refsec type's ref-section field, so the nested render's result carries
        # a field with a 'references' block to iterate
        field = {'type': FieldType.REF_SECTION, 'name': REFSEC_REF_FIELD, 'value': REFSEC_OBJ_ID}

        merged = self._call(render, field, [], 3)

        assert any(f.get('name') == NAME_FIELD for f in merged)


class TestExternalsEdgeCases:
    """__set_externals skips unresolved links and swallows fill errors."""

    def test_external_not_found_skipped(self, managers) -> None:
        """A declared external whose lookup returns None is skipped."""
        render = _render(managers, [], types_cache={})
        link = Mock()
        link.name = EXT_NAME
        type_instance = Mock()
        type_instance.has_externals.return_value = True
        type_instance.get_externals.return_value = [link]
        type_instance.get_external.return_value = None

        assert render._CmdbMultiRender__set_externals(_main_obj(), type_instance) == []

    def test_external_fill_error_swallowed(self, managers) -> None:
        """An external whose href fill raises is skipped without aborting the render."""
        render = _render(managers, [], types_cache={})
        link = Mock()
        link.name = EXT_NAME
        link.link_requires_fields.return_value = True
        link.has_fields.return_value = True
        link.fields = [NAME_FIELD]
        link.fill_href.side_effect = RuntimeError('bad href')
        type_instance = Mock()
        type_instance.has_externals.return_value = True
        type_instance.get_externals.return_value = [link]
        type_instance.get_external.return_value = link

        assert render._CmdbMultiRender__set_externals(_main_obj(), type_instance) == []


class TestMergeErrorBranches:
    """Field/section merges degrade gracefully when a definition cannot be resolved."""

    def test_plain_section_field_merge_error_nulls_value(self, managers) -> None:
        """A section field the type cannot resolve degrades to a null value."""
        bad_type = CmdbType.from_data(make_type_doc(
            MAIN_TYPE_ID, 'bad-type',
            fields=[{'type': FieldType.TEXT, 'name': NAME_FIELD, 'label': 'Name'}],
            sections=[{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': ['ghost']}],
        ))
        render = _render(managers, [], types_cache={MAIN_TYPE_ID: bad_type})

        fields = render._CmdbMultiRender__merge_fields_value(_obj(MAIN_OBJ_ID, MAIN_TYPE_ID, []), bad_type, 3)

        assert fields[0]['value'] is None

    def test_orphan_reference_section_field_skipped(self, managers) -> None:
        """A ref-section whose implicit '<name>-field' is undefined is skipped."""
        orphan_type = CmdbType.from_data(make_type_doc(
            REFSEC_TYPE_ID, 'orphan-type',
            fields=[{'type': FieldType.TEXT, 'name': NAME_FIELD, 'label': 'Name'}],
            sections=[
                {'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [NAME_FIELD]},
                {'type': 'ref-section', 'name': 'orphan', 'label': 'Orphan',
                 'reference': {'type_id': REF_TYPE_ID, 'section_name': 'main', 'selected_fields': []},
                 'fields': []},
            ],
        ))
        section = orphan_type.render_meta.sections[1]
        render = _render(managers, [], ref_render=True, types_cache={REFSEC_TYPE_ID: orphan_type,
                                                                     REF_TYPE_ID: _ref_type()})

        assert render._merge_reference_section(section, _obj(REFSEC_OBJ_ID, REFSEC_TYPE_ID, []), orphan_type, 3) is None


class TestMergeReferencesSummaryLine:
    """__merge_references fills a configured nested summary line and tolerates lookup errors."""

    def _mock_ref_type(self) -> Mock:
        """A mock referenced type exposing the summary API used by __merge_references."""
        ref_type = Mock()
        ref_type.get_public_id.return_value = REF_TYPE_ID
        ref_type.label = 'ref'
        ref_type.get_icon.return_value = ''
        ref_type.has_nested_prefix.return_value = False
        ref_type.get_nested_summary_line.return_value = 'Name {}'
        ref_type.get_nested_summary_fields.return_value = [{'name': NAME_FIELD, 'type': FieldType.TEXT}]
        return ref_type

    def _render_with_mock_type(self, managers, ref_type: Mock) -> CmdbMultiRender:
        """Builds a render then injects the cached ref object/type (a mock type can't be linked in __init__)."""
        render = _render(managers, [], types_cache={}, objects_cache={})
        render.objects_cache[REF_OBJ_ID] = _ref_obj()
        render.types_cache[REF_TYPE_ID] = ref_type
        return render

    def test_nested_summary_line_filled(self, managers) -> None:
        """A configured nested summary line is filled from the referenced object's values."""
        render = self._render_with_mock_type(managers, self._mock_ref_type())

        reference = render._CmdbMultiRender__merge_references({'value': REF_OBJ_ID, 'summaries': [{}]})

        assert reference['line'] == f'Name {REF_NAME_VALUE}'

    def test_nested_summary_fields_lookup_error_falls_back(self, managers) -> None:
        """A CmdbTypeFieldNotFoundError while resolving nested fields is tolerated."""
        ref_type = self._mock_ref_type()
        ref_type.get_nested_summary_line.return_value = None
        ref_type.get_nested_summary_fields.side_effect = CmdbTypeFieldNotFoundError('x')
        ref_type.get_summary.return_value = Mock(fields=[{'name': NAME_FIELD, 'type': FieldType.TEXT}])
        render = self._render_with_mock_type(managers, ref_type)

        # no configured nested summaries -> after the lookup error it falls back to get_summary().fields
        reference = render._CmdbMultiRender__merge_references({'value': REF_OBJ_ID})

        assert reference['object_id'] == REF_OBJ_ID

    def test_reference_build_error_returns_empty(self, managers) -> None:
        """An error building the reference yields an empty reference rather than raising."""
        ref_type = self._mock_ref_type()
        ref_type.get_public_id.side_effect = RuntimeError('boom')
        render = self._render_with_mock_type(managers, ref_type)

        reference = render._CmdbMultiRender__merge_references({'value': REF_OBJ_ID})

        assert reference['object_id'] == 0

    def test_static_line_clears_summaries(self, managers) -> None:
        """A summary line with no placeholders needs no fields, so the summaries are cleared."""
        ref_type = self._mock_ref_type()
        ref_type.get_nested_summary_line.return_value = 'Static'
        render = self._render_with_mock_type(managers, ref_type)

        reference = render._CmdbMultiRender__merge_references({'value': REF_OBJ_ID, 'summaries': [{}]})

        assert reference['line'] == 'Static'
        assert reference['summaries'] == []

    def test_reference_expansion_field_error_skipped(self, managers) -> None:
        """A referenced summary field that fails to resolve is skipped in the expansion."""
        ref_type = self._mock_ref_type()
        ref_type.get_fields.return_value = [{'name': 'ghost'}]
        ref_type.get_field.side_effect = RuntimeError('no field')
        ref_type.public_id = REF_TYPE_ID
        ref_type.name = 'ref'
        render = self._render_with_mock_type(managers, ref_type)

        reference = render._build_reference_expansion(REF_OBJ_ID)

        assert reference['summaries'] == []


class TestLinkedObjectsFallback:
    """The untyped-field fallback in get_all_linked_objects tolerates a missing type."""

    def test_missing_type_skips_field(self, managers) -> None:
        """An untyped field whose type cannot be loaded contributes no reference."""
        obj = _obj(MAIN_OBJ_ID, MAIN_TYPE_ID, [{'name': REF_FIELD, 'value': REF_OBJ_ID}])
        render = _render(managers, [], types_cache={}, ref_render=True)
        render.to_render_objects = [obj]
        render.types_manager.get_type_instance.return_value = None

        assert render.get_all_linked_objects() == {}
