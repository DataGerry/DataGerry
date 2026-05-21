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
IP Address Management (IPAM) feature for DataGerry

Provides the validators, overview builders, and shared CIDR helpers behind the IPAM
SpecialTypes (SUPERNET, SUBNET, VLAN) and the dg-ipam-interface MDS section template.
Modules:
  - cidr: pure IPv4 helpers (parsing, containment, address-count policy)
  - pagination: page/page_size clamping shared by the overview routes
  - references: SpecialType id resolution
  - subnet_validator / interface_validator / vlan_validator: structured per-row
      validation invoked at save time and from the inline pre-validation REST routes
  - range_change_guards: guards against subnet/supernet range edits that would orphan
      child rows
  - enforcement: cross-row enforcement helpers used by the validator orchestrators
  - subnet_overview / supernet_overview: payload builders for the IPAM overview views
  - supernet_membership: write-side mutations against the SUBNET <-> SUPERNET relation
      (currently the batch 'unassign subnets from supernet' flow used by the overview)

Prefix-policy constants and field/section name enums are imported from
cmdb.models.special_type_model.ipam_constants
"""
