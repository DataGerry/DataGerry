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
Object rendering: turns stored CmdbObjects into the RenderResults every reader of an object uses

`CmdbMultiRender` is the renderer, `RenderResult` what it answers, `RenderProblemLog` how a render
records what it could not build, and `render_constants` the keys and codes all three share. Import from
the modules themselves; this package re-exports nothing
"""
