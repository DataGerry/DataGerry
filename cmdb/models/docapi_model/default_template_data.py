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
Implementation of ObjectTemplateData
"""
import html
from logging import Logger, getLogger
import re
from typing import Any
from datetime import datetime
from itertools import product
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
from cmdb.models.docapi_model.object_template_data import ObjectTemplateData
from cmdb.models.docapi_model.safe_object import SafeObject
from cmdb.models.docapi_model.safe_dict import SafeDict
from cmdb.framework.rendering.cmdb_multi_render import CmdbMultiRender
from cmdb.models.docapi_model.relation_result import RelationResult
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

# -------------------------------------------------------------------------------------------------------------------- #
#                                              DefaultTemplateData - CLASS                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class DefaultTemplateData:
    """
    Class to process the template data for default templates
    """
    def __init__(
        self,
        cmdb_render_object,
        template_string: str,
        request_user,
        template_type
    ) -> None:
        """
        TODO: document
        """
        self.template_string = template_string
        self.request_user = request_user
        self.template_type = template_type

        self.objects_manager: ObjectsManager = ManagerProvider.get_manager(
            ManagerType.OBJECTS, request_user
        )
        self.types_manager: TypesManager = ManagerProvider.get_manager(
            ManagerType.TYPES, request_user
        )
        self.relations_manager: RelationsManager = ManagerProvider.get_manager(
            ManagerType.RELATIONS, request_user
        )
        self.object_relations_manager: ObjectRelationsManager = ManagerProvider.get_manager(
            ManagerType.OBJECT_RELATIONS, request_user
        )
        self.reports_manager: ReportsManager = ManagerProvider.get_manager(
            ManagerType.REPORTS, request_user
        )

        # Root object
        self.root_data = ObjectTemplateData(
            cmdb_render_object,
            self.objects_manager,
            self.request_user,
            self.template_type
        ).get_template_data()

        self.root_object_id = self.root_data["public_id"]

        # Parse template once
        self.external_object_ids = {
            int(m) for m in EXTERNAL_OBJECT_REGEX.findall(template_string)
        }

        self.report_ids = {
            int(m) for m in REPORT_REGEX.findall(template_string)
        }

        self.relation_placeholders = [
            m.group()
            for m in RELATION_PLACEHOLDER_REGEX.finditer(template_string)
        ]

        # Caches
        self.object_cache: dict[int, dict] = {}
        self.type_cache: dict[int, dict] = {}
        self.relation_cache: dict[int, dict] = {}
        self.object_relations: dict[dict] = []

        # Fetch objects
        object_ids = set(self.external_object_ids)
        object_ids.add(self.root_object_id)

        if object_ids:
            cursor = self.objects_manager.find(
                criteria={"public_id": {"$in": list(object_ids)}}
            )
            for obj in cursor:
                self.object_cache[obj["public_id"]] = obj

        # Fetch types
        type_ids = {
            obj["type_id"]
            for obj in self.object_cache.values()
            if obj.get("type_id")
        }

        if type_ids:
            cursor = self.types_manager.find(
                criteria={"public_id": {"$in": list(type_ids)}}
            )
            for t in cursor:
                self.type_cache[t["public_id"]] = t

        # Fetch relations + object relations
        relation_ids = set()

        for placeholder in self.relation_placeholders:
            for rel_id, _, _ in RELATION_STEP_REGEX.findall(placeholder):
                relation_ids.add(int(rel_id))

        self.all_object_relations: list[dict] = []  # global relation list

        if relation_ids:
            cursor = self.relations_manager.find(
                criteria={"public_id": {"$in": list(relation_ids)}}
            )
            for r in cursor:
                self.relation_cache[r["public_id"]] = r

            cursor = self.object_relations_manager.find(
                criteria={"relation_id": {"$in": list(relation_ids)}}
            )
            # store global list separately
            self.all_object_relations = list(cursor)

        # Keep self.object_relations for first-hop scoped traversal
        self.object_relations = list(self.all_object_relations)

        # Final template data
        self.template_data: dict[str, Any] = {
            "root": self._root_accessor(),
            "object": self._object_accessor(),
            "report": self._report_accessor(),
        }


    def get_template_data(self) -> dict[str, Any]:
        """
        Returns the template_data
        """
        return self.template_data


    def _root_accessor(self):
        root = dict(self.root_data)
        root["relation"] = self._relation_accessor(self.root_object_id)

        return root


    def _relation_accessor(self, start_object_id: int):
        def _relation_fn(relation_id: int, side: str) -> RelationResult:
            return self._relation_traversal(
                start_object_id,
                relation_id,
                side
            )

        return _relation_fn


    def _relation_traversal(
        self,
        start_object_id: int,
        relation_id: int,
        side: str,
    ) -> RelationResult:
        matches = []

        # Find objects for this hop
        for rel in self.object_relations:  # still use scoped here
            if rel["relation_id"] != relation_id:
                continue

            if side == "parent" and rel["relation_child_id"] == start_object_id:
                matches.append(rel["relation_parent_id"])
            elif side == "child" and rel["relation_parent_id"] == start_object_id:
                matches.append(rel["relation_child_id"])

        # Cache objects & types (unchanged)
        missing_ids = [oid for oid in matches if oid not in self.object_cache]
        if missing_ids:
            cursor = self.objects_manager.find(criteria={"public_id": {"$in": missing_ids}})
            for obj in cursor:
                self.object_cache[obj["public_id"]] = obj

        missing_type_ids = {
            obj["type_id"]
            for obj in self.object_cache.values()
            if obj.get("type_id") and obj["type_id"] not in self.type_cache
        }
        if missing_type_ids:
            cursor = self.types_manager.find(criteria={"public_id": {"$in": list(missing_type_ids)}})
            for t in cursor:
                self.type_cache[t["public_id"]] = t

        # Build scoped relations for relation_fields
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
            scoped_relations,          # scoped for relation_fields
            self.all_object_relations, # global for multi-hop traversal
            self.request_user,
            self.objects_manager,
            self.template_type
        )


    # External object accessor
    def _object_accessor(self):
        def _object_fn(public_id: int):
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

            return self._safe_wrap(result)

        return _object_fn


    def _report_accessor(self):
        def _report_fn(public_id: int):
            if public_id not in self.report_ids:
                return None

            report = self.reports_manager.get_item(public_id, as_dict=True)
            if not report:
                return None

            # Run report query
            query_str = report["report_query"]["data"]

            # The stored query is the repr of a Python dict; normalise the datetime calls and eval in
            # a locked-down namespace (only 'datetime', no builtins) so it cannot reach arbitrary code
            safe_globals = {"datetime": datetime, "__builtins__": {}}
            # pylint: disable=W0123
            report_query = eval(query_str.replace("datetime.datetime", "datetime"), safe_globals)

            objects = []

            if report_query:
                builder_params = BuilderParameters(criteria=report_query)
                objects = self.objects_manager.iterate(builder_params).results

            # Build label map for headers
            field_label_map = {}
            type_id = report.get("type_id")
            type_obj = None

            if type_id:
                type_obj = self.types_manager.get_type(type_id)

                for field in type_obj.get("fields", []):
                    field_label_map[field["name"]] = field.get("label", field["name"])

                for section in type_obj.get("multi_data_sections", []):
                    for field in section.get("fields", []):
                        field_label_map[field["name"]] = field.get("label", field["name"])

            # Build headers
            headers = ["Public ID"]
            for field_id in report.get("selected_fields", []):
                headers.append(field_label_map.get(field_id, field_id))

            rows = []

            # determine ONCE if we need MDS expansion
            use_mds = False
            if type_obj and report.get("mds_mode", "ROWS") == "ROWS":
                use_mds = self._report_uses_mds_fields(report, type_obj)

            for obj in objects:
                # Base fields
                base_fields = {
                    "public_id": obj.public_id
                }

                for field in obj.fields:
                    base_fields[field["name"]] = field.get("value")

                # Extract MDS sections
                mds_sections = []

                for section in obj.multi_data_sections:
                    section_rows = []

                    for entry in section.get("values", []):
                        row_data = {}
                        for field in entry.get("data", []):
                            row_data[field["name"]] = field.get("value")
                        section_rows.append(row_data)

                    mds_sections.append(section_rows)

                mds_mode = report.get("mds_mode", "ROWS")

                if mds_mode == "COLUMNS":
                    expanded = self._expand_mds_columns(
                        base_fields,
                        mds_sections
                    )

                    row = [str(expanded.get("public_id", ""))]
                    for field_id in report.get("selected_fields", []):
                        val = expanded.get(field_id, "")
                        row.append("" if val is None else str(val))

                    rows.append(row)

                else:
                    # Only expand if report actually uses MDS fields
                    if use_mds:
                        expanded_rows = self._expand_mds_rows(
                            base_fields,
                            mds_sections
                        )
                    else:
                        expanded_rows = [base_fields]   # no cartesian product

                    for expanded in expanded_rows:
                        row = [str(expanded.get("public_id", ""))]
                        for field_id in report.get("selected_fields", []):
                            val = expanded.get(field_id, "")
                            row.append("" if val is None else str(val))

                        rows.append(row)

            # Render table
            return self._build_report_table(headers, rows)

        return _report_fn

# ------------------------------------------------------ HELPERS ----------------------------------------------------- #

    def _get_field_label_map(self, type_id) -> dict:
        """TODO: document"""
        obj_type = self.types_manager.get_type(type_id)

        label_map = {}
        for field in obj_type.get("fields", []):
            label_map[field["id"]] = field.get("label", field["id"])

        return label_map


    def _esc(self, value: Any) -> str:
        """
        Method to escape HTML input
        """
        return html.escape("" if value is None else str(value))


    def _build_report_table(self, headers, rows):
        """
        Builds an HTML table that renders correctly in xhtml2pdf (PDF output)

        - Forces column widths inline (xhtml2pdf ignores most CSS layout rules)
        - First column is narrow (Public ID)
        - Remaining columns share the rest of the width evenly
        """
        # Column Width Calculation
        num_cols: int = len(headers)
        if num_cols < 1:
            return ""

        first_col_pct = 10  # % width for first column
        remaining_pct = 100 - first_col_pct

        if num_cols > 1:
            other_col_pct = remaining_pct / (num_cols - 1)
        else:
            other_col_pct = 100

        tpl_html = []
        tpl_html.append("<table class='report-table'>")

        # ----- Header -----
        tpl_html.append("<thead><tr>")
        for i, h in enumerate(headers):
            if i == 0:
                tpl_html.append(
                    f"<th style='width:{first_col_pct}%'>{h}</th>"
                )
            else:
                tpl_html.append(
                    f"<th style='width:{other_col_pct}%'>{h}</th>"
                )
        tpl_html.append("</tr></thead>")

        # ----- Body -----
        tpl_html.append("<tbody>")
        for row in rows:
            tpl_html.append("<tr>")
            for i, cell in enumerate(row):
                safe = "" if cell is None else str(cell)

                if i == 0:
                    tpl_html.append(
                        f"<td style='width:{first_col_pct}%'>{safe}</td>"
                    )
                else:
                    tpl_html.append(
                        f"<td style='width:{other_col_pct}%'>{safe}</td>"
                    )
            tpl_html.append("</tr>")
        tpl_html.append("</tbody></table>")

        return "".join(tpl_html)


    def _expand_mds_rows(self, base_fields: dict, mds_sections: list[dict]) -> list[dict]:
        """
        Expands multi data sections into cartesian product rows.

        Args:
            base_fields: dict of normal object fields (including public_id)
            mds_sections: list of MDS sections, each section is a list of row dicts

        Returns:
            List of fully expanded row dicts
        """
        # No MDS → single row
        if not mds_sections:
            return [base_fields]

        # If any section is empty → no rows
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


    def _expand_mds_columns(self, base_fields, mds_sections: list[dict[str, Any]]):
        """
        Collapse MDS values into stacked columns
        """
        result = dict(base_fields)
        collected = {}

        for section in mds_sections:
            for row in section:
                for field_name, value in row.items():
                    collected.setdefault(field_name, []).append(value)

        for field_name, values in collected.items():
            result[field_name] = "<br>".join(
                "" if v is None else str(v) for v in values
            )

        return result


    def _report_uses_mds_fields(self, report: dict[str, Any], type_obj: dict[str, Any]) -> bool:
        """
        TODO: document
        """
        selected = set(report.get("selected_fields", []))

        render_meta: dict[str, Any] = type_obj.get("render_meta", {})
        sections: list[dict[str, Any]] = render_meta.get("sections", [])

        for section in sections:
            if section.get("type") != "multi-data-section":
                continue

            for field_name in section.get("fields", []):
                if field_name in selected:
                    return True

        return False


    def _safe_wrap(self, data):
        if isinstance(data, dict):
            return SafeDict({k: self._safe_wrap(v) for k, v in data.items()})
        if isinstance(data, list):
            return [self._safe_wrap(v) for v in data]
        return data
