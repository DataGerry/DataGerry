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
from typing import Any
import logging
from unittest.mock import Mock, patch

import pytest

from cmdb.manager.manager_provider_model import ManagerType
from cmdb.framework.rendering import cmdb_multi_render as mr_module
from cmdb.framework.rendering import reference_read_scope as scope_module
from cmdb.framework.rendering.cmdb_multi_render import CmdbMultiRender
from cmdb.framework.rendering.render_constants import (
    ANONYMOUS_NAME,
    DEFAULT_RENDER_LEVEL,
    RenderProblemCode,
    RenderProblemKey,
    RenderedFieldKey,
    RenderedLocationReferenceKey,
    RenderedReferenceSectionKey,
    RenderTypeInfoKey,
)
from cmdb.framework.rendering.render_result import RenderResult
from cmdb.models.type_model import CmdbType
from cmdb.models.type_model.type_section import TypeSection
from cmdb.models.type_model import TypeFieldSection
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model.type_reference import TypeReference
from cmdb.models.type_model.type_external_link import TypeExternalLink
from cmdb.models.type_model.type_reference_key_enum import TypeReferenceKey
from cmdb.errors.models.cmdb_type import CmdbTypeFieldNotFoundError
from tests.utils.ipam_doc_builders import make_type_doc
# The render's steps are private methods, and these tests drive them one at a time
# pylint: disable=protected-access
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
# Declared by the TYPE but carried by no object - what a field added to a type looks like until the
# existing objects are saved again
MISSING_ON_OBJECT_FIELD: str = 'added-after-the-objects'

# Listed by a section, declared by no type: what a stored type written without the structure guard holds
GHOST_FIELD: str = 'ghost'

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
    """
    Patches ManagerProvider.get_manager to hand out per-type mock managers (empty lookups)

    The render user's denied types are patched too - nothing denied unless a test sets
    `managers.denied_type_ids` - so the read scope never reaches the database
    """
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
    namespace = SimpleNamespace(objects=objects_m, types=types_m, users=users_m, denied_type_ids=[])
    monkeypatch.setattr(
        scope_module, 'resolve_denied_type_ids', lambda _user, _permission: namespace.denied_type_ids,
    )
    return namespace


def _render(managers, to_render, ref_render=False, objects_cache=None, types_cache=None, users_cache=None):
    # managers is the active ManagerProvider patch fixture; requesting it keeps the patch in scope
    # pylint: disable=unused-argument
    """
    Builds a CmdbMultiRender with the patched managers, then seeds its caches

    The constructor loads through the patched managers; a cache a test names replaces what it loaded, which
    is what the constructor's own loading would have produced from a real database
    """
    render = CmdbMultiRender(to_render, Mock(name='render_user'), ref_render)

    for attribute, seeded in (('objects_cache', objects_cache), ('types_cache', types_cache),
                              ('users_cache', users_cache)):
        if seeded is not None:
            setattr(render, attribute, seeded)

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

        info = render._generate_object_information(_main_obj())

        assert info['object_id'] == MAIN_OBJ_ID
        assert info['author_name'] == ANONYMOUS_NAME

    def test_type_information_icon_fallback(self, managers) -> None:
        """A type whose render_meta has no icon falls back to an empty icon string."""
        main_type = _main_type()
        del main_type.render_meta.__dict__['icon']
        render = _render(managers, [], types_cache={MAIN_TYPE_ID: main_type})

        info = render._generate_type_information(main_type)

        assert info['icon'] == ''

    def test_type_information_carries_the_capability_flags(self, managers) -> None:
        """
        The two TYPE-level capability flags are forwarded to the render result

        `uses_ports` is what decides whether a client renders the ports panel for an object, and
        `selectable_as_parent` whether the object may be offered as a location parent. Absent from
        the block, either would force a client to fetch the CmdbType separately for one boolean on a
        view that already has the type server-side.
        """
        main_type = _main_type()
        main_type.uses_ports = True
        main_type.selectable_as_parent = False
        render = _render(managers, [], types_cache={MAIN_TYPE_ID: main_type})

        info = render._generate_type_information(main_type)

        assert info[RenderTypeInfoKey.USES_PORTS.value] is True
        assert info[RenderTypeInfoKey.SELECTABLE_AS_PARENT.value] is False

    @pytest.mark.parametrize('flag', [RenderTypeInfoKey.USES_PORTS, RenderTypeInfoKey.SELECTABLE_AS_PARENT])
    def test_a_type_predating_a_flag_still_renders(self, managers, flag: RenderTypeInfoKey) -> None:
        """
        A CmdbType whose document never carried the flag renders as False instead of raising

        `uses_ports` was added to the model long after most installations had types, and
        `updater_20260901` backfills it - but the renderer must not depend on that migration having
        run, because a render is a read and a read must not fail on older data.
        """
        main_type = _main_type()
        del main_type.__dict__[flag.value]
        render = _render(managers, [], types_cache={MAIN_TYPE_ID: main_type})

        info = render._generate_type_information(main_type)

        assert info[flag.value] is False

    def test_type_information_flags_are_real_booleans(self, managers) -> None:
        """
        A truthy stored value is normalised, so a client can compare with ===

        Older documents can carry the flag as a string, and the frontend model declares it as a
        boolean.
        """
        main_type = _main_type()
        main_type.uses_ports = 'true'
        render = _render(managers, [], types_cache={MAIN_TYPE_ID: main_type})

        info = render._generate_type_information(main_type)

        assert info[RenderTypeInfoKey.USES_PORTS.value] is True

    def test_type_information_carries_the_port_section_index(self, managers) -> None:
        """
        Where the ports panel sits is forwarded alongside the flag that decides whether it renders

        `uses_ports` alone only tells a client THAT the panel exists; the object view also has to
        know where to draw it among the type's sections, and it has the type server-side already.
        """
        main_type = _main_type()
        main_type.uses_ports = True
        main_type.port_section_index = 3
        render = _render(managers, [], types_cache={MAIN_TYPE_ID: main_type})

        info = render._generate_type_information(main_type)

        assert info[RenderTypeInfoKey.PORT_SECTION_INDEX.value] == 3

    def test_a_type_predating_the_port_section_index_still_renders(self, managers) -> None:
        """
        A CmdbType whose document never carried the key renders as 0 instead of raising

        `updater_20260918` backfills it, but a render is a read and a read must not depend on that
        migration having run.
        """
        main_type = _main_type()
        del main_type.__dict__[RenderTypeInfoKey.PORT_SECTION_INDEX.value]
        render = _render(managers, [], types_cache={MAIN_TYPE_ID: main_type})

        info = render._generate_type_information(main_type)

        assert info[RenderTypeInfoKey.PORT_SECTION_INDEX.value] == 0

    def test_type_information_key_set_is_exactly_the_enum(self, managers) -> None:
        """
        The block is a curated selection, and this is what says so

        A key added to the dict without a `RenderTypeInfoKey` member (or the reverse) fails here -
        which is the check that was missing when `uses_ports` was added to CmdbType and silently did
        not reach the render result.
        """
        render = _render(managers, [], types_cache={MAIN_TYPE_ID: _main_type()})

        info = render._generate_type_information(_main_type())

        assert set(info) == {member.value for member in RenderTypeInfoKey}


class TestTypeSections:
    """_get_type_sections serialises the type sections and degrades on error."""

    def test_returns_serialised_sections(self, managers) -> None:
        """The sections of the type are serialised to dicts."""
        render = _render(managers, [], types_cache={MAIN_TYPE_ID: _main_type()})

        sections = render._get_type_sections(_main_type())

        assert isinstance(sections, list) and len(sections) == 1

    def test_serialisation_error_returns_empty(self, managers) -> None:
        """A section that fails to serialise yields an empty list."""
        render = _render(managers, [], types_cache={})
        bad_type = Mock()
        bad_section = Mock()
        bad_section.to_json.side_effect = RuntimeError('boom')
        bad_type.render_meta.sections = [bad_section]

        assert render._get_type_sections(bad_type) == []


