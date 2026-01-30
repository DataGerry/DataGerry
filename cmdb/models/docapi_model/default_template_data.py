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
from cmdb.models.type_model import CmdbType
from cmdb.framework.rendering.cmdb_render import CmdbRender
from cmdb.models.docapi_model.relation_result import RelationResult
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

DATETIME_PATTERN = r"datetime\.datetime\((.*?)\)"

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

TERMINAL_REGEX = re.compile(
    r"""
    \.(fields|relation_field)\[['"](.+?)['"]\]
    |\.public_id
    """,
    re.VERBOSE,
)

# -------------------------------------------------------------------------------------------------------------------- #
#                                              DefaultTemplateData - CLASS                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class DefaultTemplateData:
    """
    FINAL stable DEFAULT template data builder.
    """

    # ------------------------------------------------------------------
    # Init
    # ------------------------------------------------------------------

    def __init__(
        self,
        cmdb_render_object,
        template_string: str,
        request_user,
        template_type
    ) -> None:
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

        # --------------------------------------------------------------
        # Parse template once
        # --------------------------------------------------------------
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

        # LOGGER.debug(f"self.relation_placeholders: {self.relation_placeholders}")

        # --------------------------------------------------------------
        # Caches
        # --------------------------------------------------------------
        self.object_cache: dict[int, dict] = {}
        self.type_cache: dict[int, dict] = {}
        self.relation_cache: dict[int, dict] = {}
        self.object_relations: dict[dict] = []

        # --------------------------------------------------------------
        # Fetch objects
        # --------------------------------------------------------------
        object_ids = set(self.external_object_ids)
        object_ids.add(self.root_object_id)

        if object_ids:
            cursor = self.objects_manager.find(
                criteria={"public_id": {"$in": list(object_ids)}}
            )
            for obj in cursor:
                self.object_cache[obj["public_id"]] = obj

        # --------------------------------------------------------------
        # Fetch types
        # --------------------------------------------------------------
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

        # --------------------------------------------------------------
        # Fetch relations + object relations
        # --------------------------------------------------------------
        relation_ids = set()

        for placeholder in self.relation_placeholders:
            for rel_id, _, _ in RELATION_STEP_REGEX.findall(placeholder):
                relation_ids.add(int(rel_id))

        # LOGGER.debug(f"relation_ids: {relation_ids}")

        if relation_ids:
            cursor = self.relations_manager.find(
                criteria={"public_id": {"$in": list(relation_ids)}}
            )
            for r in cursor:
                self.relation_cache[r["public_id"]] = r

            cursor = self.object_relations_manager.find(
                criteria={"relation_id": {"$in": list(relation_ids)}}
            )
            self.object_relations = list(cursor)

        # LOGGER.debug(f"self.object_relations: {self.object_relations}")

        # Final template data
        self.template_data = {
            "root": self._root_accessor(),
            "object": self._object_accessor(),
            "report": self._report_accessor(),
        }

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def get_template_data(self) -> dict[str, Any]:
        """TODO: document"""
        return self.template_data

    # ------------------------------------------------------------------
    # Root accessor (relations start here)
    # ------------------------------------------------------------------

    def _root_accessor(self):
        root = dict(self.root_data)
        root["relation"] = self._relation_accessor(self.root_object_id)
        return root

    # ------------------------------------------------------------------
    # Relation traversal engine
    # ------------------------------------------------------------------

    def _relation_accessor(self, start_object_id: int):
        def _relation_fn(relation_id: int, side: str):
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
    ):
        matches = []

        for rel in self.object_relations:
            if rel["relation_id"] != relation_id:
                continue

            if side == "parent" and rel["relation_child_id"] == start_object_id:
                matches.append(rel["relation_parent_id"])
            elif side == "child" and rel["relation_parent_id"] == start_object_id:
                matches.append(rel["relation_child_id"])

        # ------------------------------------------------------------------
        # Ensure related objects are cached
        # ------------------------------------------------------------------
        missing_ids = [
            oid for oid in matches
            if oid not in self.object_cache
        ]

        if missing_ids:
            cursor = self.objects_manager.find(
                criteria={"public_id": {"$in": missing_ids}}
            )
            for obj in cursor:
                self.object_cache[obj["public_id"]] = obj

        # ------------------------------------------------------------------
        # Ensure related object TYPES are cached
        # ------------------------------------------------------------------
        missing_type_ids = {
            obj["type_id"]
            for obj in self.object_cache.values()
            if obj.get("type_id") and obj["type_id"] not in self.type_cache
        }

        if missing_type_ids:
            cursor = self.types_manager.find(
                criteria={"public_id": {"$in": list(missing_type_ids)}}
            )
            for t in cursor:
                self.type_cache[t["public_id"]] = t

        return RelationResult(
            matches,
            self.object_cache,
            self.type_cache,
            self.object_relations,
            self.request_user,
            self.objects_manager,
            self.template_type
        )

    # ------------------------------------------------------------------
    # External object accessor
    # ------------------------------------------------------------------

    def _object_accessor(self):
        def _object_fn(public_id: int):
            obj = self.object_cache.get(public_id)
            if not obj:
                return None

            cmdb_object = CmdbObject.from_data(obj)
            obj_type = self.type_cache.get(cmdb_object.get_type_id())
            if not obj_type:
                return None

            render = CmdbRender(
                cmdb_object,
                CmdbType.from_data(obj_type),
                self.request_user,
                False,
            )

            return ObjectTemplateData(
                render.result(),
                self.objects_manager,
                self.request_user,
                self.template_type
            ).get_template_data()

        return _object_fn


    def _report_accessor(self):
        def _report_fn(public_id: int):
            if public_id not in self.report_ids:
                return None

            # --------------------------------------------------
            # Load report
            # --------------------------------------------------
            report = self.reports_manager.get_item(public_id, as_dict=True)
            if not report:
                return None

            # --------------------------------------------------
            # Run report query (copied from route)
            # --------------------------------------------------
            query_str = report["report_query"]["data"]

            processed_query_string = re.sub(
                DATETIME_PATTERN,
                self.replace_datetime,
                query_str.replace("datetime.datetime", "datetime"),
            )

            safe_globals = {"datetime": datetime}
            report_query = eval(processed_query_string, safe_globals)

            objects = []
            if report_query:
                builder_params = BuilderParameters(criteria=report_query)
                # objects = self.objects_manager.iterate(builder_params).results
                tmp_objects = self.objects_manager.iterate(builder_params).results
                objects = [object_.__dict__ for object_ in tmp_objects]
            # --------------------------------------------------
            # Build label map
            # --------------------------------------------------
            field_label_map = {}
            type_id = report.get("type_id")

            if type_id:
                obj_type = self.types_manager.get_type(type_id)
                for field in obj_type.get("fields", []):
                    field_label_map[field["name"]] = field.get("label", field["name"])

            # --------------------------------------------------
            # Build table
            # --------------------------------------------------
            headers = ["Public ID"]
            for field_id in report.get("selected_fields", []):
                headers.append(field_label_map.get(field_id, field_id))

            rows = []
            for obj in objects:
                row = [str(obj.get("public_id", ""))]

                # THIS IS THE CRITICAL FIX
                field_map = {
                    f.get("name"): f.get("value")
                    for f in obj.get("fields", [])
                    if f.get("name") is not None
                }

                for field_id in report.get("selected_fields", []):
                    value = field_map.get(field_id, "")
                    row.append("" if value is None else str(value))

                rows.append(row)

            return self._build_report_table(headers, rows)
            # return {
            #     "headers": headers,
            #     "rows": rows
            # }

        return _report_fn

