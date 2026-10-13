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
Unit tests for cmdb.models.docapi_model.object_template_data.ObjectTemplateData

Covers location/reference/ref-section resolution (legacy and modern), reference resolution through the document's
resolver with its memo, multi-data-section flattening, and the top-level extraction. Reading, rendering and the
location names are the resolver's (`test_document_reference_resolver.py`); here it is a Mock. The resolution helpers
are tested on instances built without __init__ side effects.
"""
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from cmdb.models.docapi_model.object_template_data import ObjectTemplateData
from cmdb.models.docapi_model.docapi_reference_constants import DEFAULT_REFERENCE_DEPTH
from cmdb.models.docapi_model.docapi_template_type_enum import DocapiTemplateType
from cmdb.models.docapi_model.reference_result import ReferenceResult
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.type_constants import DG_LOCATION_FIELD_NAME
# -------------------------------------------------------------------------------------------------------------------- #

MODULE: str = 'cmdb.models.docapi_model.object_template_data'

REF: str = FieldType.REFERENCE.value
LOCATION: str = FieldType.LOCATION.value
REF_SECTION: str = FieldType.REF_SECTION.value
TEXT: str = FieldType.TEXT.value


def _make(modern: bool = False, location_name: str = "Berlin") -> ObjectTemplateData:
    """Builds an ObjectTemplateData without running __init__, on a Mock resolver with an empty memo."""
    instance = ObjectTemplateData.__new__(ObjectTemplateData)
    instance.objects_manager = Mock()
    instance.request_user = Mock()
    instance.reference_resolver = Mock(extracted={})
    instance.reference_resolver.location_name.return_value = location_name
    instance.modern_templates = modern
    instance.template_type = DocapiTemplateType.DEFAULT if modern else DocapiTemplateType.OBJECT
    return instance


def _render(fields=None, mds=None, object_id: int = 5, type_id: int = 2) -> SimpleNamespace:
    """Builds a minimal RenderResult-like object for extraction tests."""
    return SimpleNamespace(
        object_information={"object_id": object_id},
        type_information={"type_id": type_id},
        fields=fields or [],
        multi_data_sections=mds or [],
    )


class TestResolveFieldDispatch:
    """_resolve_field dispatches by name (location) and template mode."""

    def test_location_name_dispatches_to_location(self) -> None:
        """A field named dg_location resolves through the document's location names."""
        instance = _make()

        assert instance._resolve_field(DG_LOCATION_FIELD_NAME, LOCATION, 10, None, 3) == "Berlin"
        instance.reference_resolver.location_name.assert_called_once_with(10)

    @pytest.mark.parametrize('modern', [True, False], ids=['default', 'object'])
    def test_any_location_typed_field_dispatches_to_location(self, modern: bool) -> None:
        """Whatever its name: a location field is its location's name, in both template types"""
        instance = _make(modern=modern)
        instance._resolve_reference = Mock()

        assert instance._resolve_field('placement', LOCATION, 10, None, 3) == "Berlin"
        instance.reference_resolver.location_name.assert_called_once_with(10)
        instance._resolve_reference.assert_not_called()

    def test_a_location_inside_a_reference_section_is_its_name(self) -> None:
        """The section's sub-fields dispatch through the same rule"""
        references = {"fields": [{"name": "placement", "type": LOCATION, "value": 10}]}

        result = _make(modern=True)._resolve_modern_field(REF_SECTION, None, references, 3)

        assert result == {"fields": {"placement": "Berlin"}}

    def test_modern_mode_uses_reference_result(self) -> None:
        """A modern ref field resolves to a ReferenceResult."""
        instance = _make(modern=True)
        instance._resolve_reference = Mock(return_value={"type_id": 2})

        assert isinstance(instance._resolve_field("f", REF, 10, None, 3), ReferenceResult)

    def test_legacy_mode_returns_raw_reference(self) -> None:
        """A legacy ref field resolves to the raw extracted dict."""
        instance = _make(modern=False)
        instance._resolve_reference = Mock(return_value={"type_id": 2})

        assert instance._resolve_field("f", REF, 10, None, 3) == {"type_id": 2}