class TestExternals:
    """_set_externals resolves external links and skips those with missing values."""

    def test_no_externals(self, managers) -> None:
        """A type without external links yields an empty list."""
        render = _render(managers, [], types_cache={REF_TYPE_ID: _ref_type()})

        assert render._set_externals(_ref_obj(), _ref_type()) == []

    def test_external_resolved(self, managers) -> None:
        """An external link with all required values is filled and returned."""
        render = _render(managers, [], types_cache={MAIN_TYPE_ID: _main_type()})

        externals = render._set_externals(_main_obj(), _main_type())

        assert len(externals) == 1
        assert externals[0]['href'] == f'http://x/{MAIN_NAME_VALUE}'

    def test_a_second_object_does_not_inherit_the_first_objects_url(self, managers) -> None:
        """
        The regression: ONE cached CmdbType, two objects, two different links

        The type cache hands the same CmdbType - and therefore the same TypeExternalLink - to every
        object of that type in a batch. Filling the href IN PLACE left the first object's values in the
        template, after which `link_requires_fields()` answered False and every following object was
        served the first one's URL. The sibling tests above cannot see this: each builds a fresh
        `_main_type()`, so the shared instance never exists.
        """
        shared_type = _main_type()
        first = _obj(MAIN_OBJ_ID, MAIN_TYPE_ID,
                     [{'type': FieldType.TEXT, 'name': NAME_FIELD, 'value': 'object-A'}])
        second = _obj(MAIN_OBJ_ID + 1, MAIN_TYPE_ID,
                      [{'type': FieldType.TEXT, 'name': NAME_FIELD, 'value': 'object-B'}])
        render = _render(managers, [first, second], types_cache={MAIN_TYPE_ID: shared_type})

        results = render.result()

        assert [result.externals[0]['href'] for result in results] == ['http://x/object-A',
                                                                       'http://x/object-B']

    def test_the_cached_template_is_left_unfilled(self, managers) -> None:
        """The type in the cache must still carry its placeholders after a render"""
        shared_type = _main_type()
        render = _render(managers, [_main_obj()], types_cache={MAIN_TYPE_ID: shared_type})

        render.result()

        assert shared_type.get_external(EXT_NAME).href == 'http://x/{}'

    def test_external_missing_value_skipped(self, managers) -> None:
        """An external link whose required field has no value is skipped."""
        obj = _obj(MAIN_OBJ_ID, MAIN_TYPE_ID, [{'type': FieldType.TEXT, 'name': NAME_FIELD, 'value': ''}])
        render = _render(managers, [], types_cache={MAIN_TYPE_ID: _main_type()})

        assert render._set_externals(obj, _main_type()) == []


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
    """_set_summaries fills the summaries/summary line with a default fallback."""

    def test_no_summaries_uses_default_line(self, managers) -> None:
        """A type with no summary fields yields an empty summaries list and the default line."""
        main_type = _main_type()
        main_type.render_meta.summary.fields = []
        render = _render(managers, [], types_cache={MAIN_TYPE_ID: main_type})
        result = render._set_summaries(RenderResult(), _main_obj(), main_type)

        assert result.summaries == []
        assert result.summary_line == f'{main_type.label} #{MAIN_OBJ_ID}'

    def test_summaries_filled(self, managers) -> None:
        """A configured summary field drives the summaries and summary line."""
        main_type = _main_type()
        render = _render(managers, [], types_cache={MAIN_TYPE_ID: main_type})
        result = render._set_summaries(RenderResult(), _main_obj(), main_type)

        assert result.summary_line == MAIN_NAME_VALUE

    def test_summary_error_falls_back_to_default(self, managers) -> None:
        """
        A summary field the OBJECT does not carry falls back to the default line

        This is what actually reaches `_set_summaries`' except arm: `CmdbObject.get_value` raises
        `ValueError` for a field the object has no row for, which happens whenever a field is added to
        a type and put in its summary before existing objects are saved.

        Writing it as `summary.fields = ['does-not-exist']` reaches the same arm only
        because `CmdbType.get_summary` raised for a name missing from the TYPE. Since that accessor now
        skips a stale name, that setup stopped exercising this path while still passing - the two cases
        produce identical output - so they are pinned separately below.
        """
        main_type = _main_type()
        main_type.render_meta.summary.fields = [MISSING_ON_OBJECT_FIELD]
        main_type.fields = main_type.fields + [{'name': MISSING_ON_OBJECT_FIELD, 'type': FieldType.TEXT}]
        render = _render(managers, [], types_cache={MAIN_TYPE_ID: main_type})

        result = render._set_summaries(RenderResult(), _main_obj(), main_type)

        assert result.summaries == []
        assert result.summary_line == f'{main_type.label} #{MAIN_OBJ_ID}'

    def test_a_summary_name_missing_from_the_type_is_skipped_not_fatal(self, managers) -> None:
        """
        A stale summary name costs its own entry, not the whole summary

        `CmdbType.get_summary` drops a name that no longer resolves to a field, so the remaining
        summary fields still render. With NO valid name left the result is the default line - which is
        why this reads the same as the case above and has to be asserted separately.
        """
        main_type = _main_type()
        main_type.render_meta.summary.fields = ['does-not-exist']
        render = _render(managers, [], types_cache={MAIN_TYPE_ID: main_type})

        result = render._set_summaries(RenderResult(), _main_obj(), main_type)

        assert result.summaries == []
        assert result.summary_line == f'{main_type.label} #{MAIN_OBJ_ID}'

    def test_a_stale_name_beside_a_valid_one_keeps_the_valid_summary(self, managers) -> None:
        """The behaviour the skip was introduced for: a partial summary beats no summary at all"""
        main_type = _main_type()
        main_type.render_meta.summary.fields = ['does-not-exist', NAME_FIELD]
        render = _render(managers, [], types_cache={MAIN_TYPE_ID: main_type})

        result = render._set_summaries(RenderResult(), _main_obj(), main_type)

        assert [entry['name'] for entry in result.summaries] == [NAME_FIELD]
        assert result.summary_line == MAIN_NAME_VALUE


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
    """_merge_field_content_section merges the object value onto a type field."""

    def _merge(self, render, t_field, obj):
        """Invokes the name-mangled _merge_field_content_section."""
        return render._merge_field_content_section(t_field, obj)

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

    def test_a_field_without_a_default_still_carries_a_value_key(self, managers) -> None:
        """A rendered field entry is a name+value+type TRIPLE, whatever the object holds

        A type field with no configured default has no `value` key at all, so returning it unchanged
        answered a field a consumer cannot read a value off - `undefined` rather than null on the
        frontend, for every field an object has no entry for. Reachable without any stale data: a
        create that sends only some of the Type's fields leaves the rest in exactly this state.
        """
        render = _render(managers, [], types_cache={})
        obj = _obj(REF_OBJ_ID, REF_TYPE_ID, [])

        merged = self._merge(render, {'name': NAME_FIELD, 'type': FieldType.TEXT}, obj)

        assert 'value' in merged
        assert merged['value'] is None

    def test_a_configured_default_is_not_overwritten_by_the_fallback(self, managers) -> None:
        """`setdefault` only establishes the key - a type default still reaches the reader"""
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

    def test_an_unreadable_date_string_is_left_as_it_is(self, managers) -> None:
        """
        The one place a date is read out of USER data, so it must not be invented

        A DATE field whose stored value is free text must not be parsed with `fuzzy=True`: 'ask Bob'
        rendered as a date assembled from today, on READ, and travelled into every export and report
        without the stored document ever changing. Refusing is not an option either - the render is
        crash-tolerant by construction - so the raw value survives and the reader sees what is stored.
        """
        render = _render(managers, [], types_cache={})
        obj = _obj(MAIN_OBJ_ID, MAIN_TYPE_ID, [{'type': FieldType.DATE, 'name': DATE_FIELD, 'value': 'ask Bob'}])

        merged = self._merge(render, {'name': DATE_FIELD, 'type': FieldType.DATE, 'value': None}, obj)

        assert merged['value'] == 'ask Bob'

    def test_the_mongo_wrapper_shape_is_read_too(self, managers) -> None:
        """The frontend sends a date back as `{'$date': <millis>}`, and a re-render must read it."""
        render = _render(managers, [], types_cache={})
        obj = _obj(MAIN_OBJ_ID, MAIN_TYPE_ID,
                   [{'type': FieldType.DATE, 'name': DATE_FIELD, 'value': '2026-03-01T10:00:00'}])

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
    """_merge_references / _build_reference_summaries resolve a reference field to a TypeReference."""

    def _merge(self, render, field):
        """Invokes the name-mangled _merge_references."""
        return render._merge_references(field)

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

    def _merge_entry(self, managers, caplog, entry: dict[str, Any]) -> dict[str, Any]:
        """Renders the reference with one nested-summary entry for the referenced type; no WARNING allowed."""
        render = _render(managers, [], objects_cache={REF_OBJ_ID: _ref_obj()},
                         types_cache={REF_TYPE_ID: _ref_type()})

        with caplog.at_level('WARNING'):
            reference = self._merge(render, {'name': REF_FIELD, 'value': REF_OBJ_ID, 'summaries': [entry]})

        assert caplog.text == ''
        assert reference['type_id'] == REF_TYPE_ID

        return reference

    def test_an_entry_without_prefix_renders_with_the_schema_default(self, managers, caplog) -> None:
        """What the type import stores as sent renders as the type route would have stored it"""
        reference = self._merge_entry(managers, caplog, {'type_id': REF_TYPE_ID, 'line': 'Device {}',
                                                         'fields': [NAME_FIELD]})

        assert reference['prefix'] is True
        assert reference['line'] == f'Device {REF_NAME_VALUE}'

    def test_an_entry_without_fields_renders_its_line(self, managers, caplog) -> None:
        """No `fields` is an empty list: a static line is shown as it is"""
        reference = self._merge_entry(managers, caplog, {'type_id': REF_TYPE_ID, 'line': 'See the rack plan',
                                                         'prefix': False})

        assert reference['line'] == 'See the rack plan'
        assert reference['summaries'] == []

    def test_an_entry_without_a_line_renders_its_summary_fields(self, managers, caplog) -> None:
        """No `line` is no line: the entry's summary fields are what the reference shows"""
        reference = self._merge_entry(managers, caplog, {'type_id': REF_TYPE_ID, 'fields': [NAME_FIELD],
                                                         'prefix': False})

        assert reference['line'] is None
        assert [summary['value'] for summary in reference['summaries']] == [REF_NAME_VALUE]

    def test_a_reference_that_cannot_be_built_is_reported(self, managers, caplog, monkeypatch) -> None:
        """The degraded answer is logged at WARNING, naming the field and the referenced object"""
        render = _render(managers, [], objects_cache={REF_OBJ_ID: _ref_obj()},
                         types_cache={REF_TYPE_ID: _ref_type()})
        monkeypatch.setattr(CmdbType, 'has_nested_prefix', Mock(side_effect=KeyError('prefix')))

        with caplog.at_level('WARNING'):
            reference = self._merge(render, {'name': REF_FIELD, 'value': REF_OBJ_ID})

        assert reference['summaries'] == []
        assert REF_FIELD in caplog.text
        assert str(REF_OBJ_ID) in caplog.text


class TestMergeFieldsValue:
    """_merge_fields_value and its section helpers build the merged field list."""

    def test_level_zero_returns_empty(self, managers) -> None:
        """A level of 0 stops the recursion with an empty field list."""
        render = _render(managers, [], types_cache={MAIN_TYPE_ID: _main_type()})

        assert render._merge_fields_value(_main_obj(), _main_type(), 0) == []

    def test_plain_section_reference_expanded(self, managers) -> None:
        """A reference field in a plain section gets its reference expansion filled."""
        render = _render(managers, [], ref_render=True, objects_cache={REF_OBJ_ID: _ref_obj()},
                         types_cache={MAIN_TYPE_ID: _main_type(), REF_TYPE_ID: _ref_type()})

        fields = render._merge_fields_value(_main_obj(), _main_type(), 3)

        assert _field(fields, REF_FIELD)['reference']['object_id'] == REF_OBJ_ID
        assert _field(fields, LOC_FIELD)['reference']['object_id'] == REF_OBJ_ID

    def test_reference_field_without_ref_render_clears_value(self, managers) -> None:
        """Without a resolvable reference the field value is cleared to None."""
        render = _render(managers, [], ref_render=False, types_cache={MAIN_TYPE_ID: _main_type()})

        fields = render._merge_fields_value(_main_obj(), _main_type(), 3)

        assert _field(fields, REF_FIELD)['value'] is None

    def test_reference_section_merged(self, managers) -> None:
        """A ref-section resolves the referenced type/section and merges its fields."""
        refsec_obj = _obj(REFSEC_OBJ_ID, REFSEC_TYPE_ID, [
            {'type': FieldType.TEXT, 'name': NAME_FIELD, 'value': 'Owner'},
            {'type': FieldType.REFERENCE, 'name': REFSEC_REF_FIELD, 'value': REF_OBJ_ID},
        ])
        render = _render(managers, [], ref_render=True, objects_cache={REF_OBJ_ID: _ref_obj()},
                         types_cache={REFSEC_TYPE_ID: _refsec_type(), REF_TYPE_ID: _ref_type()})

        fields = render._merge_fields_value(refsec_obj, _refsec_type(), 3)

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

        fields = render._merge_fields_value(refsec_obj, _refsec_type(), 3)

        # only the plain 'main' section field survives; the ref-section is dropped
        assert all('references' not in f for f in fields)


