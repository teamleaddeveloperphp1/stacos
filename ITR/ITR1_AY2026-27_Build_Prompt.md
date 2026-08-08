# BUILD PROMPT — ITR-1 (Sahaj) Preparation Module, AY 2026-27
### For: stacos.ai · Feature scope: ITR-1 preparation only, ending in a 100% CBDT-valid JSON

---

## 0. HOW TO USE THIS PROMPT

Paste this entire document into the AI coding tool as the specification. Attach the following files alongside it — they are **normative**, this document is **interpretive**:

| File | Role | Authority |
|---|---|---|
| `ITR-1_2026_Main_V1_1.json` | CBDT JSON schema, ITR-1, AY 2026-27, V1.1 | **Absolute.** Element names, nesting, data types, enums, minOccurs/maxOccurs, string lengths and regex patterns come from here and nowhere else. |
| `CBDT_e-Filing_ITR_1_Validation_Rules_AY_2026-27.pdf` | 339 Category A + 9 Category B + 1 Category D rules | **Absolute** for validation logic. |
| `ITR_1_Schema_change_document_AY2026-27_V1_1.pdf` | Delta from V1.0 (15-May-2026) to V1.1 (30-Jun-2026) | Confirms `ExemptIncAgriOthUs10` → `SubCategory` enum updated and `Description` field added. Build against **V1.1**. |
| Screenshots 1–7 | Reference UX from the government e-filing portal | Guidance for screen order, field grouping and labels. |

**Rule of precedence when this document conflicts with an attached artifact: the artifact wins.** If any field name written below does not exist in the attached JSON schema, use the schema's name and log the discrepancy in a `SCHEMA_MAPPING_NOTES.md`.

---

## 1. MISSION

Build a web-based, multi-tenant **ITR-1 preparation module**. A preparer (or the taxpayer) enters data across seven screens driven by a persistent left-hand menu. The module computes income, deductions, tax, interest and fees; runs the complete CBDT validation rule set; and emits a JSON file that the Income Tax Department's e-filing portal accepts **without a single schema or validation error on first upload**.

### 1.1 The single success criterion
> A JSON produced by this module, uploaded to `incometax.gov.in`, must pass the portal's own validation with zero errors. If the portal reports an error our pre-validation screen did not catch, that is a **P0 defect**.

### 1.2 In scope
- ITR-1 only. All seven screens. Save/resume. Draft versioning.
- Full computation engine (both tax regimes, AY 2026-27 rates).
- Full validation engine (Category A blocking, B advisory, D document-advisory).
- JSON generation + JSON re-import (round-trip a previously generated file back into the form).
- Optional Form 16 / AIS pre-fill **ingestion** (accept a structured payload from an upstream service and populate fields) — build the interface, treat the upstream as a stub.

### 1.3 Explicitly out of scope — do not build
- Filing/submission to the portal, e-verification, EVC, Aadhaar OTP, DSC signing.
- ITR-2/3/4, Form 10E, Form 10IA, Form 10BA, Form 67 — but **do** provide fields that record "Form X has been filed separately" where a rule requires it.
- Payment gateways, challan generation. (Challan **details** are captured; challans are not created.)
- Tax planning advice, regime-comparison recommendations. A neutral side-by-side calculator is acceptable; a recommendation is not.

---

## 2. ARCHITECTURE MANDATES

These are not suggestions. They exist because CBDT reissues schemas and rule sets mid-season, and the module must absorb that in a config change rather than a release.

1. **The validation rule set is data, not code.** Every rule lives in a versioned registry (`rules/ay2026-27/category-a.json` etc.) with this shape:
   ```json
   {
     "id": "A-120",
     "category": "A",
     "ay": "2026-27",
     "screen": "TOTAL_DEDUCTIONS",
     "fields": ["DeductUndChapVIA.Section80CCD2", "Salary17_1", "EmployerCategory"],
     "appliesWhen": "regime == 'OLD' && ['CGOV','SGOV'].includes(employerCategory)",
     "assert": "deduction80CCD2 <= 0.14 * salary17_1",
     "severity": "BLOCK",
     "message": "Under the old regime, deduction u/s 80CCD(2) cannot exceed 14% of salary where the employer is Central or State Government.",
     "remediation": "Reduce the 80CCD(2) claim to {{maxAllowed}} or lower.",
     "deepLink": "TOTAL_DEDUCTIONS#sec80CCD2"
   }
   ```
   Expressions are evaluated by a sandboxed evaluator (jsonata / expr-eval / CEL — no `eval`).

2. **The tax computation constants are data too.** Slabs, rebate thresholds, cess rate, standard deduction, section caps, due dates all live in `config/ay2026-27/constants.json`. Zero magic numbers in code.

3. **One canonical in-memory model → one serializer.** All screens read/write a single normalised `ReturnModel`. The JSON serializer is the only component that knows CBDT element names. Never let UI components construct schema fragments.

4. **Validation runs at three tiers**, all against the same registry:
   - **Tier 1 — field-level, on blur.** Format, length, regex, range.
   - **Tier 2 — screen-level, on Confirm.** Cross-field rules confined to that screen.
   - **Tier 3 — return-level, on the Validation screen.** Every rule, including cross-screen rules.
   A rule fires identically at whichever tier it is reachable. No rule may exist only at Tier 3.

5. **Every derived value is computed, never typed.** Fields the portal shows as read-only (grey boxes in screenshots 5 and 6) must be read-only here, recomputed on every model change, and never accepted from user input or from an imported JSON without recomputation.

6. **Full audit trail.** Every field change: who, when, old value, new value. Every validation run: timestamp, rule set version, pass/fail, error list. Every JSON generation: hash of the output, model snapshot.

7. **Idempotent JSON generation.** Same model → byte-identical JSON, except `JSONCreationDate`.

---

## 3. INFORMATION ARCHITECTURE

### 3.1 Left menu (persistent, always visible)

```
ITR-1 · AY 2026-27 · [Taxpayer Name] · [PAN]
─────────────────────────────────────────
  ○ 1. Personal Information          [status]
  ○ 2. Gross Total Income            [status]
  ○ 3. Total Deductions              [status]
  ○ 4. Tax Paid                      [status]
  ○ 5. Tax Liability                 [status]
  ○ 6. Tax Summary                   [status]
  ─────────────────────────────────
  ○ 7. Validation & JSON             [status]
─────────────────────────────────────────
  Draft saved 14:32 · v7 · [Save] [Exit]
```

