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
This module contains the implementation of the CiExplorerProfileManager
"""
from logging import Logger, getLogger

from cmdb.database import MongoDatabaseManager
from cmdb.manager.generic_manager import GenericManager

from cmdb.models.ci_explorer_model import CmdbCiExplorerProfile

from cmdb.errors.manager.ci_explorer_profile_manager import CI_EXPLORER_PROFILE_MANAGER_ERRORS
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                            CiExplorerProfileManager - CLASS                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class CiExplorerProfileManager(GenericManager):
    """
    The CiExplorerProfileManager manages the interaction between CiExplorer profiles and the database

    Extends: GenericManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str = None):
        super().__init__(dbm, CmdbCiExplorerProfile, CI_EXPLORER_PROFILE_MANAGER_ERRORS, database)
