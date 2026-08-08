"""The IFSC directory instance wired into the Django views.

A real deployment replaces `DEFAULT_DIRECTORY` with a client for the actual
RBI database / GIFT IFSC feed, behind the same `IfscDirectory` interface --
nothing else in the codebase changes (see itr1/services/ifsc.py).
"""

from itr1.services.ifsc import IfscRecord, IfscValidator, StaticIfscDirectory

_DEMO_RECORDS = [
    IfscRecord(ifsc='HDFC0000123', bank='HDFC Bank', branch='Patna Main', source='RBI'),
    IfscRecord(ifsc='SBIN0000001', bank='State Bank of India', branch='Corporate Centre', source='RBI'),
    IfscRecord(ifsc='ICIC0000001', bank='ICICI Bank', branch='Sample Branch', source='RBI'),
]

DEFAULT_DIRECTORY = StaticIfscDirectory(_DEMO_RECORDS)

ifsc_validator = IfscValidator(DEFAULT_DIRECTORY)
