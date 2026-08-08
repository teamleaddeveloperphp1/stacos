# Ambiguous / duplicate CBDT rules — implementer notes

Per the build prompt (§15): where a rule's wording is ambiguous, it is implemented
**literally as written**, with a code comment quoting the rule text verbatim, and
logged here for confirmation against the CBDT utility's actual behaviour before
this module is relied on for a real filing.

This file reconstructs the original `itr1-module` project's `docs/AMBIGUOUS_RULES.md`,
which was deleted along with that project before it was ever committed to git.
Its content is regenerated here from the `note` fields already carried on the
affected rules in `itr1/data/ay2026-27/rules/*.json` — nothing below is new
analysis, it is a faithful record of decisions already encoded in the registry.

---

## A-19 — Name must match the PAN database

> "Name" of taxpayer in ITR does not match with the "Name" as per the PAN
> database (this will be verified at the time of upload).

**Ambiguity:** the PAN database is not reachable from a preparation utility —
there is no way to actually verify a name match offline.

**Implementation:** only presence of the surname is asserted (`present(lastName)`).
The UI shows a permanent warning banner: *"Name must appear exactly as on the
PAN card."* The real check can only happen at portal upload; a false pass here
is expected and by design.

## A-88 — Cash donations aggregated by donee PAN (Schedule 80G)

> If Old Tax Regime is selected, and in Schedule 80G if multiple entries are
> under donation in cash with same PAN then more than Rs 2,000 then amount
> entered in donation in cash will not be considered for calculation of
> Eligible amount of donation. If sum of all such cash donation exceeds
> Rs. 2000 then eligible amount of donation shall not be more than 0 or in
> case of individual entry is more than Rs. 2000 in [sentence cuts off in the
> source document]

**Ambiguity:** the source text is grammatically incomplete — it is not fully
clear whether the ₹2,000 cap applies per row or per aggregate-by-PAN, and the
final clause is truncated.

**Implementation:** aggregate cash donations **per donee PAN across the whole
schedule**. If that aggregate exceeds ₹2,000, the entire cash component for
that PAN is disallowed (eligible = 0 for cash); otherwise it is allowed up to
₹2,000. This is the stricter reading and matches the golden/coverage test
fixtures. **A-327 is registered as an alias of A-88** — the two rules describe
the same assertion from two angles (A-88 as the general cap, A-327 as "lower
of cap or claimed").

## A-268 — Date of formation on/after 01/04/2008 blocks Individual filing

> Status selected is Individual and having date of formation on or after
> 01/04/2008 shall not be allowed to file return for AY 26-27.

**Ambiguity:** "date of formation" is conceptually an entity concept (company,
trust, AOP/BOI); an Individual does not have a formation date. The rule is
worded as if it applies to all statuses uniformly.

**Implementation:** implemented **literally as written** — the optional
`personalInfo.dateOfFormation` field exists on the model (normally left blank
for an Individual), and if a value is present and falls on/after 2008-04-01,
the return is blocked. This will essentially never fire in practice for a
genuine Individual, but the rule is asserted exactly per its text rather than
silently dropped.

## A-206/A-209 and A-207/A-208 — "deduction" vs "donation" near-duplicates

> In schedule 80DD / 80U, if deduction is > 0, then details of such deduction
> [A-206/A-207] / donation [A-209/A-208] are required.

**Ambiguity:** A-206 and A-209 (Schedule 80DD) are textually identical except
for the word "deduction" vs "donation" — Schedule 80DD has nothing to do with
donations, so this looks like a copy-paste artifact in the source document.
Same pattern for A-207/A-208 (Schedule 80U).

**Implementation:** per the build prompt's explicit instruction, the **stricter
reading** is used — both rule pairs are registered as separate rule IDs (for
CBDT numbering fidelity) but resolve to the identical assertion
(`sched80DDFilled` / `sched80UFilled`, i.e. details are mandatory whenever the
claimed amount exceeds zero). A-208 is registered as an alias of A-207, and
A-209 as an alias of A-206.

## A-325/A-326 — Textually identical rules (Schedule 80G IFSC/reference mandatory)

> IFSC and "Transaction Reference number for UPI transfer / Cheque number /
> IMPS / NEFT / RTGS reference number" in Schedule 80G is mandatory in case
> donation is in a mode other than cash.

**Ambiguity:** none in meaning — A-325 and A-326 are simply the same rule
listed twice in the source document under two IDs.

**Implementation:** implemented once; A-326 is registered as an alias of A-325,
per the build prompt's explicit instruction ("implement once, register both
IDs pointing at the same assertion").

## A-253/A-162 — New-regime self-occupied interest block (restated)

Not textually identical, but A-253 ("Interest on borrowed capital in Schedule
24(b) can't be claimed for a self-occupied property under the new regime")
restates the same assertion as A-162 in different words. A-253 is registered
as an alias of A-162 for the same reason as the pairs above.

---

## How to use this file

If you are validating this module's output against the actual CBDT e-filing
portal or utility and one of these seven rule IDs produces an unexpected
accept/reject, start here — the decision and its rationale are recorded above,
not buried in a commit message. Update this file (not just the code) if a
reading turns out to be wrong.
