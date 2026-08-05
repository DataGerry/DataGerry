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
Constants used by the query builder package

Currently scoped to the fields-array sort pipeline in BaseQueryBuilder, which projects the
matched element's value into a temporary key so MongoDB can sort on it. Both the inbound
sort-key prefix and the temporary-field name live here so callers and tests can reference
them without re-spelling the literals
"""
# -------------------------------------------------------------------------------------------------------------------- #


class SortPipeline:
    """
    Constants for the ``fields.<name>`` sort pipeline used by BaseQueryBuilder

    Attributes:
        FIELDS_PREFIX (str): Prefix on a sort key that targets a value inside the ``fields`` array;
            the suffix after this prefix is the field ``name`` to match against
        TEMP_KEY (str): Name of the temporary aggregation field that holds the extracted value
            being sorted on; projected away before the documents are returned
    """
    FIELDS_PREFIX: str = 'fields.'
    TEMP_KEY: str = '_sort_value'