**Status chip per item:** `Not started` (grey) · `In progress` (amber) · `Confirmed` (green tick) · `Has errors` (red, with error count badge).

### 3.2 Navigation rules
- Screens 1–6 are **freely navigable** in any order. Do not force a wizard. Preparers jump around.
- Screen 7 (Validation) is **enabled always** but reports "N screens not yet confirmed" as an advisory if any of 1–6 are unconfirmed.
- **Confirm** on a screen runs Tier 2 validation. On failure, remain on the screen, mark the chip red, scroll to the first error. On success, mark green and advance to the next unconfirmed screen.
- Editing any field on a confirmed screen reverts that chip to amber and **invalidates any prior successful validation run** — the Download JSON button greys out until re-validation.
- A red chip anywhere blocks JSON download. Amber chips do not block, but produce a confirmation modal.
- Deep links: `/return/{id}/deductions#sec80D` must open the screen, expand the accordion, focus and outline the field.

### 3.3 Global chrome
- Header: taxpayer name, PAN, AY, filing section, **current regime badge** (`NEW REGIME` / `OLD REGIME`), live refund/payable ticker.
- Breadcrumb mirroring the portal: `Dashboard › Returns › ITR-1 AY 2026-27 › {Screen}`.
- Autosave every 20 seconds and on every blur. Optimistic locking on concurrent edit; show "edited by {user} at {time}".
- Session timer is **not** required (that is a portal artifact); a soft idle warning at 30 minutes is.

---

## 4. SCREEN 1 — PERSONAL INFORMATION

*(Reference: screenshot 1)*

### 4.1 Section: Profile (read-only if pre-filled, editable otherwise)

| Field | Type / constraint | Rules |
|---|---|---|
| First Name | Text, mandatory | Combined name must match PAN database exactly — **A-19**. Show a warning banner: "Name must appear exactly as on the PAN card." |
| Middle Name | Text, optional | |
| Last / Surname | Text, mandatory for Individual | |
| PAN | 10 char, regex `[A-Z]{5}[0-9]{4}[A-Z]{1}`, mandatory | 4th character must be `P` for Individual — block otherwise with "ITR-1 can be filed only by an Individual." |
| Date of Birth | Date, mandatory, ≤ today | Drives senior-citizen logic. |
| Aadhaar Number | 12 digits, mandatory | Must equal the Aadhaar on profile — **A-212**. Store masked, compare on full value. **B-1, B-2**: if Aadhaar absent or unlinked, raise a Category B advisory. |
| Status | Fixed = Individual | **A-268**: if a "date of formation" is captured and is on/after 01/04/2008, block. For an Individual this is DOB-adjacent; implement the field, apply the rule literally as written. |

**Derived, not shown but used everywhere:**
- `isSeniorCitizen` = DOB on or before **01.04.1966** (per **A-13**).
- `isSeniorForTTB` = DOB **not** before 02.04.1966, i.e. age ≥ 60 (per **A-15**). Implement both predicates exactly as the rules word them — they are date-boundary specific, do not "simplify" to an age calculation.
- `isSuperSenior` = age ≥ 80 (for old-regime slab).

### 4.2 Section: Contact
Primary mobile (country code + 10 digits, mandatory), secondary mobile, primary email (mandatory, RFC-valid), secondary email.

**Primary Address** — mandatory: flat/door/building, premise/building name, road/street, area/locality, town/city/district, state (CBDT state code enum from schema), country (code enum), PIN (6 digits).

**Secondary Address** — **A-338**: mandatory in the return. **A-339**: if "Is the secondary address same as primary address?" = **No**, the secondary address must differ from the primary on at least one line. Implement as: radio Yes/No; Yes → copy primary and lock; No → require entry and run a field-by-field difference check.

### 4.3 Section: Nature of Employment
Dropdown, enum from schema. Expected values: Central Government · State Government · Public Sector Undertaking · Pensioners (CG) · Pensioners (SG) · Pensioners (PSU) · Pensioners (Other) · Others · Not Applicable.

- **A-210**: if any salary income is entered on Screen 2, `Not Applicable` is **blocked**.
- **A-264**: if salary income and exempt allowances exist, Nature of Employment is mandatory.
- This field gates: 80CCD(1) cap (**A-2, A-3**), 80CCD(2) cap (**A-4, A-116, A-120, A-216**), 80CCH eligibility (**A-187**), entertainment allowance 16(ii) (**A-57, A-58**), gratuity exemption ceiling (**A-67** ₹20L vs **A-267** ₹25L), leave encashment (**A-142**), 10(10B) eligibility (**A-185**), judge's exempt income (**A-270**).
  Surface a live "Because employment is X, the following limits apply…" helper panel. This single dropdown is the most common source of rejections.

### 4.4 Section: Filing Section

Radio group (mirror the portal): `139(1)` on/before due date · `139(4)` belated · `139(5)` revised · `119(2)(b)` after condonation · `139(8A)` updated.
Second toggle "Filed in response to notice u/s": `139(9)` · `142(1)` · `148` · `153C`.

**Regime selection** — the question is worded as an *opt-out*: "Do you wish to exercise the option u/s 115BAC(6) of opting out of the new tax regime? (default is No)". Model it as `optOutOfNewRegime: Yes|No`, derive `regime = optOutOfNewRegime === 'Yes' ? 'OLD' : 'NEW'`, and display the derived regime prominently. Never store "regime" as the primary field — the JSON carries the opt-out flag.

**Hard regime gates (all BLOCK):**
- **A-151**: Old regime cannot be selected after the due date u/s 139(1). Compare filing date against the configured due date. In the sample data, filing section is 139(4) — belated — so **Old regime must be disabled** and the opt-out radio locked to "No".
- **A-190**: the option to withdraw from the new regime is unavailable after the 139(1) due date.
- **A-189**: return u/s 139(5) where the original was u/s 139(4) → Old regime blocked.
- **A-126**: if the original return was filed u/s 142(1), a return u/s 139 cannot be filed.
- **A-152**: once proceedings are initiated u/s 148, no return u/s 139 may be filed.
- **A-219**: filing section 139(9) → the A23 responses must match the responses in the ITR against which the defective response is being submitted. Capture the original acknowledgement number and A23 responses; compare.

When Old regime is unavailable, do not merely hide the option — show it disabled with the reason inline: *"Old regime unavailable: return is being filed u/s 139(4) after the due date (Rule A-151)."*

