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
This module defines pytest fixtures for rights management, user groups, and user access levels.
"""
import logging
from datetime import datetime
import pytest

from cmdb.manager import RightsManager

from cmdb.models.user_model import CmdbUser
from cmdb.models.group_model import CmdbUserGroup
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
@pytest.fixture(scope="session", name="rights_manager")
def fixture_rights_manager():
    """
    Provides an instance of RightsManager with all available rights.
    
    Returns:
        RightsManager: An instance managing all rights.
    """
    return RightsManager()


@pytest.fixture(scope="session", name="full_access_group")
def fixture_full_access_group(rights_manager: RightsManager):
    """
    Creates a user group with full access rights.
    
    Args:
        rights_manager (RightsManager): The rights manager instance.
    
    Returns:
        CmdbUserGroup: A user group with full access rights.
    """
    return CmdbUserGroup(public_id=1, name='full', label='Full', rights=[rights_manager.get_right('base.*')])


@pytest.fixture(scope="session", name="none_access_group")
def fixture_none_access_group():
    """
    Creates a user group with no access rights.
    
    Returns:
        CmdbUserGroup: A user group with no assigned rights.
    """
    return CmdbUserGroup(public_id=2, name='none', label='None')


@pytest.fixture(scope="session", name="full_access_user")
def fixture_full_access_user(full_access_group: CmdbUserGroup):
    """
    Creates a user with full access rights.
    
    Args:
        full_access_group (CmdbUserGroup): The full access user group.
    
    Returns:
        CmdbUser: A user with full access rights.
    """
    registration_time = datetime.now()
    return CmdbUser(public_id=1,
                     user_name='full-access-user',
                     active=True,
                     group_id=full_access_group.public_id,
                     registration_time=registration_time)


@pytest.fixture(scope="session", name="none_access_user")
def fixture_none_access_user(none_access_group: CmdbUserGroup):
    """
    Creates a user with no access rights.
    
    Args:
        none_access_group (CmdbUserGroup): The no access user group.
    
    Returns:
        CmdbUser: A user with no access rights.
    """
    registration_time = datetime.now()
    return CmdbUser(public_id=2,
                     user_name='none-access-user',
                     active=True,
                     group_id=none_access_group.public_id,
                     registration_time=registration_time)
