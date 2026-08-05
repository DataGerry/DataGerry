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
Versioned database updates

Each updater_<YYYYMMDD> module implements one BaseDatabaseUpdate subclass whose creation_date is the
encoded date. Note: these modules are not auto-discovered by PyInstaller - a new updater must be
added as a --hidden-import in the Makefile's 'bin' target (see CLAUDE.md).
"""
