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
Unit tests for cmdb.models.docapi_model.default_template_data.DefaultTemplateData

Covers the decomposed report pipeline (query run, label map, headers, per-object base/MDS
extraction, row expansion, table build), the escaping/Markup behaviour (regression guard for the
autoescape change, including COLUMNS <br> stacking), the template parsing/prefetch helpers, and a
smoke test of __init__ with the managers patched. Instances are built without __init__ where the
method under test does not need the managers.
"""
from types import SimpleNamespace
from unittest.mock import Mock, patch

from markupsafe import Markup

from cmdb.models.docapi_model.default_template_data import DefaultTemplateData
from cmdb.models.docapi_model.docapi_template_type_enum import DocapiTemplateType
from cmdb.models.docapi_model.safe_object import SafeObject
from cmdb.models.reports_model.mds_mode_enum import MdsMode
# -------------------------------------------------------------------------------------------------------------------- #

MODULE: str = 'cmdb.models.docapi_model.default_template_data'


def _bare() -> DefaultTemplateData:
    """Builds a DefaultTemplateData without running __init__ (no managers / database)."""
    return DefaultTemplateData.__new__(DefaultTemplateData)


def _report_object(public_id: int = 1, fields=None, mds=None) -> SimpleNamespace:
    """Builds a minimal report result object (as objects_manager.iterate yields)."""
    return SimpleNamespace(
        public_id=public_id,
        fields=fields or [],
        multi_data_sections=mds or [],
    )


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    Pure helpers                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
class TestEsc:
    """_esc escapes values but preserves already-trusted Markup."""

    def test_none_becomes_empty(self) -> None:
        """None escapes to an empty string."""
        assert str(_bare()._esc(None)) == ""

    def test_plain_string_escaped(self) -> None:
        """A plain string with HTML is escaped."""
        assert str(_bare()._esc("<b>x</b>")) == "&lt;b&gt;x&lt;/b&gt;"

    def test_markup_preserved(self) -> None:
        """An already-trusted Markup value is returned unescaped."""
        assert str(_bare()._esc(Markup("<br>"))) == "<br>"


class TestBuildReportTable:
    """_build_report_table escapes values but returns trusted Markup."""

    def test_returns_markup(self) -> None:
        """The rendered table is Markup so the autoescaping engine emits it verbatim."""
        table = _bare()._build_report_table(["Public ID"], [["1"]])

        assert isinstance(table, Markup)
        assert table.startswith("<table")

    def test_cell_values_are_escaped(self) -> None:
        """User cell values are HTML-escaped even though the table markup is trusted."""
        table = _bare()._build_report_table(["Public ID", "Name"], [["1", "<script>x</script>"]])

        assert "&lt;script&gt;x&lt;/script&gt;" in table
        assert "<script>" not in table

    def test_header_values_are_escaped(self) -> None:
        """Header labels are HTML-escaped too."""
        assert "&lt;b&gt;ID&lt;/b&gt;" in _bare()._build_report_table(["<b>ID</b>"], [])

    def test_trusted_markup_cell_preserved(self) -> None:
        """A Markup cell (e.g. COLUMNS <br> stack) is preserved, not re-escaped."""
        table = _bare()._build_report_table(["Public ID"], [[Markup("a<br>b")]])

        assert "a<br>b" in table

    def test_empty_headers_returns_empty(self) -> None:
        """No columns yields an empty Markup string."""
        assert _bare()._build_report_table([], []) == ""


class TestExpandMdsRows:
    """_expand_mds_rows produces the cartesian product of MDS section rows."""

    def test_no_sections_single_row(self) -> None:
        """No MDS sections yields a single base row."""
        assert _bare()._expand_mds_rows({"public_id": 1}, []) == [{"public_id": 1}]

    def test_empty_section_no_rows(self) -> None:
        """An empty section yields no rows."""
        assert _bare()._expand_mds_rows({"public_id": 1}, [[]]) == []

    def test_cartesian_product(self) -> None:
        """Two sections produce the cartesian product merged onto the base."""
        rows = _bare()._expand_mds_rows({"public_id": 1}, [[{"a": 1}, {"a": 2}], [{"b": 9}]])

        assert {"public_id": 1, "a": 1, "b": 9} in rows
        assert {"public_id": 1, "a": 2, "b": 9} in rows
        assert len(rows) == 2


class TestExpandMdsColumns:
    """_expand_mds_columns stacks MDS values into <br>-joined, escaped Markup cells."""

    def test_values_joined_and_escaped(self) -> None:
        """Values are escaped and joined with a raw <br> separator (trusted Markup)."""
        result = _bare()._expand_mds_columns({"public_id": 1}, [[{"n": "<a>"}, {"n": "b"}]])

        assert isinstance(result["n"], Markup)
        assert str(result["n"]) == "&lt;a&gt;<br>b"


class TestReportUsesMdsFields:
    """_report_uses_mds_fields detects a selected multi-data-section field."""

    def test_true_when_selected_field_in_mds(self) -> None:
        """Returns True when a selected field belongs to a multi-data-section."""
        report = {"selected_fields": ["mf"]}
        type_obj = {"render_meta": {"sections": [{"type": "multi-data-section", "fields": ["mf"]}]}}

        assert _bare()._report_uses_mds_fields(report, type_obj) is True

    def test_false_when_not_mds_section(self) -> None:
        """Returns False when the selected field is not in a multi-data-section."""
        report = {"selected_fields": ["f"]}
        type_obj = {"render_meta": {"sections": [{"type": "section", "fields": ["f"]}]}}

        assert _bare()._report_uses_mds_fields(report, type_obj) is False

    def test_false_when_mds_field_not_selected(self) -> None:
        """Returns False when the MDS section's field is not among the selected fields."""
        report = {"selected_fields": ["other"]}
        type_obj = {"render_meta": {"sections": [{"type": "multi-data-section", "fields": ["mf"]}]}}

        assert _bare()._report_uses_mds_fields(report, type_obj) is False