class TestResolveLegacyField:
    """OBJECT (legacy) template field resolution."""

    def test_reference_resolved(self) -> None:
        """A ref with a value and depth resolves via _resolve_reference."""
        instance = _make()
        instance._resolve_reference = Mock(return_value={"type_id": 9})

        assert instance._resolve_legacy_field(REF, 10, None, 3) == {"type_id": 9}

    def test_reference_zero_depth_returns_value(self) -> None:
        """A ref at depth 0 is not resolved and returns the raw value."""
        assert _make()._resolve_legacy_field(REF, 10, None, 0) == 10

    def test_a_location_is_never_followed_as_a_reference(self) -> None:
        """Its value is a CmdbLocation id, not an object's: no object is read for it"""
        instance = _make()
        instance._resolve_reference = Mock(return_value={"type_id": 2})

        assert instance._resolve_legacy_field(LOCATION, 10, None, 3) == 10
        instance._resolve_reference.assert_not_called()

    def test_ref_section_maps_name_to_value(self) -> None:
        """A reference section flattens to {name: value}."""
        references = {"fields": [{"name": "a", "value": "x"}, {"name": "b", "value": "y"}]}

        assert _make()._resolve_legacy_field(REF_SECTION, None, references, 3) == {"fields": {"a": "x", "b": "y"}}

    def test_plain_field_returns_value(self) -> None:
        """A plain field returns its value unchanged."""
        assert _make()._resolve_legacy_field(TEXT, "hello", None, 3) == "hello"


class TestResolveModernField:
    """DEFAULT (modern) template field resolution."""

    def test_reference_wrapped(self) -> None:
        """A resolvable ref is wrapped in a ReferenceResult."""
        instance = _make(modern=True)
        instance._resolve_reference = Mock(return_value={"type_id": 2})

        assert isinstance(instance._resolve_modern_field(REF, 10, None, 3), ReferenceResult)

    def test_reference_none_returns_none(self) -> None:
        """An unresolvable ref returns None."""
        instance = _make(modern=True)
        instance._resolve_reference = Mock(return_value=None)

        assert instance._resolve_modern_field(REF, 10, None, 3) is None

    def test_a_location_is_never_followed_as_a_reference(self) -> None:
        """Its value is a CmdbLocation id, not an object's: no object is read for it"""
        instance = _make(modern=True)
        instance._resolve_reference = Mock(return_value={"type_id": 2})

        assert instance._resolve_modern_field(LOCATION, 10, None, 3) == 10
        instance._resolve_reference.assert_not_called()

    def test_ref_section_resolves_subfields(self) -> None:
        """A reference section resolves each sub-field recursively."""
        references = {"fields": [{"name": "sub", "type": TEXT, "value": "sv"}]}

        assert _make(modern=True)._resolve_modern_field(REF_SECTION, None, references, 3) == {"fields": {"sub": "sv"}}

    def test_plain_field_returns_value(self) -> None:
        """A plain field returns its value unchanged."""
        assert _make(modern=True)._resolve_modern_field(TEXT, "hello", None, 3) == "hello"


class TestExtractMds:
    """_extract_mds flattens multi-data-sections into comma-joined per-field strings."""

    def test_values_joined(self) -> None:
        """Repeated field values within a section are comma-joined."""
        mds = [{"section_id": "s1", "values": [
            {"data": [{"name": "f", "value": "a"}]},
            {"data": [{"name": "f", "value": "b"}]},
        ]}]

        assert _make()._extract_mds(_render(mds=mds))["s1"]["f"] == "a, b"

    def test_none_value_becomes_empty(self) -> None:
        """A None value is rendered as an empty string in the joined result."""
        mds = [{"section_id": "s", "values": [{"data": [{"name": "f", "value": None}]}]}]

        assert _make()._extract_mds(_render(mds=mds))["s"]["f"] == ""

    def test_section_without_id_skipped(self) -> None:
        """A section without a section_id is skipped."""
        mds = [{"values": [{"data": [{"name": "f", "value": "a"}]}]}]

        assert _make()._extract_mds(_render(mds=mds)) == {}

    def test_field_without_name_skipped(self) -> None:
        """An MDS field entry with no name is skipped."""
        mds = [{"section_id": "s", "values": [{"data": [
            {"value": "orphan"},
            {"name": "f", "value": "a"},
        ]}]}]

        assert _make()._extract_mds(_render(mds=mds))["s"] == {"f": "a"}


class TestExtractObjectData:
    """extract_object_data builds the id/type/fields structure and merges MDS."""

    def test_basic_fields(self) -> None:
        """Ids, type and simple fields are extracted."""
        render = _render(fields=[{"name": "h", "type": TEXT, "value": "v"}])

        data = _make().extract_object_data(render, 3)

        assert data["id"] == 5 and data["public_id"] == 5 and data["type_id"] == 2
        assert data["fields"] == {"h": "v"}

    def test_field_without_name_skipped(self) -> None:
        """A field with no name is skipped."""
        render = _render(fields=[{"type": TEXT, "value": "v"}])

        assert _make().extract_object_data(render, 3)["fields"] == {}

    def test_field_resolution_error_is_skipped(self) -> None:
        """A field whose resolution raises is logged and skipped, not fatal."""
        instance = _make()
        instance._resolve_field = Mock(side_effect=ValueError("boom"))
        render = _render(fields=[{"name": "bad", "type": TEXT, "value": "v"}])

        assert instance.extract_object_data(render, 3)["fields"] == {}

    def test_mds_merged_when_present(self) -> None:
        """A non-empty MDS result is merged under the 'mds' key."""
        mds = [{"section_id": "s", "values": [{"data": [{"name": "f", "value": "a"}]}]}]
        render = _render(fields=[], mds=mds)

        assert _make().extract_object_data(render, 3)["mds"]["s"]["f"] == "a"


