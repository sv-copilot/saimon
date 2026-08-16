"""adapters — legal data-source adapters.

Four S-tier ``SourceIndexAdapter`` implementations: CourtListener, RECAP,
Caselaw Access, and SCOTUS Merits.
"""

from plugins.legal.adapters.caselaw_access import CaselawAccessAdapter
from plugins.legal.adapters.courtlistener import CourtListenerAdapter
from plugins.legal.adapters.recap import RecapAdapter
from plugins.legal.adapters.scotus_merits import ScotusMeritsAdapter

__all__ = [
    "CaselawAccessAdapter",
    "CourtListenerAdapter",
    "RecapAdapter",
    "ScotusMeritsAdapter",
]