class TestReportLabelMapAndHeaders:
    """_report_field_label_map / _report_headers build the header labels."""

    def test_label_map_none_type(self) -> None:
        """A None type yields an empty label map."""
        assert _bare()._report_field_label_map(None) == {}

    def test_label_map_fields_and_mds(self) -> None:
        """Labels come from fields and MDS fields, falling back to the field name."""
        type_obj = {
            "fields": [{"name": "a", "label": "Alpha"}, {"name": "b"}],
            "multi_data_sections": [{"fields": [{"name": "c", "label": "Gamma"}]}],
        }

        label_map = _bare()._report_field_label_map(type_obj)

        assert label_map == {"a": "Alpha", "b": "b", "c": "Gamma"}

    def test_headers_prepend_public_id_and_use_labels(self) -> None:
        """Headers start with Public ID and use labels (falling back to the field id)."""
        headers = _bare()._report_headers({"selected_fields": ["a", "x"]}, {"a": "Alpha"})

        assert headers == ["Public ID", "Alpha", "x"]


class TestObjectExtraction:
    """_object_base_fields / _object_mds_sections extract report-object data."""

    def test_base_fields(self) -> None:
        """Base fields carry the public id and flat field values."""
        obj = _report_object(public_id=7, fields=[{"name": "h", "value": "srv"}])

        assert DefaultTemplateData._object_base_fields(obj) == {"public_id": 7, "h": "srv"}

    def test_mds_sections(self) -> None:
        """MDS sections are extracted as per-section lists of row dicts."""
        mds = [{"values": [{"data": [{"name": "f", "value": "a"}]}, {"data": [{"name": "f", "value": "b"}]}]}]
        obj = _report_object(mds=mds)

        assert DefaultTemplateData._object_mds_sections(obj) == [[{"f": "a"}, {"f": "b"}]]