### 4.5 Other questions
- "Are you filing return of income under Seventh proviso to section 139(1) but otherwise not required to furnish return of income?" — Yes/No; if Yes, capture the sub-conditions.
- "Whether this return is being filed by a representative assessee?" — Yes/No. If **Yes**, **A-294** requires details; **A-293** makes Name, Email ID and Contact No. of the representative mandatory; **A-331** requires the representative's email and phone to **differ** from the taxpayer's primary and secondary email and phone. Also capture capacity, representative PAN, and address.

### 4.6 Section: Bank Details (collapsible, as in the portal)
Repeating table: IFSC · Bank Name (auto-populated from IFSC) · Account Number · Account Type (SB/CA/CC/OD/NRO/Other) · "Nominate for refund" checkbox.
- **A-107**: IFSC must validate against the RBI database / GIFT IFSC codes. Build an `IFSCValidator` service interface with a cached lookup; fail closed with "IFSC could not be verified" if the service is unavailable — never silently pass.
- At least one account is mandatory. Exactly one must be nominated for refund. If a refund arises on Screen 6, the nominated account must be a resident Indian account.

---

## 5. SCREEN 2 — GROSS TOTAL INCOME

*(Reference: screenshot 2)* Accordion sections B1–B4 with Expand All / Collapse All.

### 5.1 B1 — Income from Salary

| Line | Label | Behaviour |
|---|---|---|
| i | Gross Salary (ia + ib + ic) | Computed. **A-59** |
| ia | Salary as per section 17(1) | Input |
| ib | Value of perquisites u/s 17(2) | Input |
| ic | Profits in lieu of salary u/s 17(3) | Input |
| ii | Less: allowances exempt u/s 10 | Computed from the Exempt Allowances sub-schedule. **A-77**, **A-63** (≤ Gross Salary), **A-213** (each section disclosed in exactly one dropdown row) |
| iii | Net Salary (i − ii) | Computed. **A-60** |
| iv | Deductions u/s 16 (iva + ivb + ivc) | Computed. **A-61** |
| iva | Standard deduction u/s 16(ia) | Auto: **₹75,000** new regime (**A-215**), **₹50,000** old regime (**A-112**), capped at Net Salary |
| ivb | Entertainment allowance u/s 16(ii) | **A-57** old regime + CG/SG/PSU only: least of ₹5,000 or ⅕ of salary. **A-58** blocked for other employers. **A-163** must be 0 in new regime |
| ivc | Professional tax u/s 16(iii) | **A-168**: must be 0 in new regime |
| v | Income chargeable under 'Salaries' (iii − iv) | Computed. **A-62** |

**Multiple employers:** support a repeating employer block (name, TAN, category) whose totals roll into ia/ib/ic and which cross-references Schedule TDS1 on Screen 4.

**Exempt Allowances sub-schedule** — a repeating dropdown + amount grid. Enforce:
- **A-213 / A-184**: each nature-of-allowance may be selected **at most once**. Disable already-chosen options in the dropdown.
- Section-wise ceilings: 10(5) LTC ≤ salary 17(1) (**A-64**), 10(6) ≤ gross salary (**A-65**), 10(7) ≤ gross salary (**A-66**), 10(10) gratuity ≤ ₹20,00,000 for PSU/Others/pensioner categories (**A-67**) and ≤ ₹25,00,000 for CG/SG/their pensioners (**A-267**), 10(10A) ≤ salary 17(1) (**A-68**), 10(10AA) leave encashment ≤ salary 17(1) (**A-69**) with a ₹25L advisory and **A-142** block above ₹25L for non-government employers, 10(10B) first proviso ≤ ₹5,00,000 (**A-70**), 10(10B) second proviso ≤ ₹5,00,000 (**A-188**), 10(10C) ≤ ₹5,00,000 (**A-71**), **A-72** only one of 10(10B)(i) / 10(10B)(ii) / 10(10C) may be selected, **A-185** 10(10B)(i) and (ii) disallowed for CG/SG employees and all pensioner categories, 10(10CC) ≤ perquisites 17(2) (**A-73**) and ≤ TDS claimed u/s 192 in TDS1 (**A-177**).
- **HRA 10(13A)**: old regime only. **A-74** ≤ salary 17(1); **A-176** ≤ ⅓ of salary 17(1); **A-165** must be 0 in new regime. **A-265** requires the 10(13A) schedule to be filled; **A-269** the claimed exemption must equal the schedule's eligible amount; **A-263** the eligible amount is the **least of** (actual HRA received; actual rent paid − 10% of salary+DA; 40%/50% of salary+DA) with **A-261** and **A-262** as the individual assertions; **A-266** basic + DA + HRA per the schedule ≤ salary 17(1). Build the 10(13A) schedule as a period-wise grid (place of work, metro flag, basic, DA, HRA received, rent paid) and compute the least-of automatically.
- **10(14)(i) / 10(14)(ii)**: **A-75, A-76** old-regime ceilings vs salary 17(1)(ia); **A-166, A-167** must be 0 in new regime; **A-150** old regime blocks 10(14)(i) Rule 2BB sub-clauses (a)–(c) and the transport allowance for handicapped assessees; **A-148** new regime caps the handicapped transport allowance at ₹38,400; **A-149** new regime blocks 10(5), 10(13A), 10(14)(i), 10(14)(ii) generally.
- **10(17)** MP/MLA/MLC: **A-37** once only; **A-161** must be 0 in new regime.
- Judge's exempt income: **A-270** CG/SG employees only; **A-301** must be 0 in new regime.

### 5.2 B2 — Income from House Property

Type of property: **Self-Occupied · Let Out · Deemed Let Out**. `Type of house property` is mandatory whenever interest u/s 24(b) is claimed (**A-271**).

| Line | Label | Rule |
|---|---|---|
| B2i | Gross rent received / receivable / lettable value | **A-45** must be > 0 for let-out/deemed let-out; **A-44** must be > 0 or null where municipal tax is claimed |
| B2ii | Tax paid to local authorities | **A-49** not allowed for Self-Occupied |
| B2iii | Annual Value (i − ii) | Computed. **A-46** |
| B2iv | 30% of Annual Value | Computed, exactly 30%. **A-43** |
| B2v | Interest payable on borrowed capital | **A-48** old regime + self-occupied → ≤ ₹2,00,000; **A-162** new regime + self-occupied → must be 0; **A-253** restates the new-regime block; **A-240** must equal the total of interest paid per Schedule 24(b) |
| B2vi | Arrears / unrealised rent received less 30% | Input |
| B2vii | Income chargeable under 'House Property' | Computed as (iii − iv − v + vi). **A-47** |

