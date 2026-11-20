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
The Types that carry PERSON or PERSON_GROUP, on top of the person selector

  - default_person_types: the two default system Types - one per marker, created by the system and never deleted -
      built, planned and seeded insert-if-missing - only by the migration of the old person records
  - person_object_references: what an id of a person or a group names, its display name, and the reports' join - read
      through the caller's READ ACL
  - person_isms_cleanup: deleting a person or group object - the risk-owner refusal and the ISMS references cleared
  - person_memberships: a person joining or leaving groups from its own side - the groups written, their new members
  - person_types_constants: the system author, the default Types' presentation and the wording

The markers, the schemas and the locked base fields are the model's (``cmdb.models.special_type_model``). Consumers
import from the module that owns a function
"""
