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
Constants shared by the ISMS managers
"""
# -------------------------------------------------------------------------------------------------------------------- #

# The stored identity of every ISMS document, and MongoDB's own document id (dropped from every projection)
PUBLIC_ID_KEY: str = 'public_id'
MONGO_ID_KEY: str = '_id'

# The key a `$group` stage answers its grouped value under
GROUPED_ID_KEY: str = '_id'

# What the residue of an undone scale follow-up names, filled with the scale entry's public_id
IMPACT_PROPAGATION_DESCRIPTION: str = "maximum impact of the RiskAssessments using Impact {public_id}"
LIKELIHOOD_PROPAGATION_DESCRIPTION: str = "likelihood value of the RiskAssessments using Likelihood {public_id}"

# What the usage refusals of the leaf ISMS entities say
THREAT_IN_USE_MESSAGE: str = 'Threat is used by IsmsRisks!'
VULNERABILITY_IN_USE_MESSAGE: str = 'Vulnerability is used by IsmsRisks!'
PROTECTION_GOAL_IN_USE_MESSAGE: str = 'ProtectionGoal is used by IsmsRisks!'
CONTROL_MEASURE_IN_USE_MESSAGE: str = 'ControlMeasure is used by ControlMeasureAssignments!'
IMPACT_IN_USE_MESSAGE: str = 'Impact is used by RiskAssessments!'
LIKELIHOOD_IN_USE_MESSAGE: str = 'Likelihood is used by RiskAssessments!'

# What the residue of an undone ImpactCategory / Impact follow-up names
CATEGORY_ADDED_DESCRIPTION: str = "ImpactCategory {public_id} added to every RiskAssessment"
CATEGORY_REMOVED_DESCRIPTION: str = "ImpactCategory {public_id} removed from the RiskAssessments holding it"
IMPACT_DESCRIPTION_ADDED_DESCRIPTION: str = "description of Impact {public_id} added to every ImpactCategory"
IMPACT_DESCRIPTION_REMOVED_DESCRIPTION: str = "description of Impact {public_id} removed from the ImpactCategories"
