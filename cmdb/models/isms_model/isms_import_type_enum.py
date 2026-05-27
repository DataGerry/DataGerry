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
Implementation of IsmsImportType enumeration
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

class IsmsImportType(BaseStrEnum):
    """
    Available IsmsImportTypes
    """
    RISK = 'risk'
    CONTROL_MEASURE = 'control_measure'
    THREAT = 'threat'
    VULNERABILITY = 'vulnerability'
