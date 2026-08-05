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
This module provide all available Response classes for the API routes
"""
from .base_api_response import BaseAPIResponse
from .delete_single_response import DeleteSingleResponse
from .get_list_response import GetListResponse
from .get_multi_response import GetMultiResponse
from .get_single_response import GetSingleResponse
from .default_response import DefaultResponse
from .insert_single_response import InsertSingleResponse
from .update_single_response import UpdateSingleResponse
from .update_multi_response import UpdateMultiResponse
from .login_response import LoginResponse
from .gridfs_response import GridFsResponse
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'BaseAPIResponse',
    'DeleteSingleResponse',
    'GetListResponse',
    'GetMultiResponse',
    'GetSingleResponse',
    'DefaultResponse',
    'InsertSingleResponse',
    'UpdateSingleResponse',
    'UpdateMultiResponse',
    'LoginResponse',
    'GridFsResponse',
]
