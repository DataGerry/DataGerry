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
REST route package for the relation family

Three blueprints, registered by ``init_rest_api`` at three prefixes:

* ``relations_blueprint`` (``/relations``) - the CmdbRelation, the definition of how two Types may
  be related
* ``object_relations_blueprint`` (``/object_relations``) - the CmdbObjectRelation, one instance of
  such a relation between two CmdbObjects
* ``object_relation_logs_blueprint`` (``/object_relation_logs``) - the CmdbObjectRelationLog, the
  append-only audit trail of those instances. Two reads and a delete: a log is written internally by
  ``ObjectRelationLogsManager``, never through a route, which is why there is no create and no update

The logs live here rather than beside the OBJECT logs (``framework_routes/cmdb_logs``) because what
they record is the entity this package serves; the ACL rights of all three sit together in
``relation_constants``. Nothing is re-exported here - consumers import from the module path - so the
package declares no ``__all__``
"""