Also: "The amount of rent which cannot be realized" ≤ gross rent (**A-336**).

**Co-ownership block:** "Is property co-owned?" Yes → assessee's share % must be **< 100** (**A-332**); other co-owners' share must be **> 0 and < 100** (**A-333**); total of all shares = **100%** (**A-295**); annual value must be share % × annual value (**A-296**); if the assessee's share is zero, interest on borrowed capital must be zero (**A-297**); co-owner PAN ≠ assessee PAN (**A-300**). If not co-owned, share = 100% (**A-334**).
HP schedule internal totals: **A-298** (1d = 1b + 1c), **A-299** (1i = 1g + 1h).

**Schedule 24(b)** — repeating: lender name, lender type (bank/NBFC/other), lender PAN/TAN, account number, sanction date, sanctioned amount, interest paid during the year. **A-220** these details are mandatory to claim 24(b); **A-246** the sum of rows must equal the schedule total.

**Loss limitation:** house property loss set off against other heads is capped at ₹2,00,000. Under the new regime, **A-160**: where there is an HP loss, GTI must equal salary + other sources (i.e. the loss is not set off).

### 5.3 B3 — Income from Other Sources

Repeating dropdown + amount grid. Each nature may be selected **at most once**: interest from savings account (**A-50**), interest from deposits (**A-51**), interest on income tax refund (**A-55**), family pension (**A-56**). Plus dividend, and "any other".
- **A-52**: the head total must equal the sum of the individual rows.
- **A-145**: total dividend income must equal the sum of the quarterly dividend breakup. Provide the quarterly grid (Q1 to 15/6, 16/6–15/9, 16/9–15/12, 16/12–15/3, 16/3–31/3) — it also drives 234C.
- **Deduction u/s 57(iia)** on family pension: old regime → lower of ⅓ of family pension or **₹15,000** (**A-54**, tolerance ±1 for rounding), and allowed only if family pension is offered to tax and the taxpayer is not in the new regime (**A-53**); new regime → ⅓ of family pension capped at **₹25,000** (**A-214**).

### 5.4 B4 — Gross Total Income and eligibility gates
- **A-22** (old) / **A-174** (new): GTI = Salary + House Property + Other Sources + LTCG u/s 112A. Assert exactly.
- **A-117**: total income excluding LTCG u/s 112A must not exceed **₹50,00,000**. On breach, block with: *"ITR-1 cannot be used. Total income exceeds ₹50 lakh — ITR-2 is required."*
- **A-20**: if a tax liability has been computed and paid, GTI and the income heads must be > 0.
- **A-21**: if taxes paid are disclosed, income details and tax computation must be disclosed.

### 5.5 Exempt Income sub-schedule (also on this screen)
Repeating dropdown + amount. **A-184** is the master rule: **no nature-of-income drop-down may be selected more than once.** Rules **A-31 to A-42**, **A-141**, **A-303 to A-322** enumerate the specific sections — implement the generic uniqueness constraint over the whole enum, then keep the per-section rule IDs in the registry so error messages cite the right number.

Additional constraints on this schedule:
- **A-29**: agricultural income shown as exempt cannot exceed **₹5,000**.
- **A-30**: the exempt income total must equal the sum of individual rows.
- **A-217**: LTCG u/s 112A shown under exempt income must not exceed **₹1,25,000**.
- **A-218**: that figure must equal (i − ii) of its own sub-rows.
- **A-292**: LTCG u/s 112A must equal (GTI including LTCG − GTI excluding LTCG).
- **A-323**: new regime → exempt income u/s 10(32) minor child's income must be 0.
- **V1.1 change:** `ExemptIncAgriOthUs10` now carries an updated `SubCategory` enum **and a new `Description` field**. Bind the dropdown to the V1.1 enum and expose `Description` as a free-text field where the schema marks it required for a given SubCategory.

---

## 6. SCREEN 3 — TOTAL DEDUCTIONS

*(Reference: screenshot 3)*

### 6.1 Regime-driven rendering
Under the **new regime**, only **80CCD(2)** and **80CCH** are claimable. Every other Chapter VI-A section must be **rendered disabled with the value locked to 0** and an inline note: *"Not available under the new tax regime."* Do not hide them — the portal shows them at 0 (screenshot 6) and preparers expect to see the list.

Rules enforcing this: **A-146** (the master rule listing B5(a)–B5(s)), **A-153** (80C+80CCC+80CCD(1) = 0), **A-154** (80DD), **A-155** (80DDB), **A-156** (80G, and no Schedule 80G details), **A-157** (80TTA), **A-158** (80TTB), **A-159** (80U), **A-169** (80CCD(1B)), **A-170** (80EE), **A-171** (80EEA), **A-172** (80EEB), **A-173** (80D, and no Schedule 80D details), **A-175** (80GGA, and no Schedule 80GGA details), **A-255** (an Individual in the new regime must not have filled the 80C, 10(13A), 80E, 80EE, 80EEA or 80EEB schedules).

### 6.2 Section-by-section (old regime)