class TestReportRows:
    """_report_rows expands objects per the report's MDS mode."""

    def test_rows_mode_without_mds(self) -> None:
        """ROWS mode without MDS fields yields one row per object."""
        instance = _bare()
        instance._report_uses_mds_fields = Mock(return_value=False)
        report = {"mds_mode": MdsMode.ROWS, "selected_fields": ["h"]}
        objects = [_report_object(public_id=1, fields=[{"name": "h", "value": "v"}])]

        rows = instance._report_rows(report, objects, type_obj={})

        assert rows == [["1", "v"]]

    def test_columns_mode_stacks(self) -> None:
        """COLUMNS mode stacks MDS values into a single <br>-joined cell."""
        report = {"mds_mode": MdsMode.COLUMNS, "selected_fields": ["m"]}
        mds = [{"values": [{"data": [{"name": "m", "value": "x"}]}, {"data": [{"name": "m", "value": "y"}]}]}]
        objects = [_report_object(public_id=1, mds=mds)]

        rows = _bare()._report_rows(report, objects, type_obj={})

        assert str(rows[0][1]) == "x<br>y"

    def test_rows_mode_with_mds_expands(self) -> None:
        """ROWS mode with MDS fields expands into one row per MDS entry (cartesian product)."""
        instance = _bare()
        instance._report_uses_mds_fields = Mock(return_value=True)
        report = {"mds_mode": MdsMode.ROWS, "selected_fields": ["m"]}
        mds = [{"values": [{"data": [{"name": "m", "value": "x"}]}, {"data": [{"name": "m", "value": "y"}]}]}]
        objects = [_report_object(public_id=1, mds=mds)]

        rows = instance._report_rows(report, objects, type_obj={"x": 1})

        assert len(rows) == 2


class TestRunReportQuery:
    """_run_report_query evaluates the stored query and iterates matching objects."""

    def test_empty_query_returns_empty(self) -> None:
        """An empty query short-circuits to no objects (no iterate call)."""
        instance = _bare()
        instance.objects_manager = Mock()
        report = {"report_query": {"data": "{}"}}

        assert instance._run_report_query(report) == []
        instance.objects_manager.iterate.assert_not_called()

    def test_non_empty_query_iterates(self) -> None:
        """A non-empty query is passed to the objects manager's iterate."""
        instance = _bare()
        instance.objects_manager = Mock()
        instance.objects_manager.iterate.return_value = SimpleNamespace(results=["obj"])
        report = {"report_query": {"data": "{'public_id': {'$gt': 1}}"}}

        assert instance._run_report_query(report) == ["obj"]
        instance.objects_manager.iterate.assert_called_once()


class TestBuildReport:
    """_build_report renders a report into a table or None."""

    def test_unknown_report_id_returns_none(self) -> None:
        """An id not referenced by the template returns None."""
        instance = _bare()
        instance.report_ids = set()

        assert instance._build_report(5) is None

    def test_missing_report_returns_none(self) -> None:
        """A referenced but missing report returns None."""
        instance = _bare()
        instance.report_ids = {5}
        instance.reports_manager = Mock()
        instance.reports_manager.get_item.return_value = None

        assert instance._build_report(5) is None

    def test_renders_table(self) -> None:
        """A resolvable report renders an HTML table (Markup) with the object rows."""
        instance = _bare()
        instance.report_ids = {5}
        instance.reports_manager = Mock()
        instance.reports_manager.get_item.return_value = {
            "report_query": {"data": "{'public_id': {'$gt': 0}}"},
            "type_id": 2,
            "selected_fields": ["h"],
            "mds_mode": MdsMode.ROWS,
        }
        instance.types_manager = Mock()
        instance.types_manager.get_type.return_value = {"fields": [{"name": "h", "label": "Host"}]}
        instance.objects_manager = Mock()
        instance.objects_manager.iterate.return_value = SimpleNamespace(
            results=[_report_object(public_id=1, fields=[{"name": "h", "value": "srv"}])]
        )

        table = instance._build_report(5)

        assert isinstance(table, Markup)
        assert "Host" in table and "srv" in table


# -------------------------------------------------------------------------------------------------------------------- #
#                                              parsing / accessors                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestParsing:
    """_parse_template / _collect_relation_ids extract referenced ids from the template."""

    def test_parse_template_ids(self) -> None:
        """Object and report ids are parsed from the template string."""
        instance = _bare()
        instance._parse_template("{{ object(7) }} and {{ report(3) }}")

        assert instance.external_object_ids == {7}
        assert instance.report_ids == {3}

    def test_collect_relation_ids(self) -> None:
        """Relation ids are collected from the parsed relation placeholders."""
        instance = _bare()
        instance.relation_placeholders = ["root.relation(4, 'parent').public_id"]

        assert instance._collect_relation_ids() == {4}


