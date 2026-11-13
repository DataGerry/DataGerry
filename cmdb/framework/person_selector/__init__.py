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
The person selector (``FieldType.PERSON``) on CmdbObjects

  - selector_values: where an object holds selector values, their shape and the ids they name (pure)
  - selector_write_rule: what a write may store - shape, existence, READ, selectable kind; an update keeps what the
      writer cannot see
  - selector_render: what a render shows - the readable selections, labelled
  - selector_delete: the delete guard (a required selection is never emptied) and the clean-up of deleted ids
  - selector_picker: the persons and groups a selector may offer the caller
  - person_selector_constants: wording and keys

The definition of a selector on a type - its settings and their rules - is the type model's
(``cmdb.models.type_model.person_selector_rules``). Consumers import from the module that owns a function
"""
