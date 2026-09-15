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
Implementation of base classes of rights for the Framework section used in Datagerry
"""
from cmdb.models.right_model.base_right import BaseRight
from cmdb.models.right_model.levels_enum import Levels
# -------------------------------------------------------------------------------------------------------------------- #

class FrameworkRight(BaseRight):
    """
    Base class for general Framework rights
    """
    MIN_LEVEL = Levels.PERMISSION
    PREFIX = f'{BaseRight.PREFIX}.framework'

    def __init__(self, name: str, level: Levels = MIN_LEVEL, description: str = None):
        super().__init__(level, name, description=description)


class ObjectRight(FrameworkRight):
    """
    Base class for CmdbObject rights
    """
    MIN_LEVEL = Levels.PERMISSION
    MAX_LEVEL = Levels.SECURE
    PREFIX = f'{FrameworkRight.PREFIX}.object'

    def __init__(self, name: str, level: Levels = MIN_LEVEL, description: str = None):
        super().__init__(name, level, description=description)


class SectionTemplateRight(FrameworkRight):
    """
    Base class for CmdbSectionTemplate rights
    """
    MIN_LEVEL = Levels.PERMISSION
    MAX_LEVEL = Levels.SECURE
    PREFIX = f'{FrameworkRight.PREFIX}.sectionTemplate'

    def __init__(self, name: str, level: Levels = MIN_LEVEL, description: str = None):
        super().__init__(name, level, description=description)


class TypeRight(FrameworkRight):
    """
    Base class for CmdbType rights
    """
    MIN_LEVEL = Levels.PROTECTED
    MAX_LEVEL = Levels.CRITICAL
    PREFIX = f'{FrameworkRight.PREFIX}.type'

    def __init__(self, name: str, level: Levels = Levels.SECURE, description: str = None):
        super().__init__(name, level, description=description)


class CategoryRight(FrameworkRight):
    """
    Base class for CmdbCategory rights
    """
    MIN_LEVEL = Levels.PROTECTED
    MAX_LEVEL = Levels.SECURE
    PREFIX = f'{FrameworkRight.PREFIX}.category'

    def __init__(self, name: str, level: Levels = Levels.PROTECTED, description: str = None):
        super().__init__(name, level, description=description)


class LogRight(FrameworkRight):
    """
    Base class for CmdbLog rights
    """
    MIN_LEVEL = Levels.PROTECTED
    MAX_LEVEL = Levels.DANGER
    PREFIX = f'{FrameworkRight.PREFIX}.log'

    def __init__(self, name: str, level: Levels = Levels.PROTECTED, description: str = None):
        super().__init__(name, level, description=description)


class WebhookRight(FrameworkRight):
    """
    Base class for CmdbWebhook rights
    """
    MIN_LEVEL = Levels.PROTECTED
    MAX_LEVEL = Levels.DANGER
    PREFIX = f'{FrameworkRight.PREFIX}.webhook'

    def __init__(self, name: str, level: Levels = MIN_LEVEL, description: str = None):
        super().__init__(name, level, description=description)


class RelationRight(FrameworkRight):
    """
    Base class for CmdbRelation rights
    """
    MIN_LEVEL = Levels.PROTECTED
    MAX_LEVEL = Levels.DANGER
    PREFIX = f'{FrameworkRight.PREFIX}.relation'

    def __init__(self, name: str, level: Levels = MIN_LEVEL, description: str = None):
        super().__init__(name, level, description=description)


class ObjectRelationRight(FrameworkRight):
    """
    Base class for CmdbObjectRelation rights
    """
    MIN_LEVEL = Levels.PROTECTED
    MAX_LEVEL = Levels.DANGER
    PREFIX = f'{FrameworkRight.PREFIX}.objectRelation'

    def __init__(self, name: str, level: Levels = MIN_LEVEL, description: str = None):
        super().__init__(name, level, description=description)


class ObjectRelationLogRight(FrameworkRight):
    """
    Base class for CmdbObjectRelationLog rights
    """
    MIN_LEVEL = Levels.PROTECTED
    MAX_LEVEL = Levels.DANGER
    PREFIX = f'{FrameworkRight.PREFIX}.objectRelationLog'

    def __init__(self, name: str, level: Levels = MIN_LEVEL, description: str = None):
        super().__init__(name, level, description=description)


class RackRight(FrameworkRight):
    """
    Base class for Rack rights (the Rack View feature)
    """
    MIN_LEVEL = Levels.PROTECTED
    MAX_LEVEL = Levels.DANGER
    PREFIX = f'{FrameworkRight.PREFIX}.rack'

    def __init__(self, name: str, level: Levels = MIN_LEVEL, description: str = None):
        super().__init__(name, level, description=description)


class PortRight(FrameworkRight):
    """
    Base class for Port rights (the Port Connectivity feature)
    """
    MIN_LEVEL = Levels.PROTECTED
    MAX_LEVEL = Levels.DANGER
    PREFIX = f'{FrameworkRight.PREFIX}.port'

    def __init__(self, name: str, level: Levels = MIN_LEVEL, description: str = None):
        super().__init__(name, level, description=description)


class ConnectionRight(FrameworkRight):
    """
    Base class for port-connection rights (the Port Connectivity feature)

    Separate from PortRight on purpose: a connection spans TWO objects, so granting somebody the right
    to document an object's ports is not the same as granting them the right to cable it to another
    object's - the second changes something about a device the grantee may not administer
    """
    MIN_LEVEL = Levels.PROTECTED
    MAX_LEVEL = Levels.DANGER
    PREFIX = f'{FrameworkRight.PREFIX}.connection'

    def __init__(self, name: str, level: Levels = MIN_LEVEL, description: str = None):
        super().__init__(name, level, description=description)


class ExtendableOptionRight(FrameworkRight):
    """
    Base class for CmdbExtendableOption rights
    """
    MIN_LEVEL = Levels.PROTECTED
    MAX_LEVEL = Levels.DANGER
    PREFIX = f'{FrameworkRight.PREFIX}.extendableOption'

    def __init__(self, name: str, level: Levels = MIN_LEVEL, description: str = None):
        super().__init__(name, level, description=description)


class ObjectGroupRight(FrameworkRight):
    """
    Base class for ObjectGroup rights
    """
    MIN_LEVEL = Levels.PROTECTED
    MAX_LEVEL = Levels.DANGER
    PREFIX = f'{FrameworkRight.PREFIX}.objectGroup'

    def __init__(self, name: str, level: Levels = MIN_LEVEL, description: str = None):
        super().__init__(name, level, description=description)


class CiExplorerRight(FrameworkRight):
    """
    Base class for CIExplorer rights
    """
    MIN_LEVEL = Levels.PROTECTED
    MAX_LEVEL = Levels.DANGER
    PREFIX = f'{FrameworkRight.PREFIX}.ciExplorer'

    def __init__(self, name: str, level: Levels = MIN_LEVEL, description: str = None):
        super().__init__(name, level, description=description)


class ReportRight(FrameworkRight):
    """
    Base class for CmdbReport rights
    """
    MIN_LEVEL = Levels.PERMISSION
    MAX_LEVEL = Levels.SECURE
    PREFIX = f'{FrameworkRight.PREFIX}.report'

    def __init__(self, name: str, level: Levels = MIN_LEVEL, description: str = None):
        super().__init__(name, level, description=description)


class IpamRight(FrameworkRight):
    """
    Base class for IPAM rights
    """
    MIN_LEVEL = Levels.PROTECTED
    MAX_LEVEL = Levels.SECURE
    PREFIX = f'{FrameworkRight.PREFIX}.ipam'

    def __init__(self, name: str, level: Levels = MIN_LEVEL, description: str = None):
        super().__init__(name, level, description=description)


class LocationRight(FrameworkRight):
    """
    Base class for CmdbLocation rights
    """
    MIN_LEVEL = Levels.PERMISSION
    MAX_LEVEL = Levels.SECURE
    PREFIX = f'{FrameworkRight.PREFIX}.location'

    def __init__(self, name: str, level: Levels = MIN_LEVEL, description: str = None):
        super().__init__(name, level, description=description)
