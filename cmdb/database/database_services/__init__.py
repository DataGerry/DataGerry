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
This package provides all helper functions for database updates: the collection validator, the updater, and
bringing a database up to date (validate, then stamp or migrate)
"""
from .updater_helpers import get_db_names_from_service_portal
from .collection_validator import CollectionValidator
from .database_updater import DatabaseUpdater
from .database_bring_up import bring_database_up_to_date
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'get_db_names_from_service_portal',
    'CollectionValidator',
    'DatabaseUpdater',
    'bring_database_up_to_date',
]
