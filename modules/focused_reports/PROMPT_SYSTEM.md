Focused prompt definitions
==========================

`prompt_specs.PROMPT_SPECS` contains one frozen `PromptSpec` per catalog key.
Question text is taken directly from `question_catalog`; titles and reasoning
instructions are authored per question. Shared evidence declarations and
output archetypes are reused. Nothing here registers additional handlers.

`build_focused_prompt(question_key, language, evidence, customer_context=None)`
returns a prompt string and never calls a model. Evidence is a mapping from
the spec's required keys to nonempty, backend-produced fact text. Missing,
blank or explicit unavailable sections fail closed. A negative finding such
as no detected yoga is valid evidence. Extra sections are ignored.

The assembler checks catalog/spec identity and EN/HI (including en-US, en-IN,
hi-IN aliases), normalizes customer-facing dates with Q5.6, and combines the
shared language master, exact question, specific reasoning, required evidence
and one META/REPORT schema. `customer_context` permits only `situation` and
`report_period` text; identity fields are not forwarded. Callers must keep
free-text context free of unnecessary personal details. Context is not evidence.

Promotion still uses the same four career summary blocks and the same
Jupiter/Saturn/Rahu renderer. The existing transit text is split at its planet
headings and rejoined verbatim. Residence and motion periods retain their
independent dates. Its old EN/HI files now contain only Promotion-specific
instructions; master rules, language style and output structure are shared.

Capability meanings and evidence provenance
------------------------------------------

* IMPLEMENTED: all 61 catalog keys, across all 8 families (Career & Job, Money & Business,
  Marriage, Relationship, Foreign & Relocation, Education, Property & Home, Life Direction),
  have collectors and focused handlers.
* EVIDENCE_AVAILABLE: minimum facts/calculations exist, but no focused handler
  is registered. This does not mean the assembled evidence payload exists or
  that any particular customer's data is complete.
* EVIDENCE_MISSING: a requirement explicitly identifies an unavailable fact
  or calculation. The schema records that exact missing requirement.

For the current catalog all declared minimum facts exist; none require an
unavailable calculation. This is deliberately not a claim that all evidence
builders are implemented. Sources are attached to each EvidenceRequirement:

* `calculate_full_kundali` supplies natal positions for a fully specified
  person. `build_house_lord_facts` supplies signs, lords and placements,
  including empty houses. These support question-specific interpretation;
  a new deterministic marriage, education, property or strength score is not
  needed or declared.
* Existing summary builders supply computed career/wealth yogas and current
  plus upcoming MD/AD. Multi-year questions require the full existing MD/AD
  sequence, not the shorter window summary.
* Existing transit functions supply sign boundaries and dated motion for
  selected planets. Their attribution to a question remains focused-builder
  work; no second ephemeris or transit engine is introduced.
* Dual questions require both natal fact sets and actual compatibility facts.
  `service_love.run_love_compatibility` already calculates both full charts
  and Ashtakoot. Timing questions additionally require separately attributed
  MD/AD and Jupiter/Saturn context for both people. No DOB-only fallback is
  acceptable as a substitute for the declared full-chart requirements.

The current catalog contains single and dual modes only. Education questions
use the learner's own chart, not a parent's chart. No CHILD questions were
invented. No catalog question is held/conditional; capability status here
describes fact availability only and is independent of purchasing activation.

Career family implementation
----------------------------

`career_keys.py` explicitly lists the 12 registered keys; new catalog entries
are not automatically enabled. `career_evidence.collect_career_evidence`
selects only required sections, and rejects unsupported requirements. Promotion
uses this same collector while retaining its public prompt/result structure.
Other Career handlers bind their exact key to `build_career_report_prompt`.
All use the shared assembler, paid AI client, structured validator and dates.

Eleven keys use birth chart, house/lord, career yoga and short MD/AD summaries
plus Jupiter/Saturn/Rahu residence and motion: promotion_timing,
career_improvement_timing, career_growth_delay_reason, next_strong_career_period,
salary_growth_timing, work_recognition_timing, job_change_now, new_job_timing,
best_period_to_switch, job_search_start_timing, job_gap_easing.

`best_career_years` substitutes `dasha_sequence` for the short MD/AD summary.
Its internal evidence horizon is five years. The collector includes every
existing MD/AD window overlapping those years, preserves original dates and
rejects missing/gapped coverage. The same transit collector samples the same
three planets over that horizon; no additional astrology engine is introduced.
Other Career questions keep the validated 12-month horizon. Neither horizon
changes the customer question. Historical and far-future Dasha windows outside
the selected horizon are not sent.

Every Career result uses the shared PDF adapter and its own prompt-spec title.
The other 38 catalog keys still raise FocusedReportNotImplementedError. Foreign
Work is in the Foreign category, not Career. The illustrative Job Stability,
Job vs Business and Government Job names are not additional catalog questions.

Money and Business family implementation
----------------------------------------

`money_business_keys.py` explicitly registers five money keys and six business
keys. `money_business_evidence.py` exposes separate money/business entry points
over one shared collector. Each selects exactly the sections declared by its
spec. Money selects natal, house/lord, wealth yoga, MD/AD and Jupiter/Saturn.
Business additionally selects career yogas, as required by its existing specs.
No Rahu/Ketu transit evidence, gemstone, divisional chart or strength score is
sent. Shared summary calculations remain unchanged; their unrelated output is
discarded. The existing transit builder accepts a restricted planet selection
while retaining its original three-planet default for Career.

`money_growth_periods` and `best_business_periods` replace the short MD/AD
summary with the existing validated multi-year sequence and use five years of
Jupiter/Saturn coverage. The remaining nine keys use 12 months. The frozen
customer questions and unique objectives/focus/emphasis are unchanged.

Prompt-spec changes: all 11 are marked implemented; both periods questions
use long Dasha requirements and multi-year timing instructions. All 11 receive
explicit financial-advice and financial-guarantee boundaries. Business adds
transaction/borrowing/employment/closure/partnership decision boundaries.
Debt prohibits guaranteed disappearance or repayment dates; start/expansion
prohibit commands to proceed; partnership prohibits reliability/success promises.

All handlers use the shared Luna client, structured validation and Q5.6 dates.
The shared PDF adapter selects the existing financial/business disclaimer and
rejects leaked wealth-summary identifiers. There is no payment, delivery or
route integration. Unsupported categories remain Marriage (6), Relationship
(9), Foreign (6), Education (4), Property (5) and Life (8).