class TestAccessors:
    """The accessors expose the render context callables."""

    def test_object_accessor_missing_returns_safeobject(self) -> None:
        """object(id) for an uncached id returns a SafeObject fallback."""
        instance = _bare()
        instance.object_cache = {}
        accessor = instance._object_accessor()

        assert isinstance(accessor(999), SafeObject)

    @patch(f'{MODULE}.CmdbObject')
    def test_object_accessor_missing_type_returns_safeobject(self, mock_cmdb_object: Mock) -> None:
        """A cached object with an uncached type returns a SafeObject fallback."""
        instance = _bare()
        instance.object_cache = {5: {"public_id": 5, "type_id": 2}}
        instance.type_cache = {}
        mock_cmdb_object.from_data.return_value.get_type_id.return_value = 2

        assert isinstance(instance._object_accessor()(5), SafeObject)

    @patch(f'{MODULE}.safe_wrap', side_effect=lambda data: data)
    @patch(f'{MODULE}.ObjectTemplateData')
    @patch(f'{MODULE}.CmdbMultiRender')
    @patch(f'{MODULE}.CmdbObject')
    def test_object_accessor_resolves_object(
        self, mock_cmdb_object: Mock, mock_render: Mock, mock_object_data: Mock, _mock_wrap: Mock
    ) -> None:
        """A cached object with a cached type renders and returns its (wrapped) template data."""
        instance = _bare()
        instance.object_cache = {5: {"public_id": 5, "type_id": 2}}
        instance.type_cache = {2: {"public_id": 2}}
        instance.objects_manager = Mock()
        instance.request_user = Mock()
        instance.template_type = DocapiTemplateType.DEFAULT
        mock_cmdb_object.from_data.return_value.get_type_id.return_value = 2
        mock_object_data.return_value.get_template_data.return_value = {"public_id": 5}

        assert instance._object_accessor()(5) == {"public_id": 5}

    def test_report_accessor_delegates_to_build_report(self) -> None:
        """report(id) delegates to _build_report."""
        instance = _bare()
        instance._build_report = Mock(return_value="TABLE")

        assert instance._report_accessor()(5) == "TABLE"
        instance._build_report.assert_called_once_with(5)

    def test_root_accessor_adds_relation(self) -> None:
        """root exposes the root data plus a relation accessor callable."""
        instance = _bare()
        instance.root_data = {"public_id": 1, "fields": {}}
        instance.root_object_id = 1
        instance.object_relations = []

        root = instance._root_accessor()

        assert root["public_id"] == 1
        assert callable(root["relation"])


class TestRelationTraversal:
    """_relation_traversal selects matching object relations for a hop."""

    @patch(f'{MODULE}.RelationResult')
    def test_child_matches(self, mock_relation_result: Mock) -> None:
        """A child hop collects the child ids of matching parent relations."""
        instance = _bare()
        instance.object_cache = {}
        instance.type_cache = {}
        instance.objects_manager = Mock()
        instance.objects_manager.find.return_value = []
        instance.types_manager = Mock()
        instance.request_user = Mock()
        instance.template_type = DocapiTemplateType.DEFAULT
        instance.all_object_relations = []
        instance.object_relations = [
            {"relation_id": 1, "relation_parent_id": 10, "relation_child_id": 20},
        ]

        instance._relation_traversal(10, 1, "child")

        matches = mock_relation_result.call_args[0][0]
        assert matches == [20]

    @patch(f'{MODULE}.RelationResult')
    def test_parent_matches_and_scoped(self, mock_relation_result: Mock) -> None:
        """A parent hop collects parent ids and the scoped relations for that hop."""
        instance = _bare()
        instance.object_cache = {}
        instance.type_cache = {}
        instance.objects_manager = Mock()
        instance.objects_manager.find.return_value = []
        instance.types_manager = Mock()
        instance.request_user = Mock()
        instance.template_type = DocapiTemplateType.DEFAULT
        instance.all_object_relations = []
        instance.object_relations = [
            {"relation_id": 1, "relation_parent_id": 30, "relation_child_id": 10},
        ]

        instance._relation_traversal(10, 1, "parent")

        assert mock_relation_result.call_args[0][0] == [30]
        scoped = mock_relation_result.call_args[0][3]
        assert scoped == instance.object_relations

    @patch(f'{MODULE}.RelationResult')
    def test_accessor_closure_skips_other_relations(self, mock_relation_result: Mock) -> None:
        """The relation-accessor closure traverses only the requested relation id."""
        instance = _bare()
        instance.object_cache = {}
        instance.type_cache = {}
        instance.objects_manager = Mock()
        instance.objects_manager.find.return_value = []
        instance.types_manager = Mock()
        instance.request_user = Mock()
        instance.template_type = DocapiTemplateType.DEFAULT
        instance.all_object_relations = []
        instance.object_relations = [
            {"relation_id": 1, "relation_parent_id": 10, "relation_child_id": 20},
            {"relation_id": 2, "relation_parent_id": 10, "relation_child_id": 99},  # other relation, skipped
        ]

        instance._relation_accessor(10)(1, "child")

        assert mock_relation_result.call_args[0][0] == [20]


