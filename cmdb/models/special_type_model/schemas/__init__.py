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
<<<<<<< HEAD
=======
"""
Predefined CmdbType schemas for the IPAM SpecialTypes

Each schema module exposes a get_<special_type>_schema() builder returning the ready-to-use
CmdbType schema dict (sections, fields, the 'special_type' marker) for one SpecialType;
SchemaProvider maps a SpecialType value to the matching builder for the special-type creation
route and the DataGerry assistant. cidr_regex holds the coarse field-level IP / CIDR
validation patterns shared by the SUBNET and SUPERNET schemas and the dg-ipam-interface
section template
"""
>>>>>>> origin/version-3.2
