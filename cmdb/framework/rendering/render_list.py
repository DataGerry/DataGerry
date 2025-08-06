# DATAGERRY - OpenSource Enterprise CMDB
# Copyright (C) 2025 becon GmbH
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
Implementation of RenderList
"""
from logging import getLogger

from cmdb.manager import ObjectsManager

from cmdb.models.object_model import CmdbObject
from cmdb.models.user_model import CmdbUser
from cmdb.framework.rendering.render_result import RenderResult
from cmdb.framework.rendering.cmdb_render import CmdbRender
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  RenderList - CLASS                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class RenderList:
    """
    A class responsible for rendering a list of CmdbObjects
    """
    def __init__(self,
                 object_list: list[CmdbObject],
                 request_user: CmdbUser,
                 ref_render: bool = False,
                 objects_manager: ObjectsManager = None):
        """
        Initializes a RenderList

        Args:
            object_list (list[CmdbObject]): The list of CmdbObjects
            request_user (CmdbUser): The user making the request
            ref_render (bool, optional): Enables reference rendering. Defaults to False
            objects_manager (ObjectsManager | None, optional): Manager for handling CmdbObjects. Defaults to None
        """
        self.object_list = object_list
        self.request_user = request_user
        self.ref_render = ref_render
        self.objects_manager = objects_manager


    def render_result_list(self, raw: bool = False) -> list[RenderResult | dict]:
        """
        Renders the list of CmdbObjects and returns the processed results

        Args:
            raw (bool, optional): If True, returns raw dictionary representations. Defaults to False

        Returns:
            list[RenderResult | dict]: A list of rendered results, either as RenderResult objects or dictionaries
        """
        preparation_objects: list[RenderResult] = []

        for passed_object in self.object_list:
            tmp_render = CmdbRender(passed_object,
                                    self.objects_manager.get_object_type(passed_object.type_id),
                                    self.request_user,
                                    self.ref_render)

            current_render_result = tmp_render.result()
            preparation_objects.append(current_render_result.__dict__ if raw else current_render_result)

        return preparation_objects
