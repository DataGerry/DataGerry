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
Cross-domain knowledge about CmdbExtendableOptions

Holds the single map of which collections reference an option by public_id, plus the in-use check
and the reference re-pointing built on it. Consumed by the CmdbExtendableOption REST helper and by
the de-duplication updater
"""
from .extendable_option_references import (
    ExtendableOptionUsageField,
    ExtendableOptionReference,
    EXTENDABLE_OPTION_REFERENCES,
    get_option_references,
    is_option_referenced,
    repoint_option_references,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'ExtendableOptionUsageField',
    'ExtendableOptionReference',
    'EXTENDABLE_OPTION_REFERENCES',
    'get_option_references',
    'is_option_referenced',
    'repoint_option_references',
]
