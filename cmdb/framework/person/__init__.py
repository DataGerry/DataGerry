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
The Persons feature: the PERSON / PERSON_GROUP SpecialTypes and the person field (FieldType.PERSON)

* ``person_values`` - pure helpers for the value a person field stores
* ``enforcement`` - the person invariants on the CmdbObject write path
* ``directory`` - reads persons and groups as the ISMS module and the person routes see them
"""
