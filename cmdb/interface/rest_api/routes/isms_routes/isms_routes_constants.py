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
Shared constants for the ISMS REST routes
"""
# -------------------------------------------------------------------------------------------------------------------- #

# Maximum number of entries allowed for the bounded ISMS scale entities (IsmsImpact, IsmsLikelihood);
# the scales are kept small to keep risk evaluations consistent and manageable
MAX_ISMS_SCALE_ENTRIES: int = 6

# Maximum number of IsmsRiskClasses that may be created
MAX_ISMS_RISK_CLASSES: int = 10

# Minimum number of configured entries per ISMS section before it counts as "ready" in the setup
# status reported by GET /isms/config/status
MIN_CONFIGURED_RISK_CLASSES: int = 3
MIN_CONFIGURED_LIKELIHOODS: int = 3
MIN_CONFIGURED_IMPACTS: int = 3
MIN_CONFIGURED_IMPACT_CATEGORIES: int = 1