class TestInit:
    """__init__ prepares the render's references through the resolver, then extracts."""

    def test_init_sets_modern_flag_prepares_and_extracts(self) -> None:
        """A DEFAULT template: the levels are prepared from this render before the data is extracted"""
        resolver = Mock(extracted={})
        render = _render(fields=[{"name": "h", "type": TEXT, "value": "v"}])

        instance = ObjectTemplateData(render, Mock(), Mock(), DocapiTemplateType.DEFAULT, resolver)

        assert instance.modern_templates is True
        assert instance.reference_resolver is resolver
        resolver.prepare.assert_called_once_with([render], DEFAULT_REFERENCE_DEPTH, True)
        assert instance.get_template_data()["fields"]["h"] == "v"

    @patch(f'{MODULE}.DocumentReferenceResolver')
    def test_without_a_resolver_one_is_started_for_this_object(self, resolver_class: Mock) -> None:
        """For the user and the objects manager given - an OBJECT template prepares in legacy mode"""
        objects_manager, user = Mock(), Mock()
        render = _render()

        instance = ObjectTemplateData(render, objects_manager, user, DocapiTemplateType.OBJECT)

        resolver_class.assert_called_once_with(user, objects_manager)
        assert instance.reference_resolver is resolver_class.return_value
        resolver_class.return_value.prepare.assert_called_once_with([render], DEFAULT_REFERENCE_DEPTH, False)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  _resolve_reference                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
REFERENCED_ID: int = 55


class TestResolveReference:
    """A referenced object's render comes from the document's resolver; what is extracted is kept per document."""

    def test_an_unresolvable_object_resolves_to_none(self) -> None:
        """Unreadable or missing - the resolver answers None, and nothing is extracted or remembered"""
        instance = _make()
        instance.reference_resolver.render_for.return_value = None
        instance.extract_object_data = Mock()

        assert instance._resolve_reference(REFERENCED_ID, 2) is None
        instance.reference_resolver.render_for.assert_called_once_with(REFERENCED_ID)
        instance.extract_object_data.assert_not_called()
        assert instance.reference_resolver.extracted == {}

    def test_a_readable_object_is_extracted_one_level_shallower(self) -> None:
        """The render of the referenced object, extracted with one hop less"""
        instance = _make()
        render = Mock(name='render')
        instance.reference_resolver.render_for.return_value = render
        instance.extract_object_data = Mock(return_value={'public_id': REFERENCED_ID})

        assert instance._resolve_reference(REFERENCED_ID, 2) == {'public_id': REFERENCED_ID}
        instance.extract_object_data.assert_called_once_with(render, 1)

    def test_the_extraction_is_remembered_per_object_depth_and_mode(self) -> None:
        """Stored under (id, depth, mode) - a second reference to it at that depth costs nothing"""
        instance = _make(modern=True)
        instance.reference_resolver.render_for.return_value = Mock(name='render')
        instance.extract_object_data = Mock(return_value={'public_id': REFERENCED_ID})

        first = instance._resolve_reference(REFERENCED_ID, 2)
        second = instance._resolve_reference(REFERENCED_ID, 2)

        assert first is second
        assert instance.reference_resolver.extracted == {(REFERENCED_ID, 2, True): first}
        instance.reference_resolver.render_for.assert_called_once_with(REFERENCED_ID)
        instance.extract_object_data.assert_called_once()

    @pytest.mark.parametrize('stored_key', [(REFERENCED_ID, 3, False), (REFERENCED_ID, 2, True), (56, 2, False)])
    def test_another_depth_mode_or_object_is_extracted_anew(self, stored_key: tuple[int, int, bool]) -> None:
        """A remembered extraction answers only its own key"""
        instance = _make(modern=False)
        instance.reference_resolver.extracted[stored_key] = {'stale': True}
        instance.reference_resolver.render_for.return_value = Mock(name='render')
        instance.extract_object_data = Mock(return_value={'public_id': REFERENCED_ID})

        assert instance._resolve_reference(REFERENCED_ID, 2) == {'public_id': REFERENCED_ID}
