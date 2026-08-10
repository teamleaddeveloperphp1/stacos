"""AY2026-27 constants, loaded once at import time.

Ported from itr1-module/packages/core/src/engine/compute.ts's
`import CONSTANTS from '../config/ay2026-27/constants.json'`.

Unlike compute.ts (which reads dotted attribute access on a TS-typed JSON
import), Python has no static types here, so `compute.py` and `facts.py`
just index this plain dict, e.g. CONSTANTS['chapterVIA']['sections']['80D']['cap'].
"""

import json
import os

_CONSTANTS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), 'data', 'ay2026-27', 'constants.json'
)

with open(_CONSTANTS_PATH, encoding='utf-8') as _f:
    CONSTANTS = json.load(_f)
