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
This package contains all errors for DataGerry

Every class here is raised, caught or extended somewhere in ``cmdb/``: a change that stops raising an error deletes
the class, its re-export and any error-map entry naming it in the same change. A wrapped error carries the exception
it wraps - ``raise XxxError(err) from err``, never ``XxxError(str(err))``
"""
