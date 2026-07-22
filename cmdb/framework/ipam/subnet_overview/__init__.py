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
Builds the data payloads for the SUBNET 'IP-Übersicht' view

The frontend renders KPI counters (total / used / free) plus a paginated, IP-sorted table
where each address of the subnet appears as either an 'assigned' or 'free' row. The package
splits the build into focused modules:
  - assigned_rows: subnet loading, assigned-row indexing, type-meta / summary-line lookups
  - candidates: candidate-IP selection (lazy slice, enumeration, search / sort / filter)
  - rows: wire-format row shaping and the paginated 'ips' block
  - distribution: the 'IP-Verteilung' heatmap grid and the type pie payloads
  - sectors: the single-sector drill-down behind the clickable heatmap
  - export_rows: the row provider for the subnet IPs Excel export
  - orchestrators: the top-level payload builders the routes call

Only the orchestrator-level builders below are part of the package's public API; route and
export modules import them from this package path
"""
from cmdb.framework.ipam.subnet_overview.candidates import (
    list_all_assignable_ips,
    list_assignable_ips_matching_substring,
)
from cmdb.framework.ipam.subnet_overview.export_rows import build_subnet_ip_export_rows
from cmdb.framework.ipam.subnet_overview.orchestrators import (
    build_invalid_ips_overview,
    build_subnet_overview,
)
from cmdb.framework.ipam.subnet_overview.sectors import build_subnet_sector_ips
# -------------------------------------------------------------------------------------------------------------------- #

__all__ = [
    'build_invalid_ips_overview',
    'build_subnet_ip_export_rows',
    'build_subnet_overview',
    'build_subnet_sector_ips',
    'list_all_assignable_ips',
    'list_assignable_ips_matching_substring',
]
