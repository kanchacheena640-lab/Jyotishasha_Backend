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
route integration. Other categories are Marriage (6), Relationship (9),
Foreign (6), Education (4), Property (5) and Life (10).

63 focused reports, 8 categories, SELF 54 / DUAL 9
-------------------------------------------------

The catalog is 63 questions across 14 core intents (12 single-question-per-
family style intents plus the 2 dual-relationship intents already documented
above). SELF 54 / DUAL 9, unchanged in composition from the original 52/9 --
the 2 new questions are both SELF.

Obstacle/remedy semantics (shared, not duplicated)
---------------------------------------------------

`prompt_contract.Archetype` gained two shared archetypes, `OBSTACLES` and
`STRENGTHS_NOW`, each with its own fixed EN/HI heading set in
`master_contract.SECTIONS` -- the same one-archetype-many-questions pattern
every other archetype already uses, not a new mechanism.

Obstacle/challenge interpretation itself was never new: `DIAGNOSTIC` (delay/
easing questions) and `TIMING`'s own optional "Slower or Watch Period" section
already asked Luna to interpret challenging evidence. What changed is a short,
always-active master-contract guardrail (both languages): prefer 2-3 of the
most meaningful factors over an exhaustive list, and never name a "dosha"
unless that exact dosha is itself one of the supplied facts (no dosha fact is
supplied to any focused report today, so none can be named). This applies
everywhere a report happens to touch challenges; it is never a forced section.

`PromptSpec.remedies` (bool, default False) is the one new per-question flag.
When True, `prompt_assembler.build_focused_prompt()` appends ONE shared
instruction block, `master_contract.REMEDY_INSTRUCTION` (EN/HI), to the
prompt -- practical guidance preferred, a Jyotish/spiritual remedy only when
evidence-grounded, never a guaranteed outcome, never a prescribed expensive
gemstone, never medical/legal/financial advice. Only `major_kundali_obstacles`
sets `remedies=True` today; the flag exists so a future question can opt in
without duplicating the instruction text.

Timing-overlap clarity: the existing master-contract paragraph that already
separates "Sign residence" from "Motion" (no new transit calculation) gained
one more sentence, in both languages, asking Luna to narrate a retrograde
sub-period INSIDE a broader supportive residence window as two distinct
halves (a stronger direct portion, a slower review portion) rather than as
one contradictory block.

New diagnostic Birth + Current reports (#62/#63)
--------------------------------------------------

`kundali_obstacles`/`major_kundali_obstacles` and `kundali_strengths`/
`major_kundali_strengths` are 2 new core intents (Life Direction, SELF),
each a single question. Both are whole-chart diagnostics, deliberately
distinct from the other 8 Life-family questions: `life_direction_and_strengths`
(natal-only, no current-activation dimension -- unchanged, still natal-only)
and `life_turning_points` (timing of phase changes, not an obstacle/strength
inventory). `natural_strengths` itself is untouched.

Evidence is entirely reused, not invented: the SAME `NATAL`/`HOUSES`/`CAREER`/
`WEALTH`/`MD_AD`/`JUPITER`/`SATURN`/`RAHU` `EvidenceRequirement` objects every
other focused report already uses, composed as one Birth base (natal, all 12
houses unfiltered, career + wealth yoga) plus one Current layer (12-month
MD/AD, Jupiter/Saturn/Rahu). `life_evidence.py` gained two small, per-question
overrides -- which natal planets and which transit planets to surface -- so
these 2 whole-chart questions can include Mars/Venus/Rahu/Ketu and Rahu
transit (facts `calculate_full_kundali` already computes); the other 8
Life questions keep their exact original planet/transit selection.

App download CTA
-----------------

The focused PDF adapter now always passes `app_download` (heading, benefit
text, `app_config.JYOTISHASHA_PLAY_STORE_URL`, `JYOTISHASHA_APP_STORE_URL`) --
the SAME component, labels and URL every one of the 25 standard paid reports
already renders via the shared template's own fixed, final section (after
all analysis and the disclaimer). `templates/report_template.html` renders
the Play Store URL as a real `<a href="{{ app_download.play_store_url }}">`
anchor around the same visible text as before, so WeasyPrint preserves it as
a clickable PDF URI annotation pointing at the canonical
`app_config.JYOTISHASHA_PLAY_STORE_URL` -- no second or invented URL. Every
report that already used this shared template and component (the 25
standard paid reports, the relationship report, and now focused reports)
inherits this same clickable link with no per-report change.
