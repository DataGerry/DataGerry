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
Implementation of DefaultTemplateData
"""
import re
from logging import Logger, getLogger
from typing import Any, Callable
from datetime import datetime
from itertools import product

from markupsafe import Markup, escape

from cmdb.framework.rendering.render_result import RenderResult
from cmdb.manager.query_builder import BuilderParameters

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import (
    ObjectsManager,
    TypesManager,
    ObjectRelationsManager,
    RelationsManager,
    ReportsManager,
)

from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model.section_type_enum import SectionType
from cmdb.models.reports_model.mds_mode_enum import MdsMode
from cmdb.models.docapi_model.docapi_template_type_enum import DocapiTemplateType
from cmdb.models.user_model import CmdbUser
from cmdb.models.docapi_model.object_template_data import ObjectTemplateData
from cmdb.models.docapi_model.safe_object import SafeObject
from cmdb.models.docapi_model.safe_wrap import safe_wrap
from cmdb.framework.rendering.cmdb_multi_render import CmdbMultiRender
from cmdb.models.docapi_model.relation_result import RelationResult
from cmdb.models.docapi_model.docapi_cache_helper import cache_objects_and_types
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

EXTERNAL_OBJECT_REGEX = re.compile(r"\{\{\s*object\((\d+)\)")

REPORT_REGEX = re.compile(r"\{\{\s*report\((\d+)\)\s*\}\}")

RELATION_PLACEHOLDER_REGEX = re.compile(
    r"""
    root
    (?:
        \.relation\(\s*\d+\s*,\s*(?:'parent'|'child')\s*\)
        (?:\.type\(\s*\d+\s*\))?
    )+
    (?:
        \.(?:fields|relation_field)\[['"].+?['"]\]
        |\.public_id
    )?
    """,
    re.VERBOSE,
)

RELATION_STEP_REGEX = re.compile(
    r"""
    \.relation\(
        \s*(\d+)\s*,\s*('parent'|'child')\s*
    \)
    (?:\.type\(\s*(\d+)\s*\))?
    """,
    re.VERBOSE,
)

# The first column (Public ID) is narrow; the remaining columns share the rest evenly
FIRST_COLUMN_PCT: int = 10
# `report_query.data` is the repr of a Python dict using `datetime.datetime(...)`; it is eval'd in a
# locked-down namespace (only `datetime`, no builtins) so it cannot reach arbitrary code
REPORT_QUERY_TOKEN: str = "datetime.datetime"

# -------------------------------------------------------------------------------------------------------------------- #
#                                              DefaultTemplateData - CLASS                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class DefaultTemplateData:
    """
    Builds the render context for DEFAULT (modern) DocAPI templates

    Exposes the root object plus ``object(id)`` / ``report(id)`` accessors and relation traversal,
    prefetching the objects, types and relations referenced by the template string.
    """
    def __init__(
        self,
        cmdb_render_object: RenderResult,
        template_string: str,
        request_user: CmdbUser,
        template_type: DocapiTemplateType
    ) -> None:
        """
        Initializes the DefaultTemplateData

        Args:
            cmdb_render_object (RenderResult): The RenderResult of the root object
            template_string (str): The raw template body (parsed for referenced ids)
            request_user (CmdbUser): The user requesting the document
            template_type (DocapiTemplateType): The template type
        """
        self.template_string = template_string
        self.request_user = request_user
        self.template_type = template_type

        self._init_managers(request_user)

        # Root object
        self.root_data = ObjectTemplateData(
            cmdb_render_object,
            self.objects_manager,
            self.request_user,
            self.template_type
        ).get_template_data()
        self.root_object_id = self.root_data["public_id"]

        # Parse the template once for referenced object / report / relation ids
        self._parse_template(template_string)

        # Caches
        self.object_cache: dict[int, dict] = {}
        self.type_cache: dict[int, dict] = {}
        self.relation_cache: dict[int, dict] = {}
        self.all_object_relations: list[dict] = []

        object_ids = set(self.external_object_ids)
        object_ids.add(self.root_object_id)
        self._prefetch_objects_and_types(object_ids)

        self._prefetch_relations(self._collect_relation_ids())
        # Scoped copy used for first-hop traversal
        self.object_relations: list[dict] = list(self.all_object_relations)

        # Final template data
        self.template_data: dict[str, Any] = {
            "root": self._root_accessor(),
            "object": self._object_accessor(),
            "report": self._report_accessor(),
        }


    def get_template_data(self) -> dict[str, Any]:
        """
        Returns the template_data

        Returns:
            dict[str, Any]: The render context (root / object / report)
        """
        return self.template_data

# ------------------------------------------------- INIT / PREFETCH -------------------------------------------------- #

    def _init_managers(self, request_user: CmdbUser) -> None:
        """Resolves the managers used for prefetching and rendering."""
        self.objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        self.types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
        self.relations_manager: RelationsManager = ManagerProvider.get_manager(ManagerType.RELATIONS, request_user)
        self.object_relations_manager: ObjectRelationsManager = ManagerProvider.get_manager(
            ManagerType.OBJECT_RELATIONS, request_user
        )
        self.reports_manager: ReportsManager = ManagerProvider.get_manager(ManagerType.REPORTS, request_user)


    def _parse_template(self, template_string: str) -> None:
        """Extracts the referenced object ids, report ids and relation placeholders from the template."""
        self.external_object_ids = {int(m) for m in EXTERNAL_OBJECT_REGEX.findall(template_string)}
        self.report_ids = {int(m) for m in REPORT_REGEX.findall(template_string)}
        self.relation_placeholders = [m.group() for m in RELATION_PLACEHOLDER_REGEX.finditer(template_string)]


    def _collect_relation_ids(self) -> set[int]:
        """Collects the relation ids referenced by the template's relation placeholders."""
        relation_ids: set[int] = set()
        for placeholder in self.relation_placeholders:
            for rel_id, _, _ in RELATION_STEP_REGEX.findall(placeholder):
                relation_ids.add(int(rel_id))

        return relation_ids


    def _prefetch_objects_and_types(self, object_ids: set[int]) -> None:
        """Loads the referenced objects and their types into the caches."""
        if object_ids:
            for obj in self.objects_manager.find(criteria={"public_id": {"$in": list(object_ids)}}):
                self.object_cache[obj["public_id"]] = obj

        type_ids = {obj["type_id"] for obj in self.object_cache.values() if obj.get("type_id")}
        if type_ids:
            for obj_type in self.types_manager.find(criteria={"public_id": {"$in": list(type_ids)}}):
                self.type_cache[obj_type["public_id"]] = obj_type


    def _prefetch_relations(self, relation_ids: set[int]) -> None:
        """Loads the referenced relations and their object-relations into the caches."""
        if not relation_ids:
            return

        for relation in self.relations_manager.find(criteria={"public_id": {"$in": list(relation_ids)}}):
            self.relation_cache[relation["public_id"]] = relation

        self.all_object_relations = list(
            self.object_relations_manager.find(criteria={"relation_id": {"$in": list(relation_ids)}})
        )

# ----------------------------------------------------- ACCESSORS ---------------------------------------------------- #

    def _root_accessor(self) -> dict[str, Any]:
        """Builds the root render context (root object data plus its relation accessor)."""
        root = dict(self.root_data)
        root["relation"] = self._relation_accessor(self.root_object_id)

        return root


    def _relation_accessor(self, start_object_id: int) -> Callable[[int, str], RelationResult]:
        """Returns a callable resolving a relation hop from `start_object_id`."""
        def _relation_fn(relation_id: int, side: str) -> RelationResult:
            return self._relation_traversal(start_object_id, relation_id, side)

        return _relation_fn


    def _relation_traversal(self, start_object_id: int, relation_id: int, side: str) -> RelationResult:
        """
        Resolves one relation hop into a RelationResult

        Args:
            start_object_id (int): The object the hop starts from
            relation_id (int): The relation to traverse
            side (str): The traversal direction ('parent' or 'child')

        Returns:
            RelationResult: The matched objects with the caches for further traversal
        """
        matches = []

        for rel in self.object_relations:
            if rel["relation_id"] != relation_id:
                continue

            if side == "parent" and rel["relation_child_id"] == start_object_id:
                matches.append(rel["relation_parent_id"])
            elif side == "child" and rel["relation_parent_id"] == start_object_id:
                matches.append(rel["relation_child_id"])

        self._cache_objects_and_types(matches)

        scoped_relations = []
        for rel in self.object_relations:
            if rel["relation_id"] != relation_id:
                continue

            if side == "parent":
                if rel["relation_child_id"] == start_object_id and rel["relation_parent_id"] in matches:
                    scoped_relations.append(rel)
            elif side == "child":
                if rel["relation_parent_id"] == start_object_id and rel["relation_child_id"] in matches:
                    scoped_relations.append(rel)

        return RelationResult(
            matches,
            self.object_cache,
            self.type_cache,
            scoped_relations,           # scoped for relation_fields
            self.all_object_relations,  # global for multi-hop traversal
            self.request_user,
            self.objects_manager,
            self.types_manager,
            self.template_type
        )


    def _cache_objects_and_types(self, object_ids: list[int]) -> None:
        """Lazily loads any of `object_ids` (and their types) not already cached."""
        cache_objects_and_types(
            object_ids,
            self.object_cache,
            self.type_cache,
            self.objects_manager,
            self.types_manager,
        )


    def _object_accessor(self) -> Callable[[int], Any]:
        """Returns a callable resolving an external ``object(id)`` reference to its (safe) data."""
        def _object_fn(public_id: int) -> Any:
            obj = self.object_cache.get(public_id)
            if not obj:
                return SafeObject()

            cmdb_object = CmdbObject.from_data(obj)
            obj_type = self.type_cache.get(cmdb_object.get_type_id())
            if not obj_type:
                return SafeObject()

            render: RenderResult = CmdbMultiRender([cmdb_object], self.request_user).result(single_object=True)

            result = ObjectTemplateData(
                render,
                self.objects_manager,
                self.request_user,
                self.template_type
            ).get_template_data()

            return safe_wrap(result)

        return _object_fn


    def _report_accessor(self) -> Callable[[int], Any]:
        """Returns a callable rendering a ``report(id)`` reference into an HTML table."""
        def _report_fn(public_id: int) -> Any:
            return self._build_report(public_id)

        return _report_fn

# ------------------------------------------------------ REPORT ------------------------------------------------------ #

    def _build_report(self, public_id: int) -> Markup | None:
        """
        Renders a report into an HTML table, or None when the report is unknown/missing

        Args:
            public_id (int): The report's public id

        Returns:
            Markup | None: The rendered report table, or None
        """
        if public_id not in self.report_ids:
            return None

        report = self.reports_manager.get_item(public_id, as_dict=True)
        if not report:
            return None

        objects = self._run_report_query(report)

        type_id = report.get("type_id")
        type_obj = self.types_manager.get_type(type_id) if type_id else None

        field_label_map = self._report_field_label_map(type_obj)
        headers = self._report_headers(report, field_label_map)
        rows = self._report_rows(report, objects, type_obj)

        return self._build_report_table(headers, rows)


    def _run_report_query(self, report: dict[str, Any]) -> list:
        """
        Evaluates the stored report query and returns the matching objects

        Args:
            report (dict[str, Any]): The report definition

        Returns:
            list: The objects matching the report query (empty when the query is empty)
        """
        query_str = report["report_query"]["data"]

        # eval in a locked-down namespace (only 'datetime', no builtins) so it cannot reach arbitrary code
        safe_globals = {"datetime": datetime, "__builtins__": {}}
        # pylint: disable=W0123
        report_query = eval(query_str.replace(REPORT_QUERY_TOKEN, "datetime"), safe_globals)

        if not report_query:
            return []

        builder_params = BuilderParameters(criteria=report_query)

        return self.objects_manager.iterate(builder_params).results


    def _report_field_label_map(self, type_obj: dict[str, Any] | None) -> dict[str, str]:
        """Builds a field-name -> label map from a type's fields and multi-data-section fields."""
        label_map: dict[str, str] = {}
        if not type_obj:
            return label_map

        for field in type_obj.get("fields", []):
            label_map[field["name"]] = field.get("label", field["name"])

        for section in type_obj.get("multi_data_sections", []):
            for field in section.get("fields", []):
                label_map[field["name"]] = field.get("label", field["name"])

        return label_map


    def _report_headers(self, report: dict[str, Any], field_label_map: dict[str, str]) -> list[str]:
        """Builds the report table header row (Public ID plus the selected fields' labels)."""
        headers = ["Public ID"]
        for field_id in report.get("selected_fields", []):
            headers.append(field_label_map.get(field_id, field_id))

        return headers


    def _report_rows(self, report: dict[str, Any], objects: list, type_obj: dict[str, Any] | None) -> list[list[Any]]:
        """
        Builds the report table body rows, expanding multi-data-sections per the report's MDS mode

        Args:
            report (dict[str, Any]): The report definition
            objects (list): The objects matching the report query
            type_obj (dict[str, Any] | None): The report's type (for MDS-field detection)

        Returns:
            list[list[str]]: The table body rows
        """
        mds_mode = report.get("mds_mode", MdsMode.ROWS)
        use_mds = bool(type_obj) and mds_mode == MdsMode.ROWS and self._report_uses_mds_fields(report, type_obj)

        rows: list[list[str]] = []
        for obj in objects:
            base_fields = self._object_base_fields(obj)
            mds_sections = self._object_mds_sections(obj)

            if mds_mode == MdsMode.COLUMNS:
                expanded_rows = [self._expand_mds_columns(base_fields, mds_sections)]
            elif use_mds:
                expanded_rows = self._expand_mds_rows(base_fields, mds_sections)
            else:
                expanded_rows = [base_fields]  # no cartesian product

            for expanded in expanded_rows:
                rows.append(self._report_row(report, expanded))

        return rows


    def _report_row(self, report: dict[str, Any], expanded: dict[str, Any]) -> list[Any]:
        """
        Builds a single report row (Public ID cell plus one raw cell per selected field)

        Cells are left raw (str / int / Markup / None); `_build_report_table` escapes them via
        `_esc`, which preserves already-trusted `Markup` (e.g. the ``<br>``-joined COLUMNS cells).
        """
        row: list[Any] = [str(expanded.get("public_id", ""))]
        for field_id in report.get("selected_fields", []):
            row.append(expanded.get(field_id, ""))

        return row


    @staticmethod
    def _object_base_fields(obj: CmdbObject) -> dict[str, Any]:
        """Extracts an object's public id and flat field values."""
        base_fields: dict[str, Any] = {"public_id": obj.public_id}
        for field in obj.fields:
            base_fields[field["name"]] = field.get("value")

        return base_fields


    @staticmethod
    def _object_mds_sections(obj: CmdbObject) -> list[list[dict]]:
        """Extracts an object's multi-data-sections as a list of per-section row dicts."""
        mds_sections: list[list[dict]] = []
        for section in obj.multi_data_sections:
            section_rows = []
            for entry in section.get("values", []):
                row_data = {}
                for field in entry.get("data", []):
                    row_data[field["name"]] = field.get("value")
                section_rows.append(row_data)
            mds_sections.append(section_rows)

        return mds_sections

# ------------------------------------------------------ HELPERS ----------------------------------------------------- #

    def _esc(self, value: Any) -> Markup:
        """
        Escapes a value for safe HTML output, leaving already-trusted `Markup` untouched

        Args:
            value (Any): The value to escape

        Returns:
            Markup: The escaped (or already-trusted) markup
        """
        return escape("" if value is None else value)


    def _build_report_table(self, headers: list[str], rows: list[list[str]]) -> Markup:
        """
        Builds an HTML table that renders correctly in xhtml2pdf (PDF output)

        Column widths are forced inline (xhtml2pdf ignores most CSS layout rules): a narrow first
        column (Public ID) and the remaining columns sharing the rest evenly. Cell/header values
        are HTML-escaped; the returned table is trusted `Markup`.

        Args:
            headers (list[str]): The header labels
            rows (list[list[str]]): The body rows

        Returns:
            Markup: The rendered table (empty string when there are no columns)
        """
        num_cols: int = len(headers)
        if num_cols < 1:
            return Markup("")

        remaining_pct = 100 - FIRST_COLUMN_PCT
        other_col_pct = remaining_pct / (num_cols - 1) if num_cols > 1 else 100

        tpl_html = ["<table class='report-table'>"]

        # ----- Header -----
        tpl_html.append("<thead><tr>")
        for i, header in enumerate(headers):
            width = FIRST_COLUMN_PCT if i == 0 else other_col_pct
            tpl_html.append(f"<th style='width:{width}%'>{self._esc(header)}</th>")
        tpl_html.append("</tr></thead>")

        # ----- Body -----
        tpl_html.append("<tbody>")
        for row in rows:
            tpl_html.append("<tr>")
            for i, cell in enumerate(row):
                width = FIRST_COLUMN_PCT if i == 0 else other_col_pct
                tpl_html.append(f"<td style='width:{width}%'>{self._esc(cell)}</td>")
            tpl_html.append("</tr>")
        tpl_html.append("</tbody></table>")

        # Trusted HTML: the cell values above are already escaped via _esc
        return Markup("".join(tpl_html))


    def _expand_mds_rows(self, base_fields: dict, mds_sections: list[list[dict]]) -> list[dict]:
        """
        Expands multi-data-sections into cartesian-product rows

        Args:
            base_fields (dict): The object's normal fields (including public_id)
            mds_sections (list[list[dict]]): The MDS sections, each a list of row dicts

        Returns:
            list[dict]: The fully expanded row dicts (empty when any section is empty)
        """
        # No MDS -> single row
        if not mds_sections:
            return [base_fields]

        # Any empty section -> no rows
        for section in mds_sections:
            if not section:
                return []

        rows = []
        for combo in product(*mds_sections):
            row = dict(base_fields)
            for section_entry in combo:
                row.update(section_entry)
            rows.append(row)

        return rows


    def _expand_mds_columns(self, base_fields: dict, mds_sections: list[list[dict]]) -> dict:
        """
        Collapses multi-data-section values into stacked columns (one cell, ``<br>``-separated)

        Args:
            base_fields (dict): The object's normal fields (including public_id)
            mds_sections (list[list[dict]]): The MDS sections, each a list of row dicts

        Returns:
            dict: base_fields with each MDS field collapsed to a `Markup` of escaped, ``<br>``-joined
                values
        """
        result = dict(base_fields)
        collected: dict[str, list] = {}

        for section in mds_sections:
            for row in section:
                for field_name, value in row.items():
                    collected.setdefault(field_name, []).append(value)

        for field_name, values in collected.items():
            # Escape each value, keep the <br> separator as trusted markup
            result[field_name] = Markup("<br>").join("" if v is None else str(v) for v in values)

        return result


    def _report_uses_mds_fields(self, report: dict[str, Any], type_obj: dict[str, Any]) -> bool:
        """
        Reports whether any of the report's selected fields is a multi-data-section field

        Args:
            report (dict[str, Any]): The report definition
            type_obj (dict[str, Any]): The report's type

        Returns:
            bool: True if a selected field belongs to a multi-data-section
        """
        selected = set(report.get("selected_fields", []))

        render_meta: dict[str, Any] = type_obj.get("render_meta", {})
        sections: list[dict[str, Any]] = render_meta.get("sections", [])

        for section in sections:
            if section.get("type") != SectionType.MDS_SECTION:
                continue

            for field_name in section.get("fields", []):
                if field_name in selected:
                    return True

        return False
