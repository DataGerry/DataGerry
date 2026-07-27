# DataGerry - OpenSource Enterprise CMDB
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
Export engine for CmdbObjects (framework layer)

Holds the export configuration (`config/`), the per-format serializers (`format/`), the writer that
drives them (`writer/`), the shared constants and the exported-file naming helper. The CmdbType export
is NOT part of this engine - it is a standalone JSON serialization in the exporter route helper, and
only borrows the filename timestamp from here
"""