class TestTheRenderedReferencePayload:
    """Every render path fills a reference field with the SAME seven-key TypeReference payload."""

    EXTRA_FIELD: str = 'not-a-summary-field'
    EXTRA_VALUE: str = 'ignored by the summary'

    def _two_field_ref_type(self) -> CmdbType:
        """A referenced type with two fields, of which only the first is its summary field."""
        return CmdbType.from_data(make_type_doc(
            REF_TYPE_ID, 'ref-type',
            fields=[
                {'type': FieldType.TEXT, 'name': NAME_FIELD, 'label': 'Name'},
                {'type': FieldType.TEXT, 'name': self.EXTRA_FIELD, 'label': 'Extra'},
            ],
            sections=[{'type': 'section', 'name': 'main', 'label': 'Main',
                       'fields': [NAME_FIELD, self.EXTRA_FIELD]}],
        ))

    def _two_field_ref_obj(self) -> CmdbObject:
        """The referenced object carrying a value for both of those fields."""
        return _obj(REF_OBJ_ID, REF_TYPE_ID, [
            {'type': FieldType.TEXT, 'name': NAME_FIELD, 'value': REF_NAME_VALUE},
            {'type': FieldType.TEXT, 'name': self.EXTRA_FIELD, 'value': self.EXTRA_VALUE},
        ])

    def _render_main(self, managers) -> CmdbMultiRender:
        """A ref-rendering CmdbMultiRender over the main object, with the two-field ref type cached."""
        return _render(
            managers, [_main_obj()], ref_render=True,
            objects_cache={REF_OBJ_ID: self._two_field_ref_obj()},
            types_cache={MAIN_TYPE_ID: _main_type(), REF_TYPE_ID: self._two_field_ref_type()},
        )

    def test_a_plain_section_reference_is_a_full_type_reference(self, managers) -> None:
        """
        A reference field of a plain section renders the complete TypeReference payload

        The frontend reads LINE, ICON and PREFIX out of this block, so a short payload leaves the
        reference field rendering without them
        """
        # result(single_object=True) returns a single RenderResult; pylint infers the list union
        # pylint: disable=no-member
        result = self._render_main(managers).result(single_object=True)

        reference = _field(result.fields, REF_FIELD)[RenderedFieldKey.REFERENCE.value]

        assert set(reference) == {key.value for key in TypeReferenceKey}
        assert reference[TypeReferenceKey.OBJECT_ID.value] == REF_OBJ_ID
        assert reference[TypeReferenceKey.TYPE_ID.value] == REF_TYPE_ID

    def test_the_summaries_are_the_types_configured_summary_fields(self, managers) -> None:
        """
        Only the referenced type's SUMMARY fields are summarised, not every field it defines

        An expansion built for a plain section would list all of them, so a type with twenty
        fields shipped twenty summary entries per reference - and the frontend showed them
        """
        # pylint: disable=no-member
        result = self._render_main(managers).result(single_object=True)

        summaries = _field(result.fields, REF_FIELD)[RenderedFieldKey.REFERENCE.value][
            RenderedFieldKey.SUMMARIES.value
        ]

        assert [entry[FieldKey.VALUE.value] for entry in summaries] == [REF_NAME_VALUE]

    def test_the_expansion_path_agrees_with_the_merge_path(self, managers) -> None:
        """
        `_expand_reference_field` (used when the merge did not expand) answers the same payload

        The two paths are the reason the same `reference` key can end up carrying two shapes
        """
        # pylint: disable=no-member
        render = self._render_main(managers)
        merged = render.result(single_object=True)

        expanded = render._expand_reference_field(REF_FIELD, _main_obj(), _main_type())

        assert expanded[RenderedFieldKey.REFERENCE.value] == \
            _field(merged.fields, REF_FIELD)[RenderedFieldKey.REFERENCE.value]

    def test_a_location_reference_stays_a_placeholder(self, managers) -> None:
        """A location field is the ONE expansion that is not a TypeReference - nothing resolves it."""
        render = _render(managers, [], types_cache={})

        reference = render._build_location_reference(REF_OBJ_ID)

        assert set(reference) == {key.value for key in RenderedLocationReferenceKey}
        assert reference[RenderedLocationReferenceKey.OBJECT_ID.value] == REF_OBJ_ID


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

        render._merge_fields_value(refsec_obj, refsec_type, 3)

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


class TestReferenceSectionDepth:
    """The ref-section merge stops recursing at level 0 but still pulls the section's own fields."""

    def test_level_zero_pulls_the_fields_without_recursing(self, managers) -> None:
        """At the bottom of the recursion a pulled field keeps its value and gains no nested block."""
        refsec_obj = _obj(REFSEC_OBJ_ID, REFSEC_TYPE_ID, [
            {'type': FieldType.TEXT, 'name': NAME_FIELD, 'value': 'Owner'},
            {'type': FieldType.REFERENCE, 'name': REFSEC_REF_FIELD, 'value': REF_OBJ_ID},
        ])
        refsec_type = _refsec_type()
        render = _render(managers, [], ref_render=True, objects_cache={REF_OBJ_ID: _ref_obj()},
                         types_cache={REFSEC_TYPE_ID: refsec_type, REF_TYPE_ID: _ref_type()})

        ref_field = render._merge_reference_section(
            refsec_type.render_meta.sections[1], refsec_obj, refsec_type, 0
        )

        pulled = ref_field[RenderedFieldKey.REFERENCES.value][RenderedReferenceSectionKey.FIELDS.value]
        assert [field[FieldKey.VALUE.value] for field in pulled] == [REF_NAME_VALUE]


class TestReportsAnUnresolvableReferenceSection:
    """
    The three ways a reference section renders nothing, each of which is otherwise entirely silent

    A CmdbType update now refuses the edits that cause them, but data written before that guard can
    still be in a database, so the render says so at WARNING instead of quietly dropping the block.
    """

    def _section(self, refsec_type: CmdbType):
        """Returns the TypeReferenceSection of the refsec type."""
        return refsec_type.render_meta.sections[1]

    def _refsec_obj(self) -> CmdbObject:
        """A refsec object referencing the ref object."""
        return _obj(REFSEC_OBJ_ID, REFSEC_TYPE_ID, [
            {'type': FieldType.TEXT, 'name': NAME_FIELD, 'value': 'Owner'},
            {'type': FieldType.REFERENCE, 'name': REFSEC_REF_FIELD, 'value': REF_OBJ_ID},
        ])

    def test_reports_a_missing_referenced_type(self, managers, caplog) -> None:
        """The referenced type is gone - the block disappears, and now says why"""
        refsec_type = _refsec_type()
        render = _render(managers, [], ref_render=True, types_cache={REFSEC_TYPE_ID: refsec_type})

        with caplog.at_level('WARNING'):
            assert render._merge_reference_section(
                self._section(refsec_type), self._refsec_obj(), refsec_type, 3,
            ) is None

        assert 'does not exist' in caplog.text
        assert REFSEC_NAME in caplog.text

    def test_reports_a_missing_referenced_section(self, managers, caplog) -> None:
        """The reported bug: the section was deleted from the referenced type"""
        refsec_type = _refsec_type()
        section = self._section(refsec_type)
        section.reference.section_name = 'ghost'
        render = _render(managers, [], ref_render=True, objects_cache={REF_OBJ_ID: _ref_obj()},
                         types_cache={REFSEC_TYPE_ID: refsec_type, REF_TYPE_ID: _ref_type()})

        with caplog.at_level('WARNING'):
            assert render._merge_reference_section(section, self._refsec_obj(), refsec_type, 3) is None

        assert "has no section 'ghost'" in caplog.text

    def test_reports_a_section_carrying_none_of_the_selected_fields(self, managers, caplog) -> None:
        """The field-side case: the section survives but shows nothing"""
        refsec_type = _refsec_type()
        section = self._section(refsec_type)
        section.reference.selected_fields = ['gone']
        render = _render(managers, [], ref_render=True, objects_cache={REF_OBJ_ID: _ref_obj()},
                         types_cache={REFSEC_TYPE_ID: refsec_type, REF_TYPE_ID: _ref_type()})

        with caplog.at_level('WARNING'):
            ref_field = render._merge_reference_section(section, self._refsec_obj(), refsec_type, 3)

        assert "carries none of the referenced field(s) ['gone']" in caplog.text
        # behaviour unchanged: the field is still returned, with an empty reference list
        assert ref_field['references']['fields'] == []

    def test_says_nothing_when_the_section_resolves(self, managers, caplog) -> None:
        """A working reference section must not log at all"""
        refsec_type = _refsec_type()
        render = _render(managers, [], ref_render=True, objects_cache={REF_OBJ_ID: _ref_obj()},
                         types_cache={REFSEC_TYPE_ID: refsec_type, REF_TYPE_ID: _ref_type()})

        with caplog.at_level('WARNING'):
            render._merge_reference_section(self._section(refsec_type), self._refsec_obj(), refsec_type, 3)

        assert caplog.text == ''

    def test_reports_one_broken_reference_once_per_render(self, managers, caplog) -> None:
        """
        A list render walks many objects through the same type definition

        Without the per-render dedupe a single broken ref-section would emit one warning per object,
        which for a large list is a log flood rather than a diagnosis.
        """
        refsec_type = _refsec_type()
        section = self._section(refsec_type)
        section.reference.section_name = 'ghost'
        render = _render(managers, [], ref_render=True, objects_cache={REF_OBJ_ID: _ref_obj()},
                         types_cache={REFSEC_TYPE_ID: refsec_type, REF_TYPE_ID: _ref_type()})

        with caplog.at_level('WARNING'):
            for _ in range(5):
                render._merge_reference_section(section, self._refsec_obj(), refsec_type, 3)

        assert caplog.text.count('has no section') == 1

    def test_a_reference_repointed_at_another_target_is_reported_again(self, managers, caplog) -> None:
        """
        The dedupe is per reference, not one line per render

        The same section aimed at a different (also missing) section is a different problem, so
        silencing it would hide half the diagnosis.
        """
        refsec_type = _refsec_type()
        section = self._section(refsec_type)
        render = _render(managers, [], ref_render=True, objects_cache={REF_OBJ_ID: _ref_obj()},
                         types_cache={REFSEC_TYPE_ID: refsec_type, REF_TYPE_ID: _ref_type()})

        with caplog.at_level('WARNING'):
            section.reference.section_name = 'ghost'
            render._merge_reference_section(section, self._refsec_obj(), refsec_type, 3)
            section.reference.section_name = 'other-ghost'
            render._merge_reference_section(section, self._refsec_obj(), refsec_type, 3)

        assert caplog.text.count('has no section') == 2


class TestExternalsEdgeCases:
    """_set_externals skips unresolved links and swallows fill errors."""

    def test_external_not_found_skipped(self, managers) -> None:
        """A declared external whose lookup returns None is skipped."""
        render = _render(managers, [], types_cache={})
        link = Mock()
        link.name = EXT_NAME
        type_instance = Mock()
        type_instance.has_externals.return_value = True
        type_instance.get_externals.return_value = [link]
        type_instance.get_external.return_value = None

        assert render._set_externals(_main_obj(), type_instance) == []

    def test_external_fill_error_swallowed(self, managers) -> None:
        """An external whose href fill raises is skipped without aborting the render."""
        render = _render(managers, [], types_cache={})
        link = Mock()
        link.name = EXT_NAME
        link.link_requires_fields.return_value = True
        link.has_fields.return_value = True
        link.fields = [NAME_FIELD]
        link.filled_href.side_effect = RuntimeError('bad href')
        type_instance = Mock()
        type_instance.has_externals.return_value = True
        type_instance.get_externals.return_value = [link]
        type_instance.get_external.return_value = link

        assert render._set_externals(_main_obj(), type_instance) == []