class TestCacheAndPrefetch:
    """_cache_objects_and_types and the __init__ prefetch helpers populate the caches."""

    def test_cache_loads_missing_objects_and_types(self) -> None:
        """Uncached object ids and their types are fetched into the caches."""
        instance = _bare()
        instance.object_cache = {}
        instance.type_cache = {}
        instance.objects_manager = Mock()
        instance.objects_manager.find.return_value = [{"public_id": 20, "type_id": 2}]
        instance.types_manager = Mock()
        instance.types_manager.find.return_value = [{"public_id": 2}]

        instance._cache_objects_and_types([20])

        assert instance.object_cache[20]["type_id"] == 2
        assert 2 in instance.type_cache

    def test_prefetch_objects_and_types(self) -> None:
        """_prefetch_objects_and_types loads objects then their types."""
        instance = _bare()
        instance.object_cache = {}
        instance.type_cache = {}
        instance.objects_manager = Mock()
        instance.objects_manager.find.return_value = [{"public_id": 5, "type_id": 2}]
        instance.types_manager = Mock()
        instance.types_manager.find.return_value = [{"public_id": 2}]

        instance._prefetch_objects_and_types({5})

        assert instance.object_cache[5]["type_id"] == 2
        assert 2 in instance.type_cache

    def test_prefetch_relations(self) -> None:
        """_prefetch_relations loads relations and object-relations into the caches."""
        instance = _bare()
        instance.relation_cache = {}
        instance.relations_manager = Mock()
        instance.relations_manager.find.return_value = [{"public_id": 4}]
        instance.object_relations_manager = Mock()
        instance.object_relations_manager.find.return_value = [{"relation_id": 4}]
        instance.all_object_relations = []

        instance._prefetch_relations({4})

        assert instance.relation_cache == {4: {"public_id": 4}}
        assert instance.all_object_relations == [{"relation_id": 4}]

    def test_prefetch_relations_empty_is_noop(self) -> None:
        """With no relation ids, no query is issued."""
        instance = _bare()
        instance.relations_manager = Mock()

        instance._prefetch_relations(set())

        instance.relations_manager.find.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       __init__                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestInit:
    """__init__ wires managers, extracts the root and builds the render context."""

    @patch(f'{MODULE}.ObjectTemplateData')
    @patch(f'{MODULE}.ManagerProvider')
    def test_builds_template_data(self, mock_provider: Mock, mock_object_data: Mock) -> None:
        """The constructed template_data exposes root/object/report and the parsed ids."""
        manager = Mock()
        manager.find.return_value = []
        mock_provider.get_manager.return_value = manager
        mock_object_data.return_value.get_template_data.return_value = {"public_id": 5}

        instance = DefaultTemplateData(Mock(), "{{ object(7) }}", Mock(), DocapiTemplateType.DEFAULT)

        assert instance.root_object_id == 5
        assert instance.external_object_ids == {7}
        assert set(instance.get_template_data().keys()) == {"root", "object", "report"}
