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

Covers location/reference/ref-section resolution (legacy and modern), reference lookup with its
ObjectsManagerGetError fallback, multi-data-section flattening, and the top-level extraction. The
manager-heavy __init__ is exercised once with ManagerProvider patched; the resolution helpers are
tested on instances built without __init__ side effects.
"""
from types import SimpleNamespace
from unittest.mock import Mock, patch

from cmdb.models.docapi_model.object_template_data import ObjectTemplateData, DG_LOCATION_FIELD_NAME
from cmdb.models.docapi_model.docapi_template_type_enum import DocapiTemplateType
from cmdb.models.docapi_model.reference_result import ReferenceResult
from cmdb.models.type_model.field_type_enum import FieldType

from cmdb.errors.manager.objects_manager import ObjectsManagerGetError
from cmdb.errors.manager.locations_manager import LocationsManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

MODULE: str = 'cmdb.models.docapi_model.object_template_data'

REF: str = FieldType.REFERENCE.value
LOCATION: str = FieldType.LOCATION.value
REF_SECTION: str = FieldType.REF_SECTION.value
TEXT: str = FieldType.TEXT.value


def _make(modern: bool = False, objects_manager=None, locations_manager=None) -> ObjectTemplateData:
    """Builds an ObjectTemplateData without running __init__ (no manager provider / extraction)."""
    instance = ObjectTemplateData.__new__(ObjectTemplateData)
    instance.objects_manager = objects_manager or Mock()
    instance.request_user = Mock()
    instance.locations_manager = locations_manager or Mock()
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


class TestResolveLocation:
    """_resolve_location returns the location name or an empty string."""

    def test_empty_value(self) -> None:
        """A falsy location value resolves to an empty string."""
        assert _make()._resolve_location(0) == ""

    def test_present(self) -> None:
        """A resolvable location returns its name."""
        lm = Mock()
        lm.get_location.return_value = {"name": "Berlin"}

        assert _make(locations_manager=lm)._resolve_location(10) == "Berlin"

    def test_not_found_returns_empty(self) -> None:
        """A None location (not found, no error) resolves to an empty string."""
        lm = Mock()
        lm.get_location.return_value = None

        assert _make(locations_manager=lm)._resolve_location(10) == ""

    def test_error_returns_empty(self) -> None:
        """A LocationsManagerGetError resolves to an empty string (not a crash)."""
        lm = Mock()
        lm.get_location.side_effect = LocationsManagerGetError("boom")

        assert _make(locations_manager=lm)._resolve_location(10) == ""


class TestResolveFieldDispatch:
    """_resolve_field dispatches by name (location) and template mode."""

    def test_location_name_dispatches_to_location(self) -> None:
        """A field named dg_location resolves through the location path."""
        lm = Mock()
        lm.get_location.return_value = {"name": "Berlin"}

        result = _make(locations_manager=lm)._resolve_field(DG_LOCATION_FIELD_NAME, LOCATION, 10, None, 3)

        assert result == "Berlin"

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

    def test_location_not_wrapped(self) -> None:
        """A location field resolves to the raw dict (only 'ref' is wrapped)."""
        instance = _make(modern=True)
        instance._resolve_reference = Mock(return_value={"type_id": 2})

        assert instance._resolve_modern_field(LOCATION, 10, None, 3) == {"type_id": 2}

    def test_ref_section_resolves_subfields(self) -> None:
        """A reference section resolves each sub-field recursively."""
        references = {"fields": [{"name": "sub", "type": TEXT, "value": "sv"}]}

        assert _make(modern=True)._resolve_modern_field(REF_SECTION, None, references, 3) == {"fields": {"sub": "sv"}}

    def test_plain_field_returns_value(self) -> None:
        """A plain field returns its value unchanged."""
        assert _make(modern=True)._resolve_modern_field(TEXT, "hello", None, 3) == "hello"


class TestResolveReference:
    """_resolve_reference resolves an object or falls back to None."""

    @patch(f'{MODULE}.CmdbMultiRender')
    def test_success(self, mock_render: Mock) -> None:
        """A resolvable reference returns the referenced object's extracted data."""
        objects_manager = Mock()
        objects_manager.get_object.return_value = Mock()
        mock_render.return_value.result.return_value = _render(
            fields=[{"name": "h", "type": TEXT, "value": "v"}], object_id=9, type_id=3
        )

        result = _make(objects_manager=objects_manager)._resolve_reference(9, 3)

        assert result["public_id"] == 9
        assert result["fields"]["h"] == "v"

    def test_missing_object_returns_none(self) -> None:
        """A ObjectsManagerGetError resolves to None (reference target gone)."""
        objects_manager = Mock()
        objects_manager.get_object.side_effect = ObjectsManagerGetError("boom")

        assert _make(objects_manager=objects_manager)._resolve_reference(9, 3) is None


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
    """__init__ wires the location manager and seeds the extracted template data."""

    @patch(f'{MODULE}.ManagerProvider')
    def test_init_sets_modern_flag_and_extracts(self, mock_provider: Mock) -> None:
        """A DEFAULT template sets modern_templates and get_template_data returns the extraction."""
        mock_provider.get_manager.return_value = Mock()
        render = _render(fields=[{"name": "h", "type": TEXT, "value": "v"}])

        instance = ObjectTemplateData(render, Mock(), Mock(), DocapiTemplateType.DEFAULT)

        assert instance.modern_templates is True
        assert instance.get_template_data()["fields"]["h"] == "v"
