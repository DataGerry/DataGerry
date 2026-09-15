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
ISMS logic that sits above the managers

`RiskMatrixReportBuilder` assembles the risk-matrix report: the IsmsRiskMatrix grid counted by every
risk assessment's before-treatment, current-state and after-treatment calculation. It reads through
three managers, which is why it lives here rather than in `cmdb/models/isms_model/` - a model does
not orchestrate reads, and importing the ISMS model package should not pull the manager layer in

The other ISMS reports are assembled in the route layer's `isms_report_helper.py`
"""
from .risk_matrix_report import RiskMatrixReportBuilder
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'RiskMatrixReportBuilder',
]
