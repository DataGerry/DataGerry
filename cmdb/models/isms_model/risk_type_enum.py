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
Implementation of RiskType enumeration
"""
from enum import Enum
# -------------------------------------------------------------------------------------------------------------------- #

class RiskType(str, Enum):
    """
    Available RiskTypes for IsmsRisks
    """
    THREAT_X_VULNERABILITY = 'THREAT_X_VULNERABILITY'
    THREAT = 'THREAT'
    EVENT = 'EVENT'


    @classmethod
    def is_valid(cls, value: str | None) -> bool:
        """
        Checks if a given string is a valid RiskType

        Args:
            value (str): The string to check

        Returns:
            bool: True if the string matches an existing RiskType, False otherwise
        """
        return value in RiskType.__members__
