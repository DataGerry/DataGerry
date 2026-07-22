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
Unit tests for the cmdb.framework.ipam.subnet_overview package

Each test module here mirrors a single source module of the subnet_overview package:
test_assigned_rows, test_candidates, test_rows, test_distribution, test_sectors,
test_export_rows and test_orchestrators. Tests are pure (no Mongo, no Flask app context):
DB managers are MagicMock-ed, internal collaborators are patched at the module path where the
name is USED, and Flask aborts surface as werkzeug HTTPExceptions
"""
