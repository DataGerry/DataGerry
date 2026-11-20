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
The user -> person sync: users and user groups mirrored into objects of Types carrying PERSON / PERSON_GROUP

  - person_sync_constants: the settings section, its keys and the refusals
  - sync_settings: the settings of both syncs - read, written whole, the user sync switched off with the group sync
  - sync_settings_rules: what settings must pass before they are stored
  - sync_mapping: what the sync writes - a user's values on its person, a group's name, the synced members
  - sync_lock: what a write may not change on a synced person or a mapped person group
  - sync_guards: what may not be deleted or changed beneath the sync - synced objects, target Types
  - sync_documents: the documents the sync writes, built without reading anything
  - sync_engine: one user or user group mirrored per call - written as the system into the caller's ledger
  - sync_hooks: the sync of a user written outside the routes (LDAP, the cloud admin) and the events registry
  - sync_pass: every user and user group at once - switching on, back on, a resync - and switching off
  - sync_group_mapping: a user group mapped to an existing person group or to one the sync creates
  - sync_relocation_rules: what keeps a synced person from moving to its new target Type
  - sync_relocation: a target change - persons moved keeping their id, or copied when blocked

Consumers import from the module that owns a function
"""