| Section | Cap / logic | Rules |
|---|---|---|
| 80C | Part of the ₹1,50,000 aggregate. Schedule 80C required: type of identifier, identification number, amount of payment | **A-1, A-224, A-241, A-247, A-272** |
| 80CCC | Part of ₹1,50,000. If > 0, at least one row with type of identifier, identifier no., amount | **A-1, A-302, A-337, A-273** |
| 80CCD(1) | Part of ₹1,50,000. Pensioner/NA employer → ≤ 20% of GTI; other employers → ≤ 10% of salary. PRAN mandatory | **A-1, A-2, A-3, A-226, A-274** |
| 80CCD(1B) | ≤ ₹50,000. PRAN mandatory. If PRAN entered but 80CCD(1) and (1B) both 0 → error | **A-115, A-226, A-275, A-335** |
| 80CCD(2) | Old: ≤ 14% of salary for CG/SG employers, ≤ 10% otherwise. New: ≤ 14% for PSU/Others/Central/State. Blocked entirely for all pensioner categories and 'Not Applicable' | **A-4, A-116, A-120, A-216, A-276** |
| 80CCH | Available **only** where Nature of Employment = Central Government and age at date of joining the armed forces is 17–27. ≤ 46.2% of salary 17(1) | **A-186, A-187, A-291** |
| 80D | Schedule 80D mandatory. 1a Self/Family ≤ ₹25,000; 1b Self/Family incl. senior ≤ ₹50,000; 2a Parents ≤ ₹25,000; 2b Parents incl. senior ≤ ₹50,000; total ≤ ₹1,00,000; preventive health check-up across all rows ≤ ₹5,000; 1a/1b gated on the "is any family member a senior citizen?" dropdown, 2a/2b on the parents dropdown; insurer name and policy number mandatory per row; row breakups must reconcile to the header premium | **A-127 to A-138, A-178 to A-183, A-234 to A-237, A-254, A-256 to A-259, A-277** |
| 80DD | Dependent with disability ₹75,000 exactly; severe ₹1,25,000 exactly (subject to GTI). Details mandatory. Form 10IA filed separately must be recorded | **A-203, A-204, A-205, A-206, A-209, A-238, A-278** |
| 80DDB | ≤ ₹1,00,000; "Self or Dependent" category ≤ ₹40,000; eligible-category description mandatory; specified disease mandatory | **A-5, A-6, A-7, A-239, A-279** |
| 80E | Must equal the total interest paid per Schedule 80E; row sum must match the schedule total | **A-242, A-248, A-280** |
| 80EE | ≤ ₹50,000. Loan sanctioned 01.04.2016–31.03.2017. Loan ≤ ₹35 lakh. Bank details mandatory and must be a subset of the 24(b) disclosures. Claimable only once the 24(b) limit is exhausted | **A-121, A-221, A-222, A-225, A-227, A-243, A-249, A-252, A-281** |
| 80EEA | ≤ ₹1,50,000. Sanctioned 01.04.2019–31.03.2022. Stamp duty value ≤ ₹45 lakh. Bank details mandatory, subset of 24(b). Mutually exclusive with 80EE | **A-122, A-123, A-221, A-223, A-228, A-229, A-230, A-244, A-250, A-282** |
| 80EEB | ≤ ₹1,50,000. Sanctioned 01.04.2019–31.03.2023. Bank details mandatory | **A-124, A-231, A-232, A-245, A-251, A-283** |
| 80G | Schedule 80G mandatory. Four tables A/B/C/D. Donee PAN ≠ assessee PAN ≠ verification PAN. A PAN entered in one block cannot appear in another. Cash > ₹2,000 disallowed. Eligible ≤ total donations. IFSC + transaction reference mandatory for non-cash | **A-8, A-9, A-10, A-78 to A-88, A-139, A-147, A-284, A-325, A-326, A-327, A-330** |
| 80GG | ≤ lesser of ₹60,000 or 25% of total income excluding LTCG before this deduction. Blocked if HRA u/s 10(13A) is claimed for the same period. Form 10BA details mandatory | **A-114, A-119, A-233, A-285** |
| 80GGA | Cash donation > ₹2,000 disallowed. Same donee PAN cannot repeat. Eligible ≤ total. Details mandatory | **A-89 to A-94, A-118, A-143, A-144, A-286** |
| 80GGC | Name and PAN of the political party mandatory. Date of contribution mandatory and must fall between 01.04.2025 and 31.03.2026. Only non-cash mode is eligible. Row sums must reconcile. IFSC validated | **A-107, A-193 to A-199, A-211, A-287, A-329** |
| 80TTA | ≤ ₹10,000; restricted to savings-account interest in Other Sources; blocked for senior citizens (DOB on or before 01.04.1966) | **A-11, A-12, A-13, A-288** |
| 80TTB | ≤ ₹50,000; only for age ≥ 60 (DOB not before 02.04.1966); restricted to interest income from other sources | **A-14, A-15, A-16, A-289** |
| 80U | Self with disability ₹75,000 exactly; severe ₹1,25,000 exactly (subject to GTI). Details mandatory. Form 10IA recorded | **A-200, A-201, A-202, A-207, A-208, A-238, A-290** |

### 6.3 Cross-cutting deduction rules
- **A-272 to A-291**: for **every** section, the *eligible* amount computed by the system must never exceed the *user-entered* amount. Implement one generic assertion over the section registry rather than twenty hand-written checks.
- **A-17**: total Chapter VI-A must equal the sum of individual eligible deductions restricted to GTI.
- **A-18**: total Chapter VI-A ≤ GTI.
- Display **C1. Total deductions** as a computed footer, matching the portal.

---

## 7. SCREEN 4 — TAX PAID

*(Reference: screenshot 4)* Five collapsible schedules plus a computed footer.

### 7.1 Schedule TDS1 — TDS from salary (Form 16)
Columns: Sl · TAN of deductor (regex `[A-Z]{4}[0-9]{5}[A-Z]{1}`) · Name of deductor · Income chargeable under Salaries · Total tax deducted.
- **A-100**: the column total must equal the sum of rows.
- **B-9**: TDS deducted in TDS1 must not exceed Gross Salary — Category B advisory.
- Cross-check: the sum of "income chargeable under Salaries" across TDS1 rows should reconcile to B1; flag a soft mismatch.

### 7.2 Schedule TDS2 — TDS other than salary (Form 16A)
Columns: TAN/PAN of deductor · Name · Gross receipt · Year of tax deduction · Tax deducted · TDS credit claimed this year · Section under which deducted · Head of income.
- **A-98**: TDS claimed ≤ tax deducted.
- **A-99**: year of deduction cannot be 0 or null where credit is claimed.
- **A-101**: column total = sum of rows.
- **A-260**: section 192 must not be selectable in TDS2/TDS3.
- **B-3, B-5, B-7**: selecting section codes 194B, 194BB, 194BA, 194IA, 194IC, 194LA, 194S / 194E, 194LB, 194LC, 194LBA(a)(b)(c), 195, 196A, 196B, 196C, 196D, 196D(1A) / 194Q, 194C, 194R raises a Category B advisory that ITR-1 may not be applicable. Show this **immediately on selection**, not only at validation.

### 7.3 Schedule TDS3 — TDS as per Form 16C/16D
Same shape as TDS2. **A-102** column total; **A-99**, **A-260**; **B-4, B-6, B-8** mirror the TDS2 advisories.

### 7.4 Schedule TCS — Form 27D
**A-96**: TCS claimed ≤ tax collected. **A-97**: column total = sum of rows. **A-99** applies.

### 7.5 Schedule IT — Advance tax and self-assessment tax
Columns: BSR code (7 digits) · Date of deposit · Challan serial number (5 digits) · Amount.
- **A-95**: total of col 4 = sum of rows.
- **A-110**: total *advance tax* = sum of Schedule IT rows dated **01.04.2025 to 31.03.2026**.
- **A-111**: total *self-assessment tax* = sum of Schedule IT rows dated **after 31.03.2026**.
  Classify each challan automatically by date; do not ask the user to choose.

