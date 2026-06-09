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
Query-string constants used by the SpecialType REST routes

Names the query-string parameters the SpecialType endpoints read, so the routes reference the
literal strings from one place instead of repeating them (mirrors ``CATEGORY_VIEW_PARAM`` for the
category routes).
"""
# -------------------------------------------------------------------------------------------------------------------- #

# Name of the ?special_type= query parameter naming the SpecialType to act on
SPECIAL_TYPE_PARAM: str = 'special_type'

# Name of the ?available= query parameter that, when true, limits the result to unused SpecialTypes
AVAILABLE_PARAM: str = 'available'
