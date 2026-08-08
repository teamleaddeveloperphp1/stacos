"""IFSC validation service (A-107).

Ported from itr1-module/packages/core/src/services/ifsc.ts.

The rule requires every IFSC under Bank Details, Schedule 80G and Schedule
80GGC to match the RBI database or the GIFT IFSC list. This is an interface
with a cached lookup; it FAILS CLOSED -- when the upstream is unreachable the
result is "could not be verified", never a silent pass.
"""

import re
import time
from dataclasses import dataclass

# RBI IFSC format: 4 alphabets, then '0', then 6 alphanumerics.
IFSC_PATTERN = re.compile(r'^[A-Z]{4}0[A-Z0-9]{6}$')

DEFAULT_TTL_SECONDS = 24 * 60 * 60


@dataclass
class IfscRecord:
    ifsc: str
    bank: str
    branch: str
    source: str  # 'RBI' | 'GIFT'


@dataclass
class IfscLookupResult:
    ifsc: str
    status: str  # 'VALID' | 'NOT_FOUND' | 'MALFORMED' | 'UNAVAILABLE'
    note: str
    record: IfscRecord | None = None


class IfscDirectory:
    """Resolve an IFSC. Raise to signal that the upstream is unavailable."""

    def lookup(self, ifsc):
        raise NotImplementedError


class IfscValidator:
    def __init__(self, directory, ttl_seconds=DEFAULT_TTL_SECONDS):
        self.directory = directory
        self.ttl_seconds = ttl_seconds
        self._cache = {}
        self._cached_at = {}

    def validate(self, raw_ifsc, now=None):
        now = time.time() if now is None else now
        ifsc = (raw_ifsc or '').strip().upper()
        if not IFSC_PATTERN.match(ifsc):
            return IfscLookupResult(
                ifsc=ifsc, status='MALFORMED',
                note='An IFSC must be 4 letters, then 0, then 6 letters or digits.',
            )

        cached_time = self._cached_at.get(ifsc)
        if cached_time is not None and now - cached_time < self.ttl_seconds:
            return self._cache[ifsc]

        try:
            record = self.directory.lookup(ifsc)
            if record:
                result = IfscLookupResult(
                    ifsc=ifsc, status='VALID', record=record,
                    note=f'{record.bank} — {record.branch}',
                )
            else:
                result = IfscLookupResult(
                    ifsc=ifsc, status='NOT_FOUND',
                    note='This IFSC was not found in the RBI database or the GIFT IFSC list.',
                )
            self._cache[ifsc] = result
            self._cached_at[ifsc] = now
        except Exception:
            # FAIL CLOSED. Not cached, so the next attempt retries the upstream.
            result = IfscLookupResult(
                ifsc=ifsc, status='UNAVAILABLE',
                note='IFSC could not be verified — the verification service is unavailable. Retry before generating the JSON.',
            )
        return result

    def validate_many(self, ifscs):
        unique = list({(x or '').strip().upper() for x in ifscs if x})
        return {u: self.validate(u) for u in unique}


class StaticIfscDirectory(IfscDirectory):
    """Development directory backed by a static table. Production wires a
    real RBI/GIFT feed behind the same interface -- nothing else changes."""

    def __init__(self, records):
        self.records = records

    def lookup(self, ifsc):
        return next((r for r in self.records if r.ifsc == ifsc), None)


class UnavailableIfscDirectory(IfscDirectory):
    """A directory that is always down -- used to prove the fail-closed
    behaviour."""

    def lookup(self, ifsc):
        raise RuntimeError('IFSC directory unavailable')