### 7.6 Footer
**Total Taxes Paid** = TDS1 + TDS2 + TDS3 + TCS + advance tax + self-assessment tax. Rules **A-103, A-104, A-108, A-109**.
**A-113**: if TDS credit is claimed but the corresponding receipt is not offered to tax anywhere in the return, raise a blocking error naming the deductor.

---

## 8. SCREEN 5 — VERIFY YOUR TAX LIABILITY DETAILS

*(Reference: screenshot 5)* Almost entirely computed. Only D6, D7, D8, D10 are user-editable, exactly as the portal shows.

### 8.1 Computation of Income
- Gross Total Income (computed, read-only)
- Total Deductions (computed, read-only)
- **C2. Total Income (B4 − C1)** — **A-24**: the difference, or **zero if negative**. Round to the nearest ₹10 per s.288A. *(In the sample: GTI ₹2,63,366 − 0 = ₹2,63,366 → displayed ₹2,63,370. Implement this rounding; getting it wrong is a common rejection.)*
- Note line when LTCG 112A is included, mirroring the portal.

### 8.2 Computation of Tax Payable

| Line | Field | Logic |
|---|---|---|
| D1 | Tax payable on total income | Computed from slabs. Provide a "Show Computation" drawer with the slab-wise breakup |
| D2 | Rebate u/s 87A | Computed. **New regime (A-191)**: not available where total income excluding LTCG exceeds **₹12,70,590** — implement the statutory rebate with **marginal relief**, which is what produces that threshold. **Old regime (A-192, A-23)**: ₹12,500 where total income ≤ ₹5,00,000; not available where total income including LTCG 7a(iii) exceeds ₹5,00,000 |
| D3 | Tax payable after rebate | **A-25**: D1 − D2 |
| D4 | Health & Education Cess @ 4% | On D3 |
| D5 | Total Tax & Cess | **A-26**: D3 + D4 |
| D6 | Relief u/s 89 | **User input.** **A-125**: blocked where 17(1), 17(2), 17(3) and family pension are all zero/blank. **D-1**: claiming relief without Form 10E filed raises a Category D advisory — capture a "Form 10E filed" checkbox with acknowledgement number |
| — | Balance tax after relief | D5 − D6 |

**Slab constants — `config/ay2026-27/constants.json`, verify against the CBDT utility before release:**

*New regime (default), FY 2025-26:* 0–₹4,00,000 nil · ₹4,00,001–₹8,00,000 5% · ₹8,00,001–₹12,00,000 10% · ₹12,00,001–₹16,00,000 15% · ₹16,00,001–₹20,00,000 20% · ₹20,00,001–₹24,00,000 25% · above ₹24,00,000 30%. Rebate u/s 87A up to ₹60,000 where total income (excluding special-rate income) ≤ ₹12,00,000, with marginal relief above.

*Old regime:* 0–₹2,50,000 nil (₹3,00,000 for age ≥ 60, ₹5,00,000 for age ≥ 80) · next slab to ₹5,00,000 5% · ₹5,00,001–₹10,00,000 20% · above ₹10,00,000 30%. Rebate u/s 87A ₹12,500 where total income ≤ ₹5,00,000.

*Both:* cess 4%. LTCG u/s 112A taxed at 12.5% on the amount exceeding ₹1,25,000 — but note ITR-1 permits LTCG 112A only up to ₹1,25,000 (**A-217**), so within ITR-1 the LTCG tax is always nil. Screenshot 5 confirms this with the note "The Total Income Field includes LTCG u/s 112A. However, no tax would be payable on the said income." Reproduce that note verbatim in behaviour.

### 8.3 Total Interest and Fee

| Line | Field | Logic |
|---|---|---|
| D7 | Interest u/s 234A | **User-editable with computed default.** 1% per month or part, on unpaid tax, from the day after the 139(1) due date to the date of filing. Provide "Show Computation" |
| D8 | Interest u/s 234B | **User-editable with computed default.** 1% per month on assessed tax where advance tax paid < 90%, from 1 April of the AY |
| D9 | Interest u/s 234C | **Computed, read-only.** Quarterly shortfall against 15/45/75/100% thresholds, using the quarterly dividend/income breakup. "Show Computation" drawer |
| D10 | Fee u/s 234F | **User-editable with computed default.** ₹5,000; ₹1,000 where total income ≤ ₹5,00,000; nil where filed on or before the due date or where total income is below the basic exemption limit |
| D10a | Fee for furnishing revised return u/s 234-I | **Computed, read-only.** **A-324**: ₹1,000 where filed after 31.12.2026 u/s 139(5) and total income ≤ ₹5 lakh. **A-328**: ₹5,000 where filed after 31.12.2026 u/s 139(5) and total income > ₹5 lakh. Otherwise nil |
| — | Total Interest and Fee Payable | **A-28**: D7 + D8 + D9 + D10 + D10a |

### 8.4 D11 — Total Tax, Fee and Interest
**A-27 / A-140**: D5 + D7 + D8 + D9 + D10 + D10a − D6. Display the three sub-lines the portal shows (balance tax after relief, total interest and fee payable, total tax fee and interest).

---

## 9. SCREEN 6 — TAX SUMMARY DETAILS

*(Reference: screenshots 6 and 7)* Entirely read-only. This is the reviewer's screen — no inputs at all.

- **Headline banner**: "You are eligible for a refund of ₹X" (green) or "You have a tax payable of ₹X" (amber) or "You have no tax payable and no refund due" (neutral).
- **A. Gross Total Income** — the four head-wise lines plus the total.
- **B. Total Deductions** — every Chapter VI-A section listed individually with its amount (0 where unclaimed), exactly as the portal does. Do not collapse zeros.
- **C. Total Taxable Income (A − B)**.
- **D. Total Tax, Fee and Interest** — every line from Screen 5.
- **E. Total Tax Paid** — TDS1, TDS2, TDS3, TCS, D12(a) advance tax, D12(b) self-assessment tax, total.
- **Amount Payable / Refund**: total tax liability; total taxes paid D12(a+b+c+d); **Refund (D12 − D11) if D12 > D11** per **A-105**; **Tax Payable (D11 − D12)** per **A-106**. Refund is rounded down to the nearest ₹10; refunds below ₹100 are not issued — show an informational note.
- Primary action: **Proceed to Validation**. Secondary: **Back to Summary**, **Export computation sheet (PDF)**.

---

## 10. SCREEN 7 — VALIDATION & JSON

