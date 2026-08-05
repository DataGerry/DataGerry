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
Unit tests for the cmdb.security.license package

Pure tests for the license feature's foundational parts: the shipped crypto material and
constants (P1), the machine fingerprint util (P3) and the dev key generator (P0). The enum
value-contracts are pinned centrally in tests/unit/test_str_enum_value_contracts.py; these
modules cover behaviour. No Mongo, no Flask
"""
