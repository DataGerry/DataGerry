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
Implementation of different configuration classes for the Flask App
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #

class Config:
    """
    Parent configuration class
    """
    TESTING = False
    DEBUG = False
    ENV = 'production'
    APPLICATION_ROOT = '/rest/'


class DevelopmentConfig(Config):
    """
    Configurations for Development
    """
    DEBUG = True
    ENV = 'development'


class ProductionConfig(Config):
    """
    Configurations for Production
    """
    DEBUG = False
    TESTING = False
    ENV = 'production'


class TestingConfig(Config):
    """
    Configurations for Testing
    """
    DEBUG = True
    TESTING = True
    ENV = 'testing'


app_config: dict[str, Any] = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig
}