class TestMergeErrorBranches:
    """Field/section merges degrade gracefully when a definition cannot be resolved."""

    def test_a_section_field_the_type_does_not_declare_is_left_out(self, managers) -> None:
        """
        A name the section lists but the type does not declare answers no entry at all

        There is no definition to answer it with, and an entry holding only a value - no name, no
        type - is one no consumer can read
        """
        bad_type = CmdbType.from_data(make_type_doc(
            MAIN_TYPE_ID, 'bad-type',
            fields=[{'type': FieldType.TEXT, 'name': NAME_FIELD, 'label': 'Name'}],
            sections=[{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [GHOST_FIELD, NAME_FIELD]}],
        ))
        render = _render(managers, [], types_cache={MAIN_TYPE_ID: bad_type})

        fields = render._merge_fields_value(_obj(MAIN_OBJ_ID, MAIN_TYPE_ID, []), bad_type, 3)

        assert [field['name'] for field in fields] == [NAME_FIELD]

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
    """_merge_references fills a configured nested summary line and tolerates lookup errors."""

    def _mock_ref_type(self) -> Mock:
        """A mock referenced type exposing the summary API used by _merge_references."""
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

        reference = render._merge_references({'value': REF_OBJ_ID, 'summaries': [{}]})

        assert reference['line'] == f'Name {REF_NAME_VALUE}'

    def test_nested_summary_fields_lookup_error_falls_back(self, managers) -> None:
        """A CmdbTypeFieldNotFoundError while resolving nested fields is tolerated."""
        ref_type = self._mock_ref_type()
        ref_type.get_nested_summary_line.return_value = None
        ref_type.get_nested_summary_fields.side_effect = CmdbTypeFieldNotFoundError('x')
        ref_type.get_summary.return_value = Mock(fields=[{'name': NAME_FIELD, 'type': FieldType.TEXT}])
        render = self._render_with_mock_type(managers, ref_type)

        # no configured nested summaries -> after the lookup error it falls back to get_summary().fields
        reference = render._merge_references({'value': REF_OBJ_ID})

        assert reference['object_id'] == REF_OBJ_ID

    def test_reference_build_error_returns_empty(self, managers) -> None:
        """An error building the reference yields an empty reference rather than raising."""
        ref_type = self._mock_ref_type()
        ref_type.get_public_id.side_effect = RuntimeError('boom')
        render = self._render_with_mock_type(managers, ref_type)

        reference = render._merge_references({'value': REF_OBJ_ID})

        assert reference['object_id'] == 0

    def test_static_line_clears_summaries(self, managers) -> None:
        """A summary line with no placeholders needs no fields, so the summaries are cleared."""
        ref_type = self._mock_ref_type()
        ref_type.get_nested_summary_line.return_value = 'Static'
        render = self._render_with_mock_type(managers, ref_type)

        reference = render._merge_references({'value': REF_OBJ_ID, 'summaries': [{}]})

        assert reference['line'] == 'Static'
        assert reference['summaries'] == []

    def test_no_line_keeps_the_summaries_the_frontend_shows(self, managers) -> None:
        """
        Without a nested summary line the summaries stay filled - they ARE what the reference shows

        The frontend's reference components render `summaries` exactly when `line` is empty, so a
        reference without a line that answered `summaries: []` would render as a bare icon and label.
        The summaries are the referenced type's default summary fields, with the object's values
        """
        ref_type = self._mock_ref_type()
        ref_type.get_nested_summary_line.return_value = None
        ref_type.get_nested_summary_fields.return_value = []
        ref_type.get_summary.return_value = Mock(fields=[{'name': NAME_FIELD, 'type': FieldType.TEXT}])
        render = self._render_with_mock_type(managers, ref_type)

        reference = render._merge_references({'value': REF_OBJ_ID})

        assert reference['line'] is None
        assert reference['summaries'] == [{'value': REF_NAME_VALUE, 'type': FieldType.TEXT}]

    def test_the_expansion_serialises_a_type_reference(self, managers) -> None:
        """
        `_build_reference_expansion` answers the SAME payload as the inline merge

        Building a five-key dict of its own would leave out `line`, `icon` and `prefix`, and
        `summaries` holding every field of the referenced type instead of its configured summary
        fields - so one `reference` key carried two shapes depending on the render path.
        """
        render = self._render_with_mock_type(managers, self._mock_ref_type())

        reference = render._build_reference_expansion(REF_OBJ_ID)

        assert set(reference) == {key.value for key in TypeReferenceKey}
        assert reference[TypeReferenceKey.LINE.value] == f'Name {REF_NAME_VALUE}'

    def test_an_unresolvable_reference_is_reported_as_none(self, managers) -> None:
        """The callers clear the field's value on None, so the empty reference maps back to it."""
        render = _render(managers, [], types_cache={}, objects_cache={})

        assert render._build_reference_expansion(REF_OBJ_ID) is None


class TestLinkedObjectsFallback:
    """The untyped-field fallback in get_all_linked_objects tolerates a missing type."""

    def test_missing_type_skips_field(self, managers) -> None:
        """An untyped field whose type cannot be loaded contributes no reference."""
        obj = _obj(MAIN_OBJ_ID, MAIN_TYPE_ID, [{'name': REF_FIELD, 'value': REF_OBJ_ID}])
        render = _render(managers, [], types_cache={}, ref_render=True)
        render.to_render_objects = [obj]
        render.types_manager.get_type_instance.return_value = None

        assert render.get_all_linked_objects() == {}

    def test_the_fallback_type_is_fetched_once_per_type(self, managers) -> None:
        """
        Several untyped fields of the same type cost ONE type lookup, not one per field

        Re-querying the type for every untyped field would be an N+1 over the whole
        render, on exactly the legacy objects that trip it
        """
        untyped = _obj(MAIN_OBJ_ID, MAIN_TYPE_ID, [
            {'name': REF_FIELD, 'value': REF_OBJ_ID},
            {'name': LOC_FIELD, 'value': REF_OBJ_ID},
        ])
        render = _render(managers, [], types_cache={}, ref_render=True)
        render.to_render_objects = [untyped]
        render.types_manager.get_type_instance.return_value = _main_type()
        render.objects_manager.get_objects_lookup.return_value = {REF_OBJ_ID: _ref_obj()}

        render.get_all_linked_objects()

        render.types_manager.get_type_instance.assert_called_once_with(MAIN_TYPE_ID)


# -------------------------------------------------------------------------------------------------------------------- #
#                                        degradation arms and remaining branches                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestLinkedUserCollection:
    """get_all_linked_users gathers the ids it needs and asks for them once."""

    def test_an_object_that_was_never_edited_contributes_no_editor(self, managers) -> None:
        """editor_id is None on most objects, so the common case is the one the branch skips"""
        render = _render(managers, [_obj(MAIN_OBJ_ID, MAIN_TYPE_ID, [], author_id=7)], types_cache={})
        render.users_manager.get_user_lookup.reset_mock()

        render.get_all_linked_users()

        assert render.users_manager.get_user_lookup.call_args.args[0] == [7]

    def test_an_object_without_an_author_contributes_nothing(self, managers) -> None:
        """An object carrying no author_id must not put a None into the lookup"""
        render = _render(managers, [], types_cache={})
        render.to_render_objects = [Mock(author_id=None, editor_id=None)]
        render.users_manager.get_user_lookup.reset_mock()

        assert render.get_all_linked_users() == {}
        render.users_manager.get_user_lookup.assert_not_called()

    def test_a_type_without_an_author_contributes_nothing(self, managers) -> None:
        """A cached type carrying no author_id must not put a None into the lookup"""
        # injected after construction: __init__ walks the cached types, which a bare Mock cannot serve
        render = _render(managers, [], types_cache={})
        render.types_cache[MAIN_TYPE_ID] = Mock(author_id=None)
        render.users_manager.get_user_lookup.reset_mock()

        assert render.get_all_linked_users() == {}
        render.users_manager.get_user_lookup.assert_not_called()


