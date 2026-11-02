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
Constants shared by the schema helpers of cmdb.class_schema

Names of Cerberus rules the helpers read or rewrite, so a helper never compares against a bare rule string
"""
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'DEFAULT_RULE',
]

# The Cerberus rule that fills a value into the validated document when the key is absent
DEFAULT_RULE: str = 'default'
