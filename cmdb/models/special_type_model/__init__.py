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
SpecialTypes: the CmdbType flavours that carry framework-level behaviour

A CmdbType marks itself as a SpecialType through its schema's 'special_type' key and is then created
from a predefined blueprint under the 'schemas' subpackage. The members are grouped by the feature
that owns them - SUPERNET / SUBNET / VLAN belong to IPAM (their field names live in ipam_constants),
RACK to the Rack View feature (rack_constants) and CABLE to Port Connectivity (cable_constants) - and
each may exist at most once per installation
"""