class TestRenderDegradation:
    """
    Every step degrades instead of failing: a piece that cannot be built is dropped and the render
    continues, with only a DEBUG line
    """

    def test_a_failing_reference_expansion_yields_an_empty_reference(self, managers) -> None:
        """_merge_references swallows anything raised while building the expansion"""
        render = _render(managers, [], types_cache={}, objects_cache={})
        render.objects_cache[REF_OBJ_ID] = _ref_obj()
        broken_type = Mock()
        broken_type.get_public_id.side_effect = RuntimeError('type is broken')
        render.types_cache[REF_TYPE_ID] = broken_type

        result = render._merge_references({'value': REF_OBJ_ID, 'summaries': []})

        assert result is not None

    @staticmethod
    def _render_with_summary_line(managers, summary_line: str):
        """A renderer whose referenced type configures the given summary line."""
        ref_type = Mock()
        ref_type.get_public_id.return_value = REF_TYPE_ID
        ref_type.label = 'Ref'
        ref_type.get_icon.return_value = None
        ref_type.has_nested_prefix.return_value = False
        ref_type.get_nested_summary_line.return_value = summary_line
        ref_type.get_nested_summary_fields.return_value = [{'name': NAME_FIELD, 'type': FieldType.TEXT}]
        render = _render(managers, [], types_cache={}, objects_cache={})
        render.objects_cache[REF_OBJ_ID] = _ref_obj()
        render.types_cache[REF_TYPE_ID] = ref_type

        return render

    def test_an_unfillable_summary_line_is_answered_as_no_line(self, managers, caplog) -> None:
        """
        A line whose placeholders do not fit the summary values is answered EMPTY, not raw

        fill_line leaves the template in place, and answering the reference with it makes the
        Angular reference field render a literal '{}' (it shows `line` verbatim when one is set).
        An empty line is its documented fallback: icon + label + #id + the summary
        fields. The mismatch is reported at WARNING, because a summary line that no longer fits its
        type is a configuration problem.
        """
        render = self._render_with_summary_line(managers, 'Name {} in {}')

        with caplog.at_level(logging.WARNING):
            result = render._merge_references({'value': REF_OBJ_ID, 'summaries': [{}]})

        assert result[TypeReferenceKey.LINE.value] == ''
        assert result[TypeReferenceKey.OBJECT_ID.value] == REF_OBJ_ID
        assert str(REF_TYPE_ID) in caplog.text

    def test_an_unfillable_line_keeps_the_summary_fields(self, managers) -> None:
        """
        The summary fields are what the frontend falls back to, so they must survive the failure

        They are dropped for a line that needs no placeholders (the line carries the information
        instead) - but once the line is gone, dropping them too would leave the block with nothing
        but the id.
        """
        render = self._render_with_summary_line(managers, 'Name {} in {}')

        result = render._merge_references({'value': REF_OBJ_ID, 'summaries': [{}]})

        assert result[TypeReferenceKey.SUMMARIES.value]

    def test_a_failing_line_check_still_answers_a_reference(self, managers) -> None:
        """An unexpected error anywhere in the merge answers the reference built so far, never None"""
        render = self._render_with_summary_line(managers, 'Name {}')

        with patch.object(TypeReference, 'line_requires_fields', side_effect=RuntimeError('bad line')):
            result = render._merge_references({'value': REF_OBJ_ID, 'summaries': [{}]})

        assert result is not None

    def test_a_reference_section_whose_type_cannot_be_read_is_dropped(self, managers) -> None:
        """_merge_reference_section returns None rather than a half-built section"""
        refsec_type = _refsec_type()
        render = _render(managers, [], types_cache={REFSEC_TYPE_ID: refsec_type}, objects_cache={})
        broken_ref_type = Mock()
        type(broken_ref_type).public_id = property(lambda _self: (_ for _ in ()).throw(RuntimeError('gone')))
        render.types_cache[REF_TYPE_ID] = broken_ref_type
        section = next(s for s in refsec_type.render_meta.sections if s.name == REFSEC_NAME)

        result = render._merge_reference_section(
            section, _obj(REFSEC_OBJ_ID, REFSEC_TYPE_ID, []), refsec_type, 1,
        )

        assert result is None

    def test_a_ref_section_field_that_cannot_be_read_is_skipped(self, managers) -> None:
        """One unreadable pulled-in field costs its own entry, not the whole reference section"""
        refsec_type = _refsec_type()
        broken_ref_type = Mock()
        broken_ref_type.public_id = REF_TYPE_ID
        broken_ref_type.name = 'ref-type'
        broken_ref_type.label = 'Ref'
        broken_ref_type.get_icon.return_value = None
        broken_ref_type.get_section.return_value = Mock(fields=[NAME_FIELD])
        broken_ref_type.get_field.side_effect = CmdbTypeFieldNotFoundError('gone')

        render = _render(managers, [], types_cache={REFSEC_TYPE_ID: refsec_type}, objects_cache={})
        render.types_cache[REF_TYPE_ID] = broken_ref_type
        render.objects_cache[REF_OBJ_ID] = _ref_obj()
        section = next(s for s in refsec_type.render_meta.sections if s.name == REFSEC_NAME)
        refsec_obj = _obj(REFSEC_OBJ_ID, REFSEC_TYPE_ID, [
            {'type': FieldType.REFERENCE, 'name': REFSEC_REF_FIELD, 'value': REF_OBJ_ID},
        ])

        result = render._merge_reference_section(section, refsec_obj, refsec_type, 1)

        assert result['references']['fields'] == []


class TestUnknownSectionType:
    """A section kind the render does not know is merged as a plain one, and says so."""

    UNKNOWN_KIND: str = 'a-kind-from-a-newer-version'

    def _type_with_an_unknown_section(self) -> CmdbType:
        """A stored type whose only section declares a kind no SectionType member covers."""
        return CmdbType.from_data(make_type_doc(
            MAIN_TYPE_ID, 'main-type',
            fields=[{'type': FieldType.TEXT, 'name': NAME_FIELD, 'label': 'Name'}],
            sections=[{'type': self.UNKNOWN_KIND, 'name': 'main', 'label': 'Main',
                       'fields': [NAME_FIELD]}],
        ))

    def test_a_stored_unknown_kind_still_renders_its_fields(self, managers) -> None:
        """
        The render follows `SECTION_CLASSES`: a kind it does not know is a PLAIN section

        This is the whole reason a type saved by a newer version stays readable - the registry
        answers the unknown kind with a TypeFieldSection, and the render must not then drop what the
        registry kept.
        """
        unknown_type = self._type_with_an_unknown_section()
        render = _render(managers, [], types_cache={MAIN_TYPE_ID: unknown_type})

        fields = render._merge_fields_value(_main_obj(), unknown_type, 1)

        assert _field(fields, NAME_FIELD)[FieldKey.VALUE.value] == MAIN_NAME_VALUE

    def test_a_section_class_the_render_does_not_know_is_merged_as_plain(self, managers, caplog) -> None:
        """A section object outside the three classes is merged as plain and reported."""
        section = SimpleNamespace(type=self.UNKNOWN_KIND, name='main', label='Main',
                                  fields=[NAME_FIELD])
        main_type = _main_type()
        main_type.render_meta.sections = [section]
        render = _render(managers, [], types_cache={MAIN_TYPE_ID: main_type})

        with caplog.at_level(logging.WARNING):
            fields = render._merge_fields_value(_main_obj(), main_type, 1)

        assert _field(fields, NAME_FIELD)[FieldKey.VALUE.value] == MAIN_NAME_VALUE
        assert self.UNKNOWN_KIND in caplog.text

    def test_a_section_without_a_fields_list_is_skipped_with_a_log(self, managers, caplog) -> None:
        """
        Nothing to merge is still reported

        An `elif` chain ending with no branch would leave such a section contributing no fields with
        no log and no marker; the section itself still appears in the render result's `sections`
        block,
        which is what made it look like a rendering glitch rather than a missing kind.
        """
        main_type = _main_type()
        main_type.render_meta.sections = [TypeSection(type=self.UNKNOWN_KIND, name='main', label='Main')]
        render = _render(managers, [], types_cache={MAIN_TYPE_ID: main_type})

        with caplog.at_level(logging.WARNING):
            fields = render._merge_fields_value(_main_obj(), main_type, 1)

        assert fields == []
        assert self.UNKNOWN_KIND in caplog.text


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 render problems                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
# A field every type below declares with a proposal, so a fallback answering the type's own value shows
TYPE_DEFAULT_VALUE: str = 'the-type-proposal'
# A stored field the object's type has since dropped
DROPPED_FIELD: str = 'dropped-from-the-type'
SECOND_EXT_HREF: str = 'http://y/{}'
PLAIN_OBJ_ID: int = 713


def _render_one(render: CmdbMultiRender) -> RenderResult:
    """Renders the single object of `render` and answers its RenderResult."""
    results: list[RenderResult] = render.result()

    assert len(results) == 1

    return results[0]


def _problem(
    code: RenderProblemCode,
    section: str | None = None,
    field: str | None = None,
    external_link: str | None = None,
) -> dict[str, Any]:
    """One render-problem entry as a RenderResult carries it."""
    return {
        RenderProblemKey.CODE.value: code.value,
        RenderProblemKey.SECTION.value: section,
        RenderProblemKey.FIELD.value: field,
        RenderProblemKey.EXTERNAL_LINK.value: external_link,
    }


def _codes(problems: list[dict[str, Any]]) -> list[str]:
    """The codes of a list of render-problem entries."""
    return [problem[RenderProblemKey.CODE.value] for problem in problems]


def _ghost_type() -> CmdbType:
    """A main-shaped type whose section lists a field the type does not declare."""
    return CmdbType.from_data(make_type_doc(
        MAIN_TYPE_ID, 'ghost-type',
        fields=[{'type': FieldType.TEXT, 'name': NAME_FIELD, 'label': 'Name'}],
        sections=[{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [NAME_FIELD, GHOST_FIELD]}],
    ))


def _defaulted_type() -> CmdbType:
    """A type with one text field carrying a proposal of its own."""
    return CmdbType.from_data(make_type_doc(
        MAIN_TYPE_ID, 'defaulted-type',
        fields=[{'type': FieldType.TEXT, 'name': NAME_FIELD, 'label': 'Name', 'value': TYPE_DEFAULT_VALUE}],
        sections=[{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [NAME_FIELD]}],
    ))


def _undefaulted_type() -> CmdbType:
    """A type with one text field and no proposal of its own."""
    return CmdbType.from_data(make_type_doc(
        MAIN_TYPE_ID, 'undefaulted-type',
        fields=[{'type': FieldType.TEXT, 'name': NAME_FIELD, 'label': 'Name'}],
        sections=[{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [NAME_FIELD]}],
    ))


def _only_name_obj(public_id: int = MAIN_OBJ_ID) -> CmdbObject:
    """A main-type object that carries its name and nothing else."""
    return _obj(public_id, MAIN_TYPE_ID, [{'type': FieldType.TEXT, 'name': NAME_FIELD, 'value': MAIN_NAME_VALUE}])


class TestACompleteRender:
    """A render that lost nothing says so."""

    def test_a_complete_render_carries_no_problems(self, managers) -> None:
        """Every reference resolves, every field merges: the list is empty"""
        render = _render(managers, [_main_obj()], ref_render=True, objects_cache={REF_OBJ_ID: _ref_obj()},
                         types_cache={MAIN_TYPE_ID: _main_type(), REF_TYPE_ID: _ref_type()})

        assert _render_one(render).render_problems == []

    def test_the_problems_are_part_of_the_serialised_result(self, managers) -> None:
        """The attribute is on the wire, next to the rest of the render"""
        render = _render(managers, [_only_name_obj()], types_cache={MAIN_TYPE_ID: _ghost_type()})

        serialised: dict[str, Any] = _render_one(render).to_json()

        assert serialised['render_problems'] == [_problem(RenderProblemCode.FIELD_NOT_ON_TYPE, 'main', GHOST_FIELD)]

    def test_a_field_the_object_does_not_carry_is_no_problem(self, managers) -> None:
        """
        A reference or location field the object never stored is answered null, and that is complete

        It is what every object saved before its type gained the field looks like, so reporting it
        would flag every such object as degraded
        """
        render = _render(managers, [_only_name_obj()], ref_render=True,
                         types_cache={MAIN_TYPE_ID: _main_type(), REF_TYPE_ID: _ref_type()})

        result = _render_one(render)

        assert _field(result.fields, REF_FIELD)['value'] is None
        assert _field(result.fields, LOC_FIELD)['value'] is None
        assert result.render_problems == []


class TestAFieldTheTypeDoesNotDeclare:
    """A section naming an undeclared field: the entry is left out, and the render says so."""

    def test_it_is_reported_on_the_result(self, managers) -> None:
        """The loss names its section and its field"""
        render = _render(managers, [_only_name_obj()], types_cache={MAIN_TYPE_ID: _ghost_type()})

        result = _render_one(render)

        assert [field['name'] for field in result.fields] == [NAME_FIELD]
        assert result.render_problems == [_problem(RenderProblemCode.FIELD_NOT_ON_TYPE, 'main', GHOST_FIELD)]

    def test_every_object_is_flagged_but_the_problem_is_logged_once(self, managers, caplog) -> None:
        """One broken definition walked by two objects: two flags, one log line"""
        render = _render(managers, [_only_name_obj(), _only_name_obj(PLAIN_OBJ_ID)],
                         types_cache={MAIN_TYPE_ID: _ghost_type()})

        with caplog.at_level(logging.WARNING):
            results = render.result()

        assert all(_codes(result.render_problems) == [RenderProblemCode.FIELD_NOT_ON_TYPE] for result in results)
        assert caplog.text.count(GHOST_FIELD) == 1


