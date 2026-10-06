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
Access control for CmdbTypes and the objects of them

``AccessControlList`` is a type's ``acl`` block (an ``activated`` switch plus its sections), ``GroupACL`` the one
section there is (CmdbUserGroup public_id -> permission values) on top of ``AccessControlListSection``. The
decision for one loaded document is in ``helpers``, the same decision for a whole query in ``builder``
"""
