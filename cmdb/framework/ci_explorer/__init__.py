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
CI Explorer feature for DataGerry

Builds the node/edge payload for the CI Explorer graph view, blending three independent
data sources: the CmdbObjectRelation graph, the dg_location hierarchy (with inverted
parent/child semantics), and CmdbType metadata (label, color, icon, schema).

Modules:
  - argparsing: pure validators and parsers for the query-string arguments accepted by
      the /ci_explorer/items route (target_id, target_type, flags, filters, item_limit)
  - relations: object-relation Mongo criteria building, fetch, direction-aware splitting
  - enrichment: batched ref-field and dg_location flattening (one $in query per source,
      shared by root + linked-object + location-grafted nodes)
  - nodes: title resolution, type_info shaping, single node composer used everywhere
  - edges: edge composers for relation edges (with metadata) and location edges (bare)
  - locations: dg_location grafting (one hop up + one hop down), with consistent
      item_limit and types_filter accounting
  - graph: top-level build_ci_explorer_graph orchestrator (single entry point used by
      the /ci_explorer/items route)
"""