class TestAFieldThatFailsToMerge:
    """The merge of one field fails: its stored value is answered, and the cache is left alone."""

    def test_the_stored_value_is_answered(self, managers, monkeypatch) -> None:
        """A null would claim the object holds nothing there - it holds the stored value"""
        render = _render(managers, [_only_name_obj()], types_cache={MAIN_TYPE_ID: _defaulted_type()})
        monkeypatch.setattr(render, '_merge_field_content_section',
                            Mock(side_effect=RuntimeError('merge failed')))

        result = _render_one(render)

        assert _field(result.fields, NAME_FIELD)['value'] == MAIN_NAME_VALUE
        assert result.render_problems == [_problem(RenderProblemCode.FIELD_MERGE_FAILED, 'main', NAME_FIELD)]

    def test_the_answered_entry_is_a_full_triple(self, managers, monkeypatch) -> None:
        """The fallback carries the definition's name and type, not just a value"""
        render = _render(managers, [_only_name_obj()], types_cache={MAIN_TYPE_ID: _defaulted_type()})
        monkeypatch.setattr(render, '_merge_field_content_section',
                            Mock(side_effect=RuntimeError('merge failed')))

        entry: dict[str, Any] = _render_one(render).fields[0]

        assert (entry['name'], entry['type']) == (NAME_FIELD, FieldType.TEXT)

    @pytest.mark.parametrize('build_type', [_defaulted_type, _undefaulted_type], ids=['with-proposal', 'without'])
    def test_a_malformed_stored_row_leaves_the_cached_type_untouched(self, managers, build_type) -> None:
        """
        The fallback is built from a copy: the definition is the cached type's live dict

        A stored row without a name makes the merge raise before it has copied anything. Writing the
        fallback value into the definition itself would change that field - its proposal included -
        for every later object of the render. A field WITHOUT a proposal is the case that shows it: the
        fallback adds a `value` key the definition never had
        """
        cached_type: CmdbType = build_type()
        definition_before: dict[str, Any] = dict(cached_type.get_field(NAME_FIELD))
        malformed = _obj(MAIN_OBJ_ID, MAIN_TYPE_ID, [{'type': FieldType.TEXT, 'value': MAIN_NAME_VALUE}])
        render = _render(managers, [malformed], types_cache={MAIN_TYPE_ID: cached_type})

        result = _render_one(render)

        assert cached_type.get_field(NAME_FIELD) == definition_before
        assert _codes(result.render_problems) == [RenderProblemCode.FIELD_MERGE_FAILED]

    def test_a_field_the_object_does_not_carry_answers_the_types_proposal(self, managers, monkeypatch) -> None:
        """No stored value to answer: the fallback keeps what the type proposes"""
        render = _render(managers, [_obj(MAIN_OBJ_ID, MAIN_TYPE_ID, [])], types_cache={MAIN_TYPE_ID: _defaulted_type()})
        monkeypatch.setattr(render, '_merge_field_content_section',
                            Mock(side_effect=RuntimeError('merge failed')))

        assert _render_one(render).fields[0]['value'] == TYPE_DEFAULT_VALUE

    def test_it_is_logged_at_warning(self, managers, monkeypatch, caplog) -> None:
        """The operator sees which field of which object"""
        render = _render(managers, [_only_name_obj()], types_cache={MAIN_TYPE_ID: _defaulted_type()})
        monkeypatch.setattr(render, '_merge_field_content_section',
                            Mock(side_effect=RuntimeError('merge failed')))

        with caplog.at_level(logging.WARNING):
            render.result()

        assert NAME_FIELD in caplog.text
        assert str(MAIN_OBJ_ID) in caplog.text


class TestAStoredFieldItsTypeDropped:
    """A legacy untyped row naming a field the type no longer declares."""

    @staticmethod
    def _dropped_obj() -> CmdbObject:
        """An object whose untyped row names a dropped field, next to a live reference."""
        return _obj(MAIN_OBJ_ID, MAIN_TYPE_ID, [
            {'name': DROPPED_FIELD, 'value': REF_OBJ_ID},
            {'type': FieldType.REFERENCE, 'name': REF_FIELD, 'value': REF_OBJ_ID},
        ])

    def test_the_render_is_built(self, managers) -> None:
        """The reference collection skips the row instead of failing the constructor"""
        managers.types.get_type_instance.return_value = _main_type()
        managers.objects.get_objects_lookup.return_value = {REF_OBJ_ID: _ref_obj()}

        render = _render(managers, [self._dropped_obj()], ref_render=True, types_cache={MAIN_TYPE_ID: _main_type()})

        assert REF_OBJ_ID in render.objects_cache

    def test_it_is_logged_but_not_flagged(self, managers, caplog) -> None:
        """The dropped value was never going to be drawn, so the render lost nothing"""
        managers.types.get_type_instance.return_value = _main_type()

        with caplog.at_level(logging.WARNING):
            render = _render(managers, [self._dropped_obj()], ref_render=True,
                             types_cache={MAIN_TYPE_ID: _main_type()})

        assert DROPPED_FIELD in caplog.text
        assert _render_one(render).render_problems == []


class TestReferencesThatCannotBeLoaded:
    """The bulk load of the referenced objects fails."""

    def test_only_the_objects_that_reference_something_are_flagged(self, managers) -> None:
        """An object with no reference lost nothing to the failed load"""
        managers.objects.get_objects_lookup.side_effect = RuntimeError('database gone')
        render = _render(managers, [_main_obj(), _only_name_obj(PLAIN_OBJ_ID)], ref_render=True,
                         types_cache={MAIN_TYPE_ID: _main_type(), REF_TYPE_ID: _ref_type()})

        referencing, plain = render.result()

        assert RenderProblemCode.REFERENCES_UNAVAILABLE.value in _codes(referencing.render_problems)
        assert plain.render_problems == []

    def test_it_is_logged_once_at_error(self, managers, caplog) -> None:
        """An infrastructure failure, logged with its traceback"""
        managers.objects.get_objects_lookup.side_effect = RuntimeError('database gone')

        with caplog.at_level(logging.WARNING):
            _render(managers, [_main_obj()], ref_render=True, types_cache={MAIN_TYPE_ID: _main_type()})

        errors = [record for record in caplog.records if record.levelno == logging.ERROR]
        assert len(errors) == 1
        assert errors[0].exc_info


class TestSectionsThatCannotBeSerialised:
    """The type's sections fail to serialise."""

    def test_the_object_is_flagged(self, managers, monkeypatch) -> None:
        """An object with no sections at all is the most visible loss there is"""
        main_type = _main_type()
        render = _render(managers, [_only_name_obj()], types_cache={MAIN_TYPE_ID: main_type})
        # each section class serialises itself, so the failure is planted on the class the type uses
        monkeypatch.setattr(type(main_type.render_meta.sections[0]), 'to_json', Mock(side_effect=RuntimeError('boom')))

        result = _render_one(render)

        assert result.sections == []
        assert _codes(result.render_problems) == [RenderProblemCode.SECTIONS_UNREADABLE]


class TestExternalLinks:
    """An external link that fails, and two links sharing a name."""

    def test_a_link_that_fails_to_fill_is_flagged_by_name(self, managers, monkeypatch) -> None:
        """The entry names the link: it is the only thing telling two failed links apart"""
        render = _render(managers, [_main_obj()], types_cache={MAIN_TYPE_ID: _main_type()})
        monkeypatch.setattr(TypeExternalLink, 'filled_href', Mock(side_effect=RuntimeError('bad href')))

        result = _render_one(render)

        assert result.externals == []
        assert _problem(RenderProblemCode.EXTERNAL_LINK_FAILED, external_link=EXT_NAME) in result.render_problems

    def test_a_link_whose_field_the_object_does_not_carry_is_skipped_quietly(self, managers) -> None:
        """
        A field the object never stored is a missing value, the by-design skip - not a failed link

        Reading it with a lookup that raises for an absent field turned every object saved before its
        type gained the link's field into a reported problem
        """
        render = _render(managers, [_obj(MAIN_OBJ_ID, MAIN_TYPE_ID, [])], types_cache={MAIN_TYPE_ID: _main_type()})

        result = _render_one(render)

        assert result.externals == []
        assert result.render_problems == []

    def test_two_links_sharing_a_name_each_render_their_own_href(self, managers) -> None:
        """
        The links are walked as they are

        Looking each one up again by its name answered the FIRST link carrying it, so the second link
        rendered as a copy of the first
        """
        main_type = _main_type()
        main_type.render_meta.externals.append(TypeExternalLink.from_data(
            {'name': EXT_NAME, 'href': SECOND_EXT_HREF, 'label': 'Ext 2', 'fields': [NAME_FIELD]}
        ))
        render = _render(managers, [_main_obj()], types_cache={MAIN_TYPE_ID: main_type})

        hrefs = [link['href'] for link in _render_one(render).externals]

        assert hrefs == [f'http://x/{MAIN_NAME_VALUE}', f'http://y/{MAIN_NAME_VALUE}']


class TestReferencesThatCannotBeBuilt:
    """A reference expansion or its line fails."""

    def test_an_unbuildable_reference_is_flagged_on_its_field(self, managers) -> None:
        """The field whose reference lost its line and summaries is named"""
        render = _render(managers, [_main_obj()], ref_render=True, objects_cache={REF_OBJ_ID: _ref_obj()},
                         types_cache={MAIN_TYPE_ID: _main_type(), REF_TYPE_ID: _ref_type()})
        broken_type = Mock()
        broken_type.get_public_id.side_effect = RuntimeError('type is broken')
        render.types_cache[REF_TYPE_ID] = broken_type

        result = _render_one(render)

        assert _problem(RenderProblemCode.REFERENCE_INCOMPLETE, field=REF_FIELD) in result.render_problems

    def test_an_unfillable_line_is_flagged(self, managers) -> None:
        """The reference is answered without its line, and the object says so"""
        render = TestRenderDegradation._render_with_summary_line(managers, 'Name {} in {}')

        with render.problems.rendering(MAIN_OBJ_ID):
            render._merge_references({'name': REF_FIELD, 'value': REF_OBJ_ID, 'summaries': [{}]})

        assert render.problems.problems_for(MAIN_OBJ_ID) == [
            _problem(RenderProblemCode.REFERENCE_LINE_UNFILLED, field=REF_FIELD)
        ]

    def test_a_reference_answered_on_its_own_is_only_logged(self, managers, caplog) -> None:
        """The MDS lookup renders no object, so there is nothing to flag - the log still says it"""
        render = _render(managers, [], objects_cache={REF_OBJ_ID: _ref_obj()}, types_cache={})
        broken_type = Mock()
        broken_type.get_public_id.side_effect = RuntimeError('type is broken')
        render.types_cache[REF_TYPE_ID] = broken_type

        with caplog.at_level(logging.WARNING):
            render.get_mds_reference(REF_OBJ_ID)

        assert not render.problems.problems_by_object
        assert str(REF_OBJ_ID) in caplog.text


