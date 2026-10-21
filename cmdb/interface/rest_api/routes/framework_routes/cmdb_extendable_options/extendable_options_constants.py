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

Holds the ACL rights each endpoint guards on. The document keys moved to
``cmdb.models.extendable_option_model.extendable_option_constants`` (ExtendableOptionKey) and the
referencing-collection field names to ``cmdb.framework.extendable_options`` - both are shared with
the predefined-data factories and the database updaters, so neither can be owned by the REST layer.
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #


class ExtendableOptionRight(BaseStrEnum):
    """Per-endpoint ACL rights checked by the CmdbExtendableOption route ``protect`` decorators."""
    ADD = 'base.framework.extendableOption.add'
    VIEW = 'base.framework.extendableOption.view'
    EDIT = 'base.framework.extendableOption.edit'
    DELETE = 'base.framework.extendableOption.delete'
