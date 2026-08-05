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
This module prove all API Response parameters for ISMS
"""
from .api_parameters import APIParameters
from .collection_parameters import CollectionParameters
from .group_parameters import GroupDeletionParameters
from .type_parameters import TypeIterationParameters
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'APIParameters',
    'CollectionParameters',
    'GroupDeletionParameters',
    'TypeIterationParameters',
]