class TestReferenceSectionProblems:
    """Every way a reference section can come up short is flagged on the object."""

    @staticmethod
    def _section(ref_type: CmdbType):
        """The reference section of a refsec type."""
        return next(section for section in ref_type.render_meta.sections if section.name == REFSEC_NAME)

    def _merge(self, render, refsec_type: CmdbType, refsec_obj: CmdbObject | None = None) -> list[dict[str, Any]]:
        """Merges the refsec type's reference section while rendering the refsec object; answers its problems."""
        refsec_obj = refsec_obj or _obj(REFSEC_OBJ_ID, REFSEC_TYPE_ID, [])

        with render.problems.rendering(REFSEC_OBJ_ID):
            render._merge_reference_section(self._section(refsec_type), refsec_obj, refsec_type, 1)

        return render.problems.problems_for(REFSEC_OBJ_ID)

    def test_a_missing_referenced_type(self, managers) -> None:
        """The target type is gone"""
        refsec_type = _refsec_type()
        render = _render(managers, [], types_cache={REFSEC_TYPE_ID: refsec_type})

        assert self._merge(render, refsec_type) == [
            _problem(RenderProblemCode.REFERENCE_SECTION_UNRESOLVED, REFSEC_NAME)
        ]

    def test_a_section_without_its_reference_field(self, managers) -> None:
        """The type declares the section but not the '<section>-field' it reads the reference from"""
        orphan_type = CmdbType.from_data(make_type_doc(
            REFSEC_TYPE_ID, 'orphan-type',
            fields=[{'type': FieldType.TEXT, 'name': NAME_FIELD, 'label': 'Name'}],
            sections=[
                {'type': 'ref-section', 'name': REFSEC_NAME, 'label': 'Orphan',
                 'reference': {'type_id': REF_TYPE_ID, 'section_name': 'main', 'selected_fields': []},
                 'fields': []},
            ],
        ))
        render = _render(managers, [], types_cache={REFSEC_TYPE_ID: orphan_type, REF_TYPE_ID: _ref_type()})

        assert _codes(self._merge(render, orphan_type)) == [RenderProblemCode.REFERENCE_SECTION_UNRESOLVED]

    def test_a_referenced_type_that_cannot_be_read(self, managers) -> None:
        """Reading the target type raises"""
        refsec_type = _refsec_type()
        render = _render(managers, [], types_cache={REFSEC_TYPE_ID: refsec_type})
        broken_ref_type = Mock()
        type(broken_ref_type).public_id = property(lambda _self: (_ for _ in ()).throw(RuntimeError('gone')))
        render.types_cache[REF_TYPE_ID] = broken_ref_type

        assert _codes(self._merge(render, refsec_type)) == [RenderProblemCode.REFERENCE_SECTION_UNRESOLVED]

    def test_a_pulled_in_field_that_cannot_be_read(self, managers) -> None:
        """The section renders short by one field, and names it"""
        refsec_type = _refsec_type()
        broken_ref_type = Mock()
        broken_ref_type.public_id = REF_TYPE_ID
        broken_ref_type.name = 'ref-type'
        broken_ref_type.label = 'Ref'
        broken_ref_type.get_icon.return_value = None
        broken_ref_type.get_section.return_value = Mock(fields=[NAME_FIELD])
        broken_ref_type.get_field.side_effect = CmdbTypeFieldNotFoundError('gone')
        render = _render(managers, [], types_cache={REFSEC_TYPE_ID: refsec_type}, objects_cache={})
        render.types_cache[REF_TYPE_ID] = broken_ref_type

        assert self._merge(render, refsec_type) == [
            _problem(RenderProblemCode.REFERENCE_SECTION_FIELD_SKIPPED, REFSEC_NAME, NAME_FIELD)
        ]

    def test_a_resolving_section_is_no_problem(self, managers) -> None:
        """The control case"""
        refsec_type = _refsec_type()
        render = _render(managers, [], types_cache={REFSEC_TYPE_ID: refsec_type, REF_TYPE_ID: _ref_type()})

        assert self._merge(render, refsec_type) == []


# -------------------------------------------------------------------------------------------------------------------- #
#                                         The READ ACL over referenced objects                                         #
# -------------------------------------------------------------------------------------------------------------------- #
DEFAULT_NAME_VALUE: str = 'proposed-by-the-type'


def _refsec_field(value: Any) -> dict[str, Any]:
    """A nested ref-section field pointing at `value`."""
    return {'name': REFSEC_REF_FIELD, 'type': FieldType.REF_SECTION, 'value': value}


def _ref_obj_doc() -> dict[str, Any]:
    """The stored document of the referenced object, as get_object answers it."""
    return CmdbObject.to_json(_ref_obj())


class TestTheReadScopeOfARender:
    """Which scope a render reads its references through."""

    def test_a_render_of_its_own_scopes_its_user(self, managers) -> None:
        """The scope is the render user's"""
        render = _render(managers, [])

        assert render.read_scope.user is render.render_user

    def test_the_prefetch_leaves_out_the_denied_types(self, managers) -> None:
        """The bulk load of the referenced objects is narrowed by the user's denied types"""
        managers.denied_type_ids = [REF_TYPE_ID]
        render = _render(managers, [], types_cache={MAIN_TYPE_ID: _main_type()}, ref_render=True)
        render.to_render_objects = [_main_obj()]

        render.get_all_linked_objects()

        render.objects_manager.get_objects_lookup.assert_called_once_with([REF_OBJ_ID], [REF_TYPE_ID])

class TestTheMdsReferenceOfARenderedObject:
    """get_mds_reference asked for the object the render was built for."""

    def test_it_answers_the_objects_own_reference(self, managers) -> None:
        """A render caches what its objects reference, never the objects - they resolve all the same"""
        render = _render(managers, [_ref_obj()], types_cache={REF_TYPE_ID: _ref_type()})

        reference = render.get_mds_reference(REF_OBJ_ID)

        assert reference[TypeReferenceKey.OBJECT_ID.value] == REF_OBJ_ID
        assert reference[TypeReferenceKey.TYPE_ID.value] == REF_TYPE_ID
        assert [summary['value'] for summary in reference[TypeReferenceKey.SUMMARIES.value]] == [REF_NAME_VALUE]

    def test_an_id_the_render_does_not_hold_is_the_empty_reference(self, managers) -> None:
        """Neither rendered nor cached - the empty reference, never None"""
        render = _render(managers, [_ref_obj()], types_cache={REF_TYPE_ID: _ref_type()})

        assert render.get_mds_reference(REF_OBJ_ID + 1) == TypeReference.to_json(TypeReference.empty())


class TestAnUnsetReferenceSectionsValues:
    """A reference section with nothing to merge answers no values."""

    def _ref_type_with_default(self) -> CmdbType:
        """The referenced type, its name field proposing a default."""
        return CmdbType.from_data(make_type_doc(
            REF_TYPE_ID, 'ref-type',
            fields=[{'type': FieldType.TEXT, 'name': NAME_FIELD, 'label': 'Name', 'value': DEFAULT_NAME_VALUE}],
            sections=[{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [NAME_FIELD]}],
        ))

    def _merge_unset(self, managers, ref_type: CmdbType) -> dict[str, Any]:
        """Merges the refsec section of an object referencing nothing; answers the pulled-in name field."""
        refsec_type = _refsec_type()
        render = _render(managers, [], ref_render=True,
                         types_cache={REFSEC_TYPE_ID: refsec_type, REF_TYPE_ID: ref_type})
        unset = _obj(REFSEC_OBJ_ID, REFSEC_TYPE_ID, [{'type': FieldType.TEXT, 'name': NAME_FIELD, 'value': 'Owner'}])

        ref_field = render._merge_reference_section(refsec_type.render_meta.sections[1], unset, refsec_type, 3)

        return ref_field[RenderedFieldKey.REFERENCES][RenderedReferenceSectionKey.FIELDS][0]

    def test_the_type_default_is_no_value(self, managers) -> None:
        """The proposal is not shown as a value the section holds"""
        assert self._merge_unset(managers, self._ref_type_with_default())[FieldKey.VALUE] is None

    def test_the_type_default_is_parked(self, managers) -> None:
        """It sits under `default`, where a merge puts a proposal the object's value replaced"""
        field = self._merge_unset(managers, self._ref_type_with_default())

        assert field[RenderedFieldKey.DEFAULT] == DEFAULT_NAME_VALUE

    def test_no_default_parks_nothing(self, managers) -> None:
        """A field without a proposal answers None and no `default`"""
        field = self._merge_unset(managers, _ref_type())

        assert field[FieldKey.VALUE] is None
        assert RenderedFieldKey.DEFAULT.value not in field

    def test_the_cached_type_keeps_its_default(self, managers) -> None:
        """The pulled-in field is a copy - the cached definition still proposes its value"""
        ref_type = self._ref_type_with_default()

        self._merge_unset(managers, ref_type)

        assert ref_type.get_field(NAME_FIELD)[FieldKey.VALUE] == DEFAULT_NAME_VALUE


# -------------------------------------------------------------------------------------------------------------------- #
#                                     A reference section chain (A -> B's rb -> C)                                     #
# -------------------------------------------------------------------------------------------------------------------- #
CHAIN_A_TYPE_ID: int = 740
CHAIN_B_TYPE_ID: int = 741
CHAIN_C_TYPE_ID: int = 742
CHAIN_A_ID: int = 750
CHAIN_B_ID: int = 751
CHAIN_C_ID: int = 752
CHAIN_B2_ID: int = 753
CHAIN_A_SECTION: str = 'ra'
CHAIN_B_SECTION: str = 'rb'
CHAIN_B_VALUE: str = 'b-value'
CHAIN_C_VALUE: str = 'c-value'


def _chain_ref_section(name: str, type_id: int, section_name: str) -> dict[str, Any]:
    """A reference section as the type builder writes it: its own fields list names its '<name>-field'."""
    return {'type': 'ref-section', 'name': name, 'label': name, 'fields': [f'{name}-field'],
            'reference': {'type_id': type_id, 'section_name': section_name, 'selected_fields': []}}


