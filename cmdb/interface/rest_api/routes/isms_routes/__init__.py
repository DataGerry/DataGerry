# DataGerry - OpenSource Enterprise CMDB
# Copyright (C) 2025 becon GmbH
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
This module prove all APIBluerpints for ISMS
"""
from .risk_class_routes import risk_class_blueprint
from .likelihood_routes import likelihood_blueprint
from .impact_routes import impact_blueprint
from .impact_category_routes import impact_category_blueprint
from .protection_goal_routes import protection_goal_blueprint
from .risk_matrix_routes import risk_matrix_blueprint
from .isms_config_routes import isms_config_blueprint
from .threat_routes import threat_blueprint
from .vulnerability_routes import vulnerability_blueprint
from .risk_routes import risk_blueprint
from .control_measure_routes import control_measure_blueprint
from .risk_assessment_routes import risk_assessment_blueprint
from .measure_control_assignment_routes import control_measure_assignment_blueprint
from .isms_report_routes import isms_report_blueprint
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'risk_class_blueprint',
    'likelihood_blueprint',
    'impact_blueprint',
    'impact_category_blueprint',
    'protection_goal_blueprint',
    'risk_matrix_blueprint',
    'isms_config_blueprint',
    'threat_blueprint',
    'vulnerability_blueprint',
    'risk_blueprint',
    'control_measure_blueprint',
    'risk_assessment_blueprint',
    'control_measure_assignment_blueprint',
    'isms_report_blueprint',
]
