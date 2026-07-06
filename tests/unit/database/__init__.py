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
Unit tests for the cmdb.database package (top-level modules)

Scope is the pure, side-effect-free logic: the BSON<->JSON codec and retry decorator in
database_utils, and the query-construction logic in mongo_query_builder. The pymongo I/O wrappers
in mongo_database_manager / mongo_connector are exercised by the integration and functional suites
(they need a live MongoDB), and methods with known open issues are deliberately left untested.
"""
