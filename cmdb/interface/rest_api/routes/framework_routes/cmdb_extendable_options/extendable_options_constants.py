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
Constants used by the CmdbExtendableOption REST routes

Centralises the ACL rights each endpoint guards on, the request/document keys the routes read, and
the field names on the referencing collections that the deletion in-use check queries - so the
routes and helper carry no bare string literals.
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #


class ExtendableOptionRight(BaseStrEnum):
    """Per-endpoint ACL rights checked by the CmdbExtendableOption route ``protect`` decorators."""
    ADD = 'base.framework.extendableOption.add'
    VIEW = 'base.framework.extendableOption.view'
    EDIT = 'base.framework.extendableOption.edit'
    DELETE = 'base.framework.extendableOption.delete'


class ExtendableOptionKey(BaseStrEnum):
    """Request-body / document keys of a CmdbExtendableOption."""
    PUBLIC_ID = 'public_id'
    VALUE = 'value'
    OPTION_TYPE = 'option_type'
    PREDEFINED = 'predefined'


class ExtendableOptionUsageField(BaseStrEnum):
    """
    Field names on the referencing collections that point at a CmdbExtendableOption public_id

    Queried by ``is_extendable_option_used`` to decide whether an option may be deleted
    """
    SOURCE = 'source'                                # threats / vulnerabilities / control measures
    CATEGORIES = 'categories'                        # object groups
    IMPLEMENTATION_STATE = 'implementation_state'    # control measures
    IMPLEMENTATION_STATUS = 'implementation_status'  # risk assessments / control-measure assignments
    CATEGORY_ID = 'category_id'                      # risks