*(Reference: screenshot 7)* This is the screen that makes or breaks the product.

### 10.1 Behaviour
On entry, run the **complete** rule registry — all Categories A, B and D — plus a structural validation of the generated JSON against `ITR-1_2026_Main_V1_1.json` using a real JSON Schema validator (AJV or equivalent). **Validate the actual output artifact, not the model.**

### 10.2 Success state
```
┌─────────────────────────────────────┐
│ ✓  Validation successful!           │
│    No errors were found             │
└─────────────────────────────────────┘
[ Back ]              [ Download JSON ]  [ Preview ]
```
Match the portal's presentation. **Download JSON** is enabled only in this state. **Preview** renders the full ITR-1 form as a PDF for review.

### 10.3 Error state
Group errors by screen, ordered by screen sequence, then by severity:

```
✗ Validation failed — 3 errors, 2 warnings

  PERSONAL INFORMATION  (1 error)
  ● [A-151] Old tax regime cannot be selected for a return filed
    under section 139(4) after the due date.
    → Change the opt-out response to "No", or change the filing section.
    [Go to field]

  TOTAL DEDUCTIONS  (2 errors)
  ● [A-120] Deduction u/s 80CCD(2) of ₹60,000 exceeds 14% of salary
    (₹46,200) for a Central Government employer.
    → Reduce the claim to ₹46,200 or lower.
    [Go to field]
  ...

  ADVISORIES  (2)
  ▲ [B-3] Section 194IA has been selected in Schedule TDS2. Income
    taxable at special rates cannot be reported in ITR-1; ITR-2 may
    be required. This will not block the JSON but may result in a
    notice u/s 139(9).
  ▲ [D-1] Relief u/s 89 has been claimed. Form 10E must be filed
    separately before submitting the return.
```

**Severity handling:**
- **Category A** → blocks download. Red.
- **Category B** → does not block; requires an explicit "I understand" acknowledgement checkbox before download, and the acknowledgement is stored in the audit log.
- **Category D** → does not block; informational, acknowledged the same way.

Every error must carry: rule ID, plain-English message, the offending value, the permitted value, and a working deep link. **An error message that does not tell the preparer what number to change is a defect.**

### 10.4 Validation report export
Downloadable PDF/CSV: PAN, AY, timestamp, rule set version, schema version, full error and advisory list, and a green attestation when clean. This is the artifact a preparer files as proof of diligence.

---

## 11. JSON GENERATION

### 11.1 Non-negotiables
1. Validate the generated JSON against the attached schema **inside the generation pipeline**. Never emit an unvalidated file.
2. **Omit empty nodes.** Do not emit `null`, `""`, or zero-valued optional objects — the portal rejects several of these. Emit `0` only for numeric fields the schema marks mandatory.
3. **Types are exact.** Amounts are JSON numbers (integers, rupees, no decimals, no thousands separators, no currency symbol). Dates are the schema's format (typically `YYYY-MM-DD`). Flags are the schema's literal enum tokens (`Y`/`N` or `true`/`false` — take whichever the schema declares).
4. **Element order follows the schema's declared order.** Some validators are order-sensitive; do not rely on object-key insertion luck — serialize from an ordered template derived from the schema.
5. **Rounding** is applied at the model layer before serialization, never in the UI: total income to the nearest ₹10 (s.288A); tax, interest and refund to the nearest ₹10 (s.288B).

### 11.2 Root structure
Build the root from the attached schema. The expected skeleton is:

```
ITR
└── ITR1
    ├── CreationInfo          (SWVersionNo, SWCreatedBy, JSONCreatedBy,
    │                          JSONCreationDate, IntermediaryCity, Digest)
    ├── Form_ITR1             (FormName, Description, AssessmentYear,
    │                          SchemaVer, FormVer)
    ├── PersonalInfo          (AssesseeName, PAN, Address, DOB,
    │                          EmployerCategory, AadhaarCardNo)
    ├── FilingStatus          (ReturnFileSec, SeventhProvisio139(1),
    │                          NewTaxRegime / OptOutNewTaxRegime,
    │                          RepresentativeAssessee ...)
    ├── ITR1_IncomeDeductions (Salary block, HP block, other sources,
    │                          GrossTotIncome, DeductUndChapVIA,
    │                          TotalIncome, exempt income schedules,
    │                          Schedule80D / 80G / 80GGA / 80GGC / 80DD /
    │                          80U / 80C / 80E / 80EE / 80EEA / 80EEB /
    │                          10(13A) / 24(b))
    ├── ITR1_TaxComputation   (TotalTaxPayable, Rebate87A, EducationCess,
    │                          GrossTaxLiability, Section89, IntrstPay,
    │                          TotalIntrstPay, TotTaxPlusIntrstPay)
    ├── TaxPaid               (TaxesPaid: TDS1, TDS2, TDS3, TCS,
    │                          AdvanceTax, SelfAssessmentTax, TotalTaxesPaid;
    │                          BalTaxPayable)
    ├── Refund                (RefundDue, BankAccountDtls)
    ├── Schedule TDS1 / TDS2 / TDS3 / TCS / IT
    └── Verification          (Declaration, Capacity, Place, Date)
```
**Verify every one of these names against the attached JSON schema and correct them where they differ.** The names above are a navigational aid, not a specification.

### 11.3 CreationInfo
- `SWVersionNo`: the stacos.ai module version.
- `SWCreatedBy`: the CBDT-issued software provider code for stacos.ai. **Configurable — never hard-code.** *(If no code has been issued, register as a software provider; the validation rules PDF states that non-compliant utilities are liable to be blacklisted without notice.)*
- `JSONCreatedBy`: same code.
- `JSONCreationDate`: generation date in the schema's format.
- `IntermediaryCity`, `Digest`: per schema. Compute `Digest` by the CBDT-specified method if the schema mandates one.

### 11.4 Filename
`{PAN}_{AY}_ITR1_{YYYYMMDDHHmmss}.json` — e.g. `AHKPT5171E_2026-27_ITR1_20260807132045.json`.

### 11.5 Round-trip import
Accept a previously generated JSON, map it back into the model, **recompute every derived field**, and re-run validation. If a recomputed value differs from the imported value, flag it as a discrepancy rather than silently overwriting — this is how preparers catch a corrupted draft.

---

## 12. GOLDEN TEST CASE (from the attached screenshots)

Seed this as an automated regression test. Every build must reproduce it exactly.