# ------------------------------------------------------ HELPERS ----------------------------------------------------- #

    def _get_field_label_map(self, type_id) -> dict:
        """TODO: document"""
        obj_type = self.types_manager.get_type(type_id)

        label_map = {}
        for field in obj_type.get("fields", []):
            label_map[field["id"]] = field.get("label", field["id"])

        return label_map


    def _esc(self, value):
        """TODO: document"""
        return html.escape("" if value is None else str(value))


    def _build_report_table(self, headers, rows):
        """
        Builds an HTML table that renders correctly in xhtml2pdf (PDF output)

        - Forces column widths inline (xhtml2pdf ignores most CSS layout rules)
        - First column is narrow (Public ID)
        - Remaining columns share the rest of the width evenly
        """

        # ----- Column Width Calculation -----
        num_cols = len(headers)
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
    # def _build_report_table(self, headers, rows):
    #     """TODO: document"""
    #     style = """
    #     <style>
    #     .report-table {
    #         width: 100%;
    #         border-collapse: collapse;
    #         margin-top: 10px;
    #         table-layout: fixed;
    #     }

    #     .report-table th,
    #     .report-table td {
    #         border: 1px solid #444;
    #         padding: 4px;
    #         vertical-align: top;
    #     }

    #     .report-table th {
    #         background-color: #f0f0f0;
    #         font-weight: bold;
    #         text-align: left;
    #     }
    #     </style>
    #     """

    #     tpl_html = [style]
    #     tpl_html.append("<table class='report-table'>")

    #     # Header
    #     tpl_html.append("<thead><tr>")
    #     for h in headers:
    #         tpl_html.append(f"<th>{h}</th>")
    #     tpl_html.append("</tr></thead>")

    #     # Body
    #     tpl_html.append("<tbody>")
    #     for row in rows:
    #         tpl_html.append("<tr>")
    #         for cell in row:
    #             safe = "" if cell is None else str(cell)
    #             tpl_html.append(f"<td>{safe}</td>")
    #         tpl_html.append("</tr>")
    #     tpl_html.append("</tbody></table>")

    #     result = "".join(tpl_html)
    #     # LOGGER.debug(f"result: {result}")
    #     return result

    # def _build_report_table(self, headers, rows):
    #     """TODO: document"""
    #     style = """
    #     <style>
    #     .report-table {
    #         width: 100%;
    #         border-collapse: collapse;
    #         margin-top: 10px;
    #         table-layout: auto;
    #     }

    #     .report-table th,
    #     .report-table td {
    #         border: 1px solid #444;
    #         padding: 6px;
    #         font-size: 10pt;
    #         vertical-align: top;
    #         word-break: break-word;
    #         white-space: normal;
    #         min-width: 80px;
    #     }

    #     .report-table th {
    #         background-color: #f0f0f0;
    #         font-weight: bold;
    #         text-align: left;
    #     }

    #     /* Make first column smaller (Public ID) */
    #     .report-table th:first-child,
    #     .report-table td:first-child {
    #         min-width: 50px;
    #         width: 50px;
    #         text-align: center;
    #     }
    #     </style>
    #     """

    #     tpl_html = [style]
    #     tpl_html.append("<table class='report-table'>")

    #     # Header
    #     tpl_html.append("<thead><tr>")
    #     for h in headers:
    #         tpl_html.append(f"<th>{h}</th>")
    #     tpl_html.append("</tr></thead>")

    #     # Body
    #     tpl_html.append("<tbody>")
    #     for row in rows:
    #         tpl_html.append("<tr>")
    #         for cell in row:
    #             safe = "" if cell is None else str(cell)
    #             tpl_html.append(f"<td>{safe}</td>")
    #         tpl_html.append("</tr>")
    #     tpl_html.append("</tbody></table>")

    #     return "".join(tpl_html)


    def replace_datetime(self, match: re.Match) -> str:
        """
        Replaces a regex match containing datetime arguments with a Python datetime object

        Args:
            match (re.Match): A regular expression match object containing 
                            a string of datetime arguments (e.g., "2025, 11, 26, 0, 0").

        Returns:
            str: A string representation (repr) of the evaluated datetime object.

        Notes:
            - This function expects the match to contain arguments suitable for datetime().
            - The returned value is the repr of the datetime object, 
            which can be used in source code or serialization.
        """
        args = match.group(1)

        #pylint: disable=W0123
        return repr(eval(f"datetime({args})"))
