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
TODO: document
"""
# -------------------------------------------------------------------------------------------------------------------- #

# -------------------------------------------------------------------------------------------------------------------- #
#                                               AggregatedFields - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class AggregatedFields:
    """
    TODO: document
    """
    def __init__(self, field_dicts: list[dict]) -> None:
        self._field_dicts = field_dicts


    def __getitem__(self, field_name: str) -> str:
        values = []

        for d in self._field_dicts:
            val = d.get(field_name)
            if val is None or val == "":
                continue
            values.append(str(val))

        return ", ".join(values)