def _chain_type(type_id: int, ref_section: dict[str, Any] | None = None) -> CmdbType:
    """A type with a name field in 'main', and optionally one reference section with its field."""
    fields: list[dict[str, Any]] = [{'type': FieldType.TEXT, 'name': NAME_FIELD, 'label': 'Name'}]
    sections: list[dict[str, Any]] = [
        {'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [NAME_FIELD]},
    ]

    if ref_section is not None:
        fields.append({'type': FieldType.REF_SECTION, 'name': f"{ref_section['name']}-field",
                       'label': ref_section['name']})
        sections.append(ref_section)

    return CmdbType.from_data(make_type_doc(type_id, f'chain-{type_id}', fields=fields, sections=sections))


def _chain_types(b_points_at: int = CHAIN_C_TYPE_ID, b_section: str = 'main') -> dict[int, CmdbType]:
    """A's 'ra' pulls B's reference section 'rb', which pulls `b_points_at`'s `b_section`."""
    return {
        CHAIN_A_TYPE_ID: _chain_type(CHAIN_A_TYPE_ID, _chain_ref_section(CHAIN_A_SECTION, CHAIN_B_TYPE_ID,
                                                                         CHAIN_B_SECTION)),
        CHAIN_B_TYPE_ID: _chain_type(CHAIN_B_TYPE_ID, _chain_ref_section(CHAIN_B_SECTION, b_points_at, b_section)),
        CHAIN_C_TYPE_ID: _chain_type(CHAIN_C_TYPE_ID),
    }


def _chain_obj(public_id: int, type_id: int, value: str, section: str | None = None,
               target: Any = None) -> CmdbObject:
    """An object named `value`, whose `section` field (if any) points at `target`."""
    fields: list[dict[str, Any]] = [{'type': FieldType.TEXT, 'name': NAME_FIELD, 'value': value}]

    if section is not None:
        fields.append({'type': FieldType.REF_SECTION, 'name': f'{section}-field', 'value': target})

    return _obj(public_id, type_id, fields)


def _chain_a() -> CmdbObject:
    """The A object, whose 'ra' points at the B object."""
    return _chain_obj(CHAIN_A_ID, CHAIN_A_TYPE_ID, 'a-value', CHAIN_A_SECTION, CHAIN_B_ID)


def _chain_cache(c_cached: bool = True, b_target: Any = CHAIN_C_ID) -> dict[int, CmdbObject]:
    """The prefetched chain: the B object (pointing at `b_target`) and, unless hidden or gone, the C object."""
    cache: dict[int, CmdbObject] = {
        CHAIN_B_ID: _chain_obj(CHAIN_B_ID, CHAIN_B_TYPE_ID, CHAIN_B_VALUE, CHAIN_B_SECTION, b_target),
    }

    if c_cached:
        cache[CHAIN_C_ID] = _chain_obj(CHAIN_C_ID, CHAIN_C_TYPE_ID, CHAIN_C_VALUE)

    return cache


def _merge_chain(render: CmdbMultiRender, level: int = DEFAULT_RENDER_LEVEL - 1) -> dict[str, Any]:
    """Merges A's 'ra' section of the A object; answers B's pulled-in 'rb-field'."""
    a_type: CmdbType = render.types_cache[CHAIN_A_TYPE_ID]
    ra_section = next(section for section in a_type.render_meta.sections if section.name == CHAIN_A_SECTION)

    with render.problems.rendering(CHAIN_A_ID):
        ra_field = render._merge_reference_section(ra_section, _chain_a(), a_type, level)

    pulled: list[dict[str, Any]] = ra_field[RenderedFieldKey.REFERENCES][RenderedReferenceSectionKey.FIELDS]

    return next(field for field in pulled if field[FieldKey.NAME] == f'{CHAIN_B_SECTION}-field')


class TestAReferenceSectionChain:
    """A pulled-in reference-section field is resolved with the section of the type that declares it."""

    def test_the_chain_answers_the_far_objects_values(self, managers) -> None:
        """A's section shows B's 'rb' section - and that shows C's values, under C's type"""
        render = _render(managers, [], ref_render=True, objects_cache=_chain_cache(), types_cache=_chain_types())

        rb_field = _merge_chain(render)

        block: dict[str, Any] = rb_field[RenderedFieldKey.REFERENCES]
        assert rb_field[FieldKey.VALUE] == CHAIN_C_ID
        assert block[RenderedReferenceSectionKey.TYPE_ID.value] == CHAIN_C_TYPE_ID
        assert [field[FieldKey.VALUE] for field in block[RenderedReferenceSectionKey.FIELDS]] == [CHAIN_C_VALUE]

    def test_the_block_has_the_shape_the_frontend_draws(self, managers) -> None:
        """The same five keys as any reference section's block - type id, name, label, icon, fields"""
        render = _render(managers, [], ref_render=True, objects_cache=_chain_cache(), types_cache=_chain_types())

        block: dict[str, Any] = _merge_chain(render)[RenderedFieldKey.REFERENCES]

        assert set(block) == {key.value for key in RenderedReferenceSectionKey}

    def test_the_block_is_resolved_from_the_declaring_type(self, managers) -> None:
        """B declares 'rb'; the C object's own type declares no such section and is not consulted for it"""
        render = _render(managers, [], ref_render=True, objects_cache=_chain_cache(), types_cache=_chain_types())

        assert _merge_chain(render)[RenderedFieldKey.REFERENCES][RenderedReferenceSectionKey.TYPE_NAME.value] \
            == f'chain-{CHAIN_C_TYPE_ID}'

    def test_the_section_is_the_one_the_field_belongs_to(self, managers) -> None:
        """B declares a second reference section ahead of 'rb'; 'rb-field' is still resolved with 'rb'"""
        types: dict[int, CmdbType] = _chain_types()
        b_type: CmdbType = types[CHAIN_B_TYPE_ID]
        decoy: CmdbType = _chain_type(CHAIN_B_TYPE_ID, _chain_ref_section('decoy', CHAIN_A_TYPE_ID, 'main'))
        b_type.render_meta.sections.insert(0, decoy.render_meta.sections[-1])
        render = _render(managers, [], ref_render=True, objects_cache=_chain_cache(), types_cache=types)

        block: dict[str, Any] = _merge_chain(render)[RenderedFieldKey.REFERENCES]

        assert block[RenderedReferenceSectionKey.TYPE_ID.value] == CHAIN_C_TYPE_ID

    def test_at_the_depth_limit_the_field_has_no_block(self, managers) -> None:
        """The hop that would reach level 0 answers the field as merged - its stored id, no block"""
        render = _render(managers, [], ref_render=True, objects_cache=_chain_cache(), types_cache=_chain_types())

        rb_field = _merge_chain(render, level=1)

        assert rb_field[FieldKey.VALUE] == CHAIN_C_ID
        assert RenderedFieldKey.REFERENCES.value not in rb_field

    def test_a_far_object_not_cached_renders_like_an_unset_one(self, managers) -> None:
        """Unreadable or gone: the block keeps C's fields, answers no value, and reports nothing"""
        render = _render(managers, [], ref_render=True, objects_cache=_chain_cache(c_cached=False),
                         types_cache=_chain_types())

        rb_field = _merge_chain(render)

        block: dict[str, Any] = rb_field[RenderedFieldKey.REFERENCES]
        assert [field[FieldKey.VALUE] for field in block[RenderedReferenceSectionKey.FIELDS]] == [None]
        assert render.problems.problems_for(CHAIN_A_ID) == []

    @pytest.mark.parametrize('unset_value', [None, '', 0], ids=['none', 'empty-string', 'zero'])
    def test_an_unset_nested_reference_is_no_problem(self, managers, unset_value: Any) -> None:
        """Nothing referenced yet: the block answers no values, and nothing is queried or reported"""
        render = _render(managers, [], ref_render=True, objects_cache=_chain_cache(b_target=unset_value),
                         types_cache=_chain_types())

        rb_field = _merge_chain(render)

        assert [field[FieldKey.VALUE] for field in rb_field[RenderedFieldKey.REFERENCES]
                [RenderedReferenceSectionKey.FIELDS]] == [None]
        assert render.problems.problems_for(CHAIN_A_ID) == []
        render.objects_manager.get_object.assert_not_called()

    def test_a_field_without_its_section_is_answered_as_merged(self, managers) -> None:
        """B stores 'rb-field' but declares no 'rb' section any more: the value, no block, no problem"""
        types: dict[int, CmdbType] = _chain_types()
        b_type: CmdbType = types[CHAIN_B_TYPE_ID]
        b_type.render_meta.sections = [section for section in b_type.render_meta.sections
                                       if section.name != CHAIN_B_SECTION]
        b_type.render_meta.sections.append(TypeFieldSection.from_data(
            {'type': 'section', 'name': CHAIN_B_SECTION, 'label': 'Plain', 'fields': [f'{CHAIN_B_SECTION}-field']}))
        render = _render(managers, [], ref_render=True, objects_cache=_chain_cache(), types_cache=types)

        rb_field = _merge_chain(render)

        assert rb_field[FieldKey.VALUE] == CHAIN_C_ID
        assert RenderedFieldKey.REFERENCES.value not in rb_field
        assert render.problems.problems_for(CHAIN_A_ID) == []

    def test_a_cycle_ends_at_the_depth(self, managers) -> None:
        """B's 'rb' pulls B's own 'rb': the two B objects point at each other, and the merge still ends"""
        cache: dict[int, CmdbObject] = {
            CHAIN_B_ID: _chain_obj(CHAIN_B_ID, CHAIN_B_TYPE_ID, CHAIN_B_VALUE, CHAIN_B_SECTION, CHAIN_B2_ID),
            CHAIN_B2_ID: _chain_obj(CHAIN_B2_ID, CHAIN_B_TYPE_ID, 'b2-value', CHAIN_B_SECTION, CHAIN_B_ID),
        }
        render = _render(managers, [], ref_render=True, objects_cache=cache,
                         types_cache=_chain_types(b_points_at=CHAIN_B_TYPE_ID, b_section=CHAIN_B_SECTION))

        rb_field = _merge_chain(render)

        inner: dict[str, Any] = rb_field[RenderedFieldKey.REFERENCES][RenderedReferenceSectionKey.FIELDS][0]
        assert inner[FieldKey.VALUE] == CHAIN_B_ID
        assert RenderedFieldKey.REFERENCES.value not in inner

    def test_the_chain_is_merged_without_a_render_or_a_read(self, managers) -> None:
        """No nested CmdbMultiRender is built and no object is read: the prefetch loaded the chain"""
        render = _render(managers, [], ref_render=True, objects_cache=_chain_cache(), types_cache=_chain_types())

        with patch.object(mr_module, 'CmdbMultiRender', wraps=CmdbMultiRender) as nested_ctor:
            _merge_chain(render)

        nested_ctor.assert_not_called()
        render.objects_manager.get_object.assert_not_called()

    def test_a_whole_render_carries_the_chain(self, managers) -> None:
        """Through result(): A's rendered 'ra' field carries C's value two blocks down"""
        render = _render(managers, [_chain_a()], ref_render=True, objects_cache=_chain_cache(),
                         types_cache=_chain_types())

        result = _render_one(render)

        ra_field = _field(result.fields, f'{CHAIN_A_SECTION}-field')
        rb_field = ra_field[RenderedFieldKey.REFERENCES][RenderedReferenceSectionKey.FIELDS][0]
        assert rb_field[RenderedFieldKey.REFERENCES][RenderedReferenceSectionKey.FIELDS][0][FieldKey.VALUE] \
            == CHAIN_C_VALUE
        assert result.render_problems == []