**Input**
- Name: ANSHAL THAKUR · PAN: AHKPT5171E · DOB: 28-Dec-1986 · Aadhaar ending 4638
- Address: Flat No 202, Sundaram Block, Mansarovar Garden, Sinha Library Road, Patna, Bihar 800001, India
- Mobile 91-9199366399 · Email anshal.thakur@gmail.com
- Nature of employment: **Others**
- Filing section: **139(4) — belated** · Opt out of new regime: **No** → **NEW REGIME** (and old regime must be *disabled* by A-151)
- Representative assessee: No · Seventh proviso: No
- Salary: gross ₹3,30,000 · exempt allowances ₹0 · net ₹3,30,000 · deductions u/s 16 ₹75,000 · chargeable ₹2,55,000
- House property: ₹0 · Other sources: ₹8,366 · LTCG 112A: ₹0
- Deductions: all ₹0 (80CCD(2) ₹0, 80CCH ₹0 with the "not allowed for employment category other than Central Government" note visible)
- TDS1: TAN MUMS27065D, SKORYDOV SYSTEMS PRIVATE LIMITED, salary ₹3,30,000, TDS ₹24,500

**Expected output**
| Value | Expected |
|---|---|
| Gross Total Income | ₹2,63,366 |
| Total Deductions | ₹0 |
| Total Income (rounded) | **₹2,63,370** |
| Tax payable on total income | ₹0 |
| Rebate u/s 87A | ₹0 |
| Cess | ₹0 |
| Total tax & cess | ₹0 |
| Interest 234A/B/C, fee 234F, 234-I | ₹0 |
| Total tax, fee and interest | ₹0 |
| Total taxes paid | ₹24,500 |
| **Refund** | **₹24,500** |
| Validation | **Successful — no errors** |

Note that despite the belated filing, 234F is ₹0 because total income is below the basic exemption limit. Your 234F logic must produce this.

### 12.1 Additional test scenarios to build
1. Old regime, filed 139(1) before due date, full Chapter VI-A claims at every cap boundary (exactly at, one rupee over, one rupee under).
2. Old regime attempted with a 139(4) filing → **A-151** must block.
3. 139(5) revised where the original was 139(4) with old regime → **A-189** must block.
4. Total income ₹50,00,001 → **A-117** must block with the ITR-2 message.
5. LTCG 112A ₹1,25,001 → **A-217** must block.
6. Senior citizen (DOB 01.04.1966) claiming 80TTA → **A-13** must block; claiming 80TTB → allowed.
7. DOB 02.04.1966 claiming 80TTB → **A-15** must block.
8. Salary income with Nature of Employment = 'Not Applicable' → **A-210** must block.
9. TDS2 with section 194IA → **B-3** advisory, JSON still downloadable after acknowledgement.
10. Relief u/s 89 claimed with all salary components zero → **A-125** blocks; with salary present but no Form 10E → **D-1** advisory only.
11. Self-occupied HP with ₹2,50,000 interest, old regime → **A-48** blocks at ₹2,00,000; same in new regime → **A-162** blocks at ₹0.
12. Co-owned property with shares summing to 95% → **A-295** blocks.
13. 80G cash donation of ₹2,500 to a single PAN → **A-88** must zero the eligible amount.
14. Exempt income with the same section selected twice → **A-184** blocks.
15. Secondary address marked "not same as primary" but entered identically → **A-339** blocks.
16. Every rule in the registry must have at least one passing and one failing fixture. **Target: 100% rule coverage in the test suite.** A rule with no failing fixture is an untested rule.

---

## 13. UX REQUIREMENTS

- **Indian number formatting** throughout: `₹2,63,366` (lakh/crore grouping), never `₹263,366`.
- Amount inputs accept digits only; strip commas, spaces and `₹` on paste; right-aligned; no decimals.
- Every computed field visually distinct (grey fill, no border) and non-focusable, matching the portal.
- Inline errors appear **below** the field in red with the rule ID in small type; screen-level errors appear in a summary panel at the top with anchor links.
- "Show Computation" drawers for tax payable, 234A, 234B, 234C, 87A rebate with marginal relief, HRA least-of, and the standard deduction — showing the arithmetic line by line. Preparers must be able to defend every number.
- Section-limit helper text is **live**: "₹1,50,000 limit · ₹40,000 remaining" updating as the user types.
- Keyboard-first: Tab order follows visual order, Enter confirms the section, Ctrl+S saves.
- Accessible: WCAG 2.1 AA, proper labels, ARIA live regions for computed value changes, 4.5:1 contrast.
- Responsive down to tablet; the left menu collapses to a hamburger below 1024px.
- English and Hindi UI strings from day one — all strings externalised, no hard-coded text.

---

## 14. ACCEPTANCE CRITERIA

The feature ships only when all of the following are true:

1. All 339 Category A, 9 Category B and 1 Category D rules are implemented in the registry, each with a unique ID matching the CBDT numbering, and each with passing and failing test fixtures.
2. The golden test case reproduces every expected value exactly, including the ₹2,63,370 rounding.
3. Generated JSON validates against `ITR-1_2026_Main_V1_1.json` with a standards-compliant JSON Schema validator, zero errors.
4. At least 10 real, varied returns upload to the government portal without a single portal-side error.
5. Round-trip import of a generated JSON reproduces an identical model.
6. The rule set version, schema version and constants version are all displayed in the UI footer and stamped into every generated JSON and validation report.
7. A new CBDT rule can be added by editing a JSON file and adding a fixture — no code change, no deployment of application logic.
8. Audit log captures every field change, validation run and JSON generation.

---

## 15. NOTES FOR THE IMPLEMENTER

- The validation rules document warns that non-compliant preparation software is liable to be blacklisted without notice, and that no return prepared with blacklisted software may be uploaded until the provider corrects it. Treat rule fidelity as a compliance obligation, not a quality target.
- Where a rule's wording is ambiguous (several are — e.g. **A-88** on cash donations, **A-268** on date of formation for an Individual), implement it **literally as written**, add a code comment quoting the rule text verbatim, and log it in an `AMBIGUOUS_RULES.md` for confirmation against the CBDT utility's behaviour.
- Rules **A-325** and **A-326** are textually identical in the source document. Implement once, register both IDs pointing at the same assertion.
- Rules **A-207** and **A-208** (and **A-206**/**A-209**) are near-duplicates differing only in the words "deduction"/"donation". Implement the stricter reading: details are required whenever the deduction exceeds zero.
- Build the constants file so that AY 2027-28 can be added alongside AY 2026-27 without touching AY 2026-27's values. Season rollover is annual and predictable — design for it now.
