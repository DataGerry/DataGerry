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
REST API routes for the CmdbExtendableOption domain

Gathers everything backing the ``/rest/extendable_options`` endpoints in one place, mirroring the
``cmdb_categories`` / ``cmdb_types`` route packages:

    extendable_option_routes.py     ``extendable_option_blueprint`` - the CmdbExtendableOption CRUD endpoints
    extendable_options_constants.py ACL rights + request/document keys + referencing-collection field names
    extendable_options_helper.py    ``is_extendable_option_used`` - the in-use guard run before deletion

The CRUD handlers delegate their domain logic to ``ExtendableOptionsManager``; the deletion in-use
check lives in the helper so it stays unit-testable.
"""
from cmdb.interface.rest_api.routes.framework_routes.cmdb_extendable_options.extendable_option_routes import (
    extendable_option_blueprint,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'extendable_option_blueprint',
]
