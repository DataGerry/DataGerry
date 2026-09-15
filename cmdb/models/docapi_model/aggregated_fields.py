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
This module contains the AggregatedFields class used to expose relation-aggregated fields to templates.
"""
# -------------------------------------------------------------------------------------------------------------------- #

# -------------------------------------------------------------------------------------------------------------------- #
#                                               AggregatedFields - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class AggregatedFields:
    """
    Aggregates the same field across several objects (or relation edges) for template access.

    A RelationResult may cover many objects; indexing this container by a field name returns the
    non-empty values of that field across all of them, joined into a single comma-separated string.
    """
    def __init__(self, field_dicts: list[dict]) -> None:
        """
        Args:
            field_dicts (list[dict]): One name->value field mapping per object/edge to aggregate
        """
        self._field_dicts = field_dicts


    def __getitem__(self, field_name: str) -> str:
        """
        Returns the non-empty values of `field_name` across all aggregated dicts

        Args:
            field_name (str): The field to collect values for

        Returns:
            str: The values joined by ', ' (empty string when no dict carries a non-empty value)
        """
        values = []

        for d in self._field_dicts:
            val = d.get(field_name)
            if val is None or val == "":
                continue
            values.append(str(val))

        return ", ".join(values)
