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
Server-side behaviour of the Rack View feature

  - rack_validator: the pure field rules of a Rack CmdbObject (Rackname present and not blank,
      Height a positive integer), split into a presence set and a value set so the object REST
      routes and the bulk importer can each run the part its own pipeline does not already cover
  - enforcement: the write-path entry point - normalises a Rack candidate in place and returns the
      structured errors, plus the Rack-specific abort formatter
  - mount_validator: the geometry rules of a CmdbRackMount (area, required geometry per area, the fit
      inside the rack's height, and the U-range overlap against the mounts a placement competes with),
      layered so the pure shape checks run before anything needs the rack or its other mounts
  - height_change: what a height reduction does to the mounts that no longer fit - they are UNPLACED
      into the rack's unassigned bucket, never deleted. Backs both the shrink pre-check route and the
      post-write hook on the object update path
  - overview: the pure projection of one rack for drawing - the mounts grouped per area, each resolved to
      the mounted object's summary line and its type's label, icon and colour

Field and section name enums are imported from cmdb.models.special_type_model.rack_constants and the
mount's own enums from cmdb.models.rack_model; the validation messages and limits live in
rack_constants of this package
"""
from cmdb.framework.rack.rack_constants import (
    RackDisplayName,
    RackLimits,
    RackMountError,
    RackMountLimits,
    RackOverviewKey,
    RackValidationError,
)
from cmdb.framework.rack.rack_validator import (
    coerce_rack_height,
    validate_rack_field_values,
    validate_rack_object,
    validate_rack_required_values,
)
from cmdb.framework.rack.enforcement import (
    enforce_rack_object_invariants,
    format_rack_errors_for_abort,
    normalize_rack_object,
)
from cmdb.framework.rack.mount_validator import (
    coerce_slot_value,
    find_slot_conflicts,
    validate_area,
    validate_mount_fits_rack,
    validate_mount_placement,
    validate_mount_shape,
)
from cmdb.framework.rack.height_change import (
    find_mounts_beyond_height,
    get_height_conflicts,
    handle_rack_height_change,
    unplace_mounts_beyond_height,
)
from cmdb.framework.rack.overview import build_mount_row, build_rack_overview
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'RackDisplayName',
    'RackLimits',
    'RackMountError',
    'RackMountLimits',
    'RackOverviewKey',
    'RackValidationError',
    'coerce_rack_height',
    'validate_rack_field_values',
    'validate_rack_object',
    'validate_rack_required_values',
    'enforce_rack_object_invariants',
    'format_rack_errors_for_abort',
    'normalize_rack_object',
    'coerce_slot_value',
    'find_slot_conflicts',
    'validate_area',
    'validate_mount_fits_rack',
    'validate_mount_placement',
    'validate_mount_shape',
    'find_mounts_beyond_height',
    'get_height_conflicts',
    'handle_rack_height_change',
    'unplace_mounts_beyond_height',
    'build_mount_row',
    'build_rack_overview',
]
