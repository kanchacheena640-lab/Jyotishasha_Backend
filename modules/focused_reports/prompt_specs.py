"""One authored reasoning definition per existing catalog question.

Customer wording is referenced from the catalog, never maintained in parallel.
These specifications do not register handlers or activate purchasing.
"""
from types import MappingProxyType

from modules.intents.intent_contract import LocalizedText
from modules.intents.question_catalog import get_question
from modules.focused_reports.prompt_contract import Archetype as A, Capability as C, PromptSpec
from modules.focused_reports import evidence_requirements as E
from modules.focused_reports.career_keys import CAREER_QUESTION_KEYS
from modules.focused_reports.money_business_keys import MONEY_BUSINESS_QUESTION_KEYS, MULTI_YEAR_KEYS
from modules.focused_reports.marriage_keys import MARRIAGE_QUESTION_KEYS, MARRIAGE_MULTI_YEAR_KEYS
from modules.focused_reports.relationship_keys import RELATIONSHIP_QUESTION_KEYS, RELATIONSHIP_TIMING_KEYS
from modules.focused_reports.foreign_keys import FOREIGN_HORIZONS
from modules.focused_reports.education_keys import EDUCATION_HORIZONS
from modules.focused_reports.property_keys import PROPERTY_HORIZONS
from modules.focused_reports.life_keys import LIFE_HORIZONS, DIAGNOSTIC_BIRTH_CURRENT_KEYS


TIMING = {
    "best_windows": "Compare only supplied dated windows; rank the strongest supported periods and explain the difference.",
    "when_begins": "Distinguish present conditions from the first supported easing or opening window; never promise an event date.",
    "delay_reason": "Explain current pressure first; identify easing only where supplied MD/AD and transit dates support it.",
    "current_period": "Assess the present first, then compare useful upcoming windows within the supplied evidence horizon.",
    "easing_period": "Explain whether pressure is persistent, mixed or easing; use only supported windows, not a deadline.",
    "care_periods": "Identify evidence-supported periods needing care, balanced with supportive factors; do not force a warning.",
    "overview": "Prioritize the requested assessment; do not attach event dates to undated natal indications.",
    "guidance": "Prioritize practical focus; mention timing only when dated evidence is supplied and relevant.",
}
DECISION = "Describe supportive/challenging conditions and practical constraints, not commands to resign, buy, sell or change a business."
SELF = "Use only this person's chart; do not infer another person's intentions, feelings, choices or future actions, or silently perform two-chart compatibility."
DUAL = "Keep both full birth charts separately attributed; use only supplied compatibility facts. Never claim private feelings, fidelity or future choices. Never assert that a partner loves, does not love, will marry, will leave, is cheating, is loyal/disloyal, will consent/refuse, or has a hidden motive. No guarantee of marriage, breakup, reconciliation, long-term success, divorce or engagement. No therapy diagnosis. Existing Ashtakoot scores are matching facts, never love percentages or outcome probabilities. This is not the separate Relationship Future product."
FINANCIAL_BOUNDARY = "Astrological context only. No investment, trading, lending, borrowing, tax or regulated financial advice. No guaranteed profit, income, salary, investment returns, debt repayment or wealth creation."
BUSINESS_BOUNDARY = "Do not command the customer to invest money, borrow money, take a loan, quit employment, close a business, sign a partnership, buy/sell securities or make a specific financial transaction."
LIFE_BOUNDARY = "Preserve customer agency. No fixed destiny, unavoidable event, guaranteed success/failure, exact death/longevity event, inevitable accident, illness, divorce/marriage, job loss or financial gain/loss. Do not diagnose mental illness, physical disease, fertility conditions, addiction or personality disorders. Do not instruct the customer to quit a job, end a relationship, make an investment, avoid medical treatment, make legal decisions, relocate or abandon education. No life success percentage, destiny score, strength percentage, risk probability, event probability or arbitrary ranking. Describe themes, tendencies, strengths, challenges and supported periods only."
QUESTION_BOUNDARIES = {
    "property_delay_reason": ("Property delay is not permanent blockage; identify easing only where supplied dated evidence supports it.",),
    "study_progress_improvement": ("Study difficulties are not permanent blockage; identify easing only from supplied dated evidence.",),
    "foreign_plans_delay_reason": ("Delay is not permanent blockage; do not treat administrative obstacles as chart-proven facts.",),
    "marriage_delay_reason": ("Delay is not permanent destiny or permanent denial of marriage; do not assign blame.",),
    "relationship_to_marriage_window": ("Assess only the customer's own commitment timing. Do not invent a partner's chart, intentions, feelings, willingness or future decisions; never claim the current partner will definitely marry the customer.",),
    "debt_pressure_easing": ("Never claim debt will definitely disappear or be repaid by a specific date.",),
    "business_start_timing": ("Provide launch timing context, not a command to proceed.",),
    "business_expansion_timing": ("Provide expansion timing context, not a command to proceed.",),
    "new_venture_partnership_timing": ("Do not guarantee partner reliability or business success.",),
}
BOUNDARIES = {
    "career_growth_timing": ("No guaranteed promotion, raise, salary amount, continued employment or definite job-loss prediction.",),
    "job_change_timing": (DECISION, "Do not tell the user to resign or promise an offer, selection or appointment. No guaranteed continued employment or definite job loss."),
    "money_improvement_timing": (FINANCIAL_BOUNDARY,),
    "business_timing": (DECISION, FINANCIAL_BOUNDARY, BUSINESS_BOUNDARY, "No guaranteed profit, funding, commercial success or partner behavior."),
    "marriage_timing": ("No guarantee that marriage will happen, exact marriage date, engagement date, proposal, partner behaviour, family approval, relationship conversion or legal marriage outcome. No spouse identity or prediction about a partner's consent. Describe supportive, mixed or easing windows only from supplied backend evidence.",),
    "relationship_marriage_potential": ("No marriage guarantee or substitute for mutual consent.",),
    "relationship_strengths_and_challenges": ("No breakup, cheating or private-intention predictions.",),
    "foreign_move_timing": (DECISION, "No guarantee of visa, immigration approval, citizenship, residency, university admission, foreign job, relocation or settlement. No legal/immigration advice. Do not tell the customer to resign, migrate, invest or relocate. Describe supportive, mixed or challenging astrological periods only; no outcome probabilities or arbitrary scores."),
    "study_exam_timing": ("No guaranteed exam success, pass/fail outcome, marks/rank, admission, scholarship, institution acceptance, visa or degree completion. No marks/rank prediction, exam success percentage, admission probability or arbitrary education score. Do not advise abandoning education based on astrology. Describe astrological strengths, challenges and supportive timing only. Use the learner's own chart; do not infer a child's chart from a parent's.",),
    "property_timing": (DECISION, "Astrology is not financial, legal, mortgage, investment, tax, title or real-estate due-diligence advice. No guaranteed property purchase, ownership, loan approval, registration, possession, price appreciation, investment return, dispute outcome or construction completion. Do not tell the customer to buy a specific property, take a loan, borrow money, invest a specific amount, sign an agreement or ignore legal/title verification. Practical financial/legal verification remains outside the astrology conclusion. No purchase probability, loan probability, property-success percentage or investment-return score."),
    "life_turning_points": ("No fatalism, exact event dates, health diagnoses or guaranteed life events.", LIFE_BOUNDARY),
    "life_direction_and_strengths": ("Describe tendencies, not fixed personality labels, ability scores or a predetermined destiny.", LIFE_BOUNDARY),
    "kundali_obstacles": ("Identify only 2-4 of the most meaningful obstacles, never an exhaustive negativity list. Never name a "
        "dosha unless that exact dosha is itself supplied as a fact. No deterministic doom, no guaranteed misfortune. Remedies "
        "are practical-first; a Jyotish/spiritual remedy only when reasonably tied to the evidence; never an expensive gemstone "
        "prescription, never medical, legal or financial advice, never a guaranteed remedy outcome.", LIFE_BOUNDARY),
    "kundali_strengths": ("Identify only 2-4 of the most meaningful strengths, never an exhaustive list. Distinguish durable natal "
        "strengths from what current Dasha/transit evidence actually activates now; never claim a strength guarantees an outcome.",
        LIFE_BOUNDARY),
}
# The one intent whose reports may include the shared remedy instruction (master_contract.REMEDY_INSTRUCTION).
# A per-question set, not a per-family default -- remedies are never forced into a report where they make no sense.
REMEDY_KEYS = frozenset({"major_kundali_obstacles"})

_specs = {}


def _group(intent, evidence, rows):
    for key, en, hi, objective, focus, emphasis in rows:
        q = get_question(key)
        if q.intent_slug != intent or key in _specs:
            raise ValueError(f"Duplicate or inconsistent prompt definition: {key}")
        archetype = (A.OBSTACLES if intent == "kundali_obstacles" else
                     A.STRENGTHS_NOW if intent == "kundali_strengths" else
                     A.DIAGNOSTIC if q.answer_mode in ("delay_reason", "easing_period") else
                     A.DIRECTION if q.answer_mode == "guidance" or intent == "life_direction_and_strengths" else
                     A.COMPATIBILITY if q.person_mode == "dual" and q.answer_mode == "overview" else A.TIMING)
        requirements = evidence
        if q.person_mode == "dual" and q.answer_mode in ("current_period", "care_periods"):
            requirements = E.DUAL_TIMING
        timing = TIMING[q.answer_mode]
        if intent == "life_turning_points" or key == "best_career_years" or key in MULTI_YEAR_KEYS:
            requirements = tuple(r for r in requirements if r != E.MD_AD)
            if E.LONG_DASHA not in requirements:
                requirements += (E.LONG_DASHA,)
            timing = "Read the supplied multi-year MD/AD sequence; name major phase transitions and supported periods, not invented events or years outside the evidence."
        capability = C.EVIDENCE_MISSING if any(r.missing for r in requirements) else C.EVIDENCE_AVAILABLE
        if key in MARRIAGE_MULTI_YEAR_KEYS:
            requirements = tuple(r for r in requirements if r != E.MD_AD) + (E.LONG_DASHA,)
            timing += " Use the supplied multi-year MD/AD and Jupiter/Saturn coverage; do not infer dates outside that evidence."
        if key in CAREER_QUESTION_KEYS or key in MONEY_BUSINESS_QUESTION_KEYS or key in MARRIAGE_QUESTION_KEYS:
            capability = C.IMPLEMENTED
        if key in RELATIONSHIP_QUESTION_KEYS:
            if q.person_mode != "dual":
                raise ValueError("Relationship reports require dual person mode.")
            capability = C.IMPLEMENTED
            requirements = E.DUAL_TIMING if key in RELATIONSHIP_TIMING_KEYS else E.DUAL_COMPARISON
            timing = ("Compare both people's separately attributed MD/AD and Jupiter/Saturn windows over the supplied next 12 months; supportive or mixed periods do not determine consent or outcomes."
                      if key in RELATIONSHIP_TIMING_KEYS else
                      "Assess natal compatibility without event dates or timing claims; no timing evidence is supplied for this question.")
        if key in FOREIGN_HORIZONS:
            capability = C.IMPLEMENTED
            if FOREIGN_HORIZONS[key] == 60:
                requirements = tuple(r for r in requirements if r != E.MD_AD) + (E.LONG_DASHA,)
                timing += " Compare the supplied five-year MD/AD and Jupiter/Saturn/Rahu coverage; never infer dates beyond it."
            else:
                timing += " Use the supplied 12-month context for suitability or current diagnosis; do not invent longer-term windows."
        if key in EDUCATION_HORIZONS:
            capability = C.IMPLEMENTED
            if EDUCATION_HORIZONS[key] > 12:
                requirements = tuple(r for r in requirements if r != E.MD_AD) + (E.LONG_DASHA,)
                timing += " Compare the supplied three-year MD/AD and Jupiter/Saturn coverage for higher-education planning; never infer dates beyond it."
            else:
                timing += " Use the supplied 12-month study/preparation or current-progress context; do not invent longer-term windows."
        if key in PROPERTY_HORIZONS:
            capability = C.IMPLEMENTED
            if PROPERTY_HORIZONS[key] > 12:
                requirements = tuple(r for r in requirements if r != E.MD_AD) + (E.LONG_DASHA,)
                timing += " Compare the supplied five-year MD/AD and Jupiter/Saturn coverage for property/home windows; never infer dates beyond it."
            else:
                timing += " Assess the present first using the supplied 12-month current-period/diagnostic context; do not invent longer-term windows."
        if key in LIFE_HORIZONS:
            capability = C.IMPLEMENTED
            months = LIFE_HORIZONS[key]
            if key in DIAGNOSTIC_BIRTH_CURRENT_KEYS:
                # Birth + Current diagnostic: the SAME natal/house-lord/career-yoga/wealth-yoga facts every other
                # intent already reuses, plus the current MD/AD and Jupiter/Saturn/Rahu transit facts every timing
                # intent already reuses -- proven sufficient (no new calculation) precisely because every one of
                # these EvidenceRequirement objects already exists and is already used elsewhere in this file.
                requirements = (E.NATAL, E.HOUSES, E.CAREER, E.WEALTH, E.MD_AD, E.JUPITER, E.SATURN, E.RAHU)
                timing = ("Distinguish durable birth-chart facts (natal houses, lords and career/wealth yogas) from what the "
                          f"supplied {months}-month current MD/AD and Jupiter/Saturn/Rahu evidence actively activates right "
                          "now; no dates beyond the supplied evidence.")
            else:
                requirements = E.NATAL_DIRECTION if months is None else (
                    E.LIFE_TIMING if months > 12 else E.NATAL_DIRECTION + (E.MD_AD, E.JUPITER, E.SATURN))
                timing = ("Natal tendencies only; no timing evidence is supplied and no dates or future event windows should be invented."
                          if months is None else
                          TIMING[q.answer_mode] + f" Use only the supplied {months}-month continuous MD/AD and Jupiter/Saturn coverage; no dates beyond it.")
            if months == 12:
                timing += " Current context first; upcoming windows are supporting context, not a generic future forecast."
        _specs[key] = PromptSpec(key, intent, q.person_mode, LocalizedText(en, hi), q.question,
            objective, focus, timing, requirements, emphasis,
            ((DUAL if q.person_mode == "dual" else SELF),) + BOUNDARIES[intent] + QUESTION_BOUNDARIES.get(key, ()), archetype, capability,
            remedies=key in REMEDY_KEYS)


_group("career_growth_timing", E.CAREER_TIMING, [
    ("promotion_timing", "Promotion Report", "प्रमोशन रिपोर्ट",
     "Assess whether the current period supports professional advancement and increased responsibility.",
     "Synthesize natal career indications, 2nd/6th/10th/11th houses and their lords, career yogas, current MD/AD, and Jupiter/Saturn/Rahu transits.",
     "Answer the promotion question now; strongest supported advancement windows, slower period only if justified, and practical career action."),
    ("career_improvement_timing", "Career Improvement", "करियर में सुधार",
     "Identify when professional momentum may begin improving after a stagnant phase.",
     "Compare career-house/lord support and career yogas with the current and next MD/AD and relevant career transits.",
     "Separate the first signs of improvement from sustained growth; suggest a realistic preparation focus."),
    ("career_growth_delay_reason", "Career Growth Delays", "करियर की देरी",
     "Explain astrological factors that may correspond to delayed professional progress.",
     "Weigh pressure and support in career houses/lords, career yogas, MD/AD and career transits without treating delay as permanent.",
     "Prioritize the main bottlenecks, counterbalancing strengths and supported easing windows."),
    ("next_strong_career_period", "Next Career Opportunity", "करियर का अगला मजबूत समय",
     "Identify the next comparatively strong period for career development.",
     "Compare upcoming MD/AD with natal career factors and Jupiter/Saturn/Rahu changes, distinguishing responsibility from recognition.",
     "Explain why one supplied window is more useful than another and how to prepare for it."),
    ("salary_growth_timing", "Salary Growth", "सैलरी में बढ़ोतरी",
     "Assess periods supportive of improved compensation in the user's employment.",
     "Connect earned income and gains houses/lords with professional responsibility, career yogas, MD/AD and relevant career transits.",
     "Distinguish promotion, workload and actual pay growth; frame negotiation preparation without promising an amount."),
    ("work_recognition_timing", "Work Recognition", "काम की पहचान",
     "Assess when professional contributions may be more visible and acknowledged.",
     "Read reputation and gains through career houses/lords, career yogas, MD/AD and career transits.",
     "Separate visibility from a title or pay change; suggest ways to make contributions clear."),
    ("best_career_years", "Career Growth Years", "करियर के अच्छे साल",
     "Compare the supplied coming years for sustained career development.",
     "Anchor long-term career promise in natal career houses/yogas and the full dated MD/AD sequence; use relevant transits only within their coverage.",
     "Select a few substantiated phases, distinguishing foundation-building from consolidation and recognition."),
])
_group("job_change_timing", E.CAREER_TIMING, [
    ("job_change_now", "Job Change Timing", "नौकरी बदलने का समय",
     "Assess current professional stability versus transition conditions.",
     "Balance career-house/lord continuity and change indications against MD/AD and relevant career transits.",
     "Compare staying and exploring opportunities as conditions, with practical offer and financial checks; never instruct resignation."),
    ("new_job_timing", "New Job Opportunities", "नई नौकरी के अवसर",
     "Identify periods supportive of entering a new employment role.",
     "Synthesize service and career houses/lords, career yogas, MD/AD and career transits for openings rather than guaranteed selection.",
     "Distinguish search activity, interview progress and an actual offer; prioritize the next supported window."),
    ("best_period_to_switch", "Job Switch Windows", "नौकरी बदलने के अवसर",
     "Compare forthcoming windows for a considered change of employer or role.",
     "Read continuity versus transition in career factors, MD/AD and Jupiter/Saturn/Rahu context.",
     "Rank supported switching windows and note tradeoffs without telling the user to leave."),
    ("job_search_start_timing", "Job Search Timing", "नौकरी तलाशने का समय",
     "Identify a useful time to intensify an active job search.",
     "Use career readiness and service-house/lord indications with MD/AD and career transits to assess preparation versus outreach.",
     "Separate preparation, networking and applications from offer timing; give a focused search action."),
    ("job_gap_easing", "Employment Gap", "नौकरी के अंतराल में राहत",
     "Assess whether the phase without suitable work may become less restrictive.",
     "Weigh service/career obstacles and available strengths against MD/AD transitions and career transits.",
     "Discuss suitable-work prospects and easing cautiously, with manageable search steps and no job-loss claims."),
])
_group("money_improvement_timing", E.MONEY_TIMING, [
    ("financial_improvement_timing", "Financial Improvement", "आर्थिक स्थिति में सुधार",
     "Assess when overall financial conditions may become more manageable.",
     "Read income, savings and gains house/lord facts and existing wealth yogas alongside MD/AD and Jupiter/Saturn context.",
     "Separate increased inflow from reduced pressure and more stable money management."),
    ("income_increase_timing", "Income Growth", "आमदनी में बढ़ोतरी",
     "Assess periods supportive of higher earned inflow.",
     "Focus on income/gains houses and lords, existing wealth yogas, MD/AD and relevant Jupiter/Saturn transits.",
     "Discuss capacity and timing for income growth without predicting amounts or investment returns."),
    ("money_growth_periods", "Financial Growth Windows", "आर्थिक बढ़ोतरी के समय",
     "Compare forthcoming periods for building financial stability and resources.",
     "Combine savings/gains indications and computed wealth yogas with MD/AD and relevant transits.",
     "Rank supported accumulation windows while separating sustained stability from speculative windfalls."),
    ("financial_pressure_easing", "Financial Pressure", "आर्थिक दबाव में राहत",
     "Explain current financial strain and when it may ease.",
     "Balance income and savings support against expense/obligation house-lord factors, MD/AD and Jupiter/Saturn context.",
     "Identify pressure mechanisms and counterweights, then practical budgeting caution rather than guaranteed relief."),
    ("debt_pressure_easing", "Debt Pressure", "कर्ज के दबाव में राहत",
     "Assess the timing context for managing debt-related obligations more comfortably.",
     "Read debt/service, expenses and income house/lord relationships with wealth yogas, MD/AD and relevant transits.",
     "Distinguish easing cash-flow pressure from elimination of debt; keep repayment decisions grounded in actual finances."),
])
_group("business_timing", E.BUSINESS_TIMING, [
    ("business_start_timing", "Starting a Business", "बिज़नेस शुरू करने का समय",
     "Assess conditions for initiating a business rather than assuming entrepreneurial success.",
     "Read enterprise, work and financial house/lord facts, career/wealth yogas, MD/AD and Jupiter/Saturn timing.",
     "Separate planning from launch readiness; discuss resources and market preparation without issuing a launch command."),
    ("business_growth_timing", "Business Growth", "बिज़नेस की बढ़ोतरी",
     "Assess when an existing business may find stronger growth conditions.",
     "Connect enterprise and gains factors, career/wealth yogas, MD/AD and relevant transits.",
     "Distinguish activity or demand from sustainable gains and avoid revenue guarantees."),
    ("best_business_periods", "Business Opportunity Windows", "बिज़नेस के अच्छे समय",
     "Compare upcoming periods for business progress and consolidation.",
     "Balance enterprise-house/lord support and pressure with career/wealth yogas, MD/AD and Jupiter/Saturn windows.",
     "Explain the strongest comparative periods and what kind of preparation each supports."),
    ("business_expansion_timing", "Business Expansion", "बिज़नेस बढ़ाने का समय",
     "Assess timing conditions for increasing an existing business's scale.",
     "Weigh gains and enterprise factors against obligations, using career/wealth yogas, MD/AD and relevant transits.",
     "Distinguish growth opportunity from capacity strain; discuss cash flow and execution rather than commanding expansion."),
    ("business_slowdown_easing", "Business Slowdown", "बिज़नेस की सुस्ती",
     "Explain a slow business phase and assess supported easing windows.",
     "Compare enterprise/gains pressures and natal resources with career/wealth yogas, MD/AD and Jupiter/Saturn conditions.",
     "Prioritize the main constraint and possible stabilization; avoid promising recovery or profitability."),
    ("new_venture_partnership_timing", "New Venture or Partnership", "नया काम या पार्टनरशिप",
     "Assess the user's readiness and timing for a new venture or working partnership.",
     "Use the user's enterprise, partnership and financial house/lord facts, yogas, MD/AD and relevant transits.",
     "Distinguish venture readiness from partner reliability; recommend practical agreement checks, not claims about another person's intent."),
])
_group("marriage_timing", E.MARRIAGE_TIMING, [
    ("strongest_marriage_periods", "Marriage Windows", "शादी के मजबूत समय",
     "Compare the strongest supplied periods supportive of marriage readiness.",
     "Read marriage-related natal placements and house/lord facts with MD/AD and Jupiter/Saturn transits.",
     "Rank supported windows and explain their combined support without promising a wedding date."),
    ("marriage_chances_timing", "Marriage Prospects", "शादी की संभावनाओं का समय",
     "Assess when marriage prospects may begin to look more favorable.",
     "Separate underlying marriage indications from current MD/AD and Jupiter/Saturn activation of relevant houses/lords.",
     "Explain the first supported opening and readiness factors, not a guaranteed outcome."),
    ("marriage_delay_reason", "Marriage Delays", "शादी में देरी",
     "Explain astrological indications that may correspond to delayed marriage progress.",
     "Balance pressure and support in marriage houses/lords with MD/AD and relevant Jupiter/Saturn timing.",
     "Discuss delays without permanent denial or blame; mention easing only if justified."),
    ("marriage_delay_easing", "Easing Marriage Delays", "शादी की देरी में राहत",
     "Assess when conditions around a delayed marriage process may improve.",
     "Compare the present marriage-house/lord pressures with forthcoming MD/AD and Jupiter/Saturn windows.",
     "Focus on change from pressure to opportunity and practical readiness, not a fixed deadline."),
    ("marriage_talks_current_period", "Marriage Discussions", "शादी की बातचीत",
     "Assess whether the present phase supports beginning or progressing marriage discussions.",
     "Combine marriage-related natal factors with current MD/AD and Jupiter/Saturn context.",
     "Distinguish a useful conversation period from final commitment and preserve all parties' choice."),
    ("relationship_to_marriage_window", "Relationship Towards Marriage", "रिश्ते से शादी की ओर",
     "Assess the user's own timing for considering marriage within a current relationship.",
     "Read the user's relationship and marriage houses/lords, MD/AD and Jupiter/Saturn context only.",
     "Describe personal readiness and supported discussions; do not infer partner consent or turn this into compatibility."),
])
_group("relationship_marriage_potential", E.DUAL_COMPARISON, [
    ("relationship_lead_to_marriage", "Relationship and Marriage", "रिश्ता और शादी",
     "Assess how both supplied charts support or complicate a relationship progressing toward marriage.",
     "Compare each person's relationship/marriage house-lord facts and existing Ashtakoot components, preserving person attribution.",
     "Balance compatibility strengths and work needed for commitment; no guaranteed marriage."),
    ("long_term_compatibility", "Long-Term Compatibility", "लंबे समय का तालमेल",
     "Assess enduring compatibility themes across the two supplied charts.",
     "Compare emotional, partnership and communication-related natal placements and relevant existing compatibility components.",
     "Distinguish natural ease from recurring adjustment needs without predicting longevity or private feelings."),
    ("kundali_match_for_marriage", "Kundali Match for Marriage", "शादी के लिए कुंडली मिलान",
     "Interpret the supplied kundali-matching facts in the context of marriage.",
     "Use actual Ashtakoot component results with each chart's marriage house/lord context; do not recompute scores.",
     "Explain strengths and limitations of the match rather than reducing marriage to a total score."),
    ("right_time_to_consider_marriage", "Considering Marriage Together", "साथ शादी पर विचार",
     "Assess whether the current periods of both people support considering marriage together.",
     "Combine separately attributed natal compatibility with each person's MD/AD and Jupiter/Saturn timing context.",
     "Distinguish compatible charts from synchronized readiness and useful discussions."),
])
_group("relationship_strengths_and_challenges", E.DUAL_COMPARISON, [
    ("relationship_strengths_risks", "Relationship Strengths and Challenges", "रिश्ते की ताकत और चुनौतियाँ",
     "Identify the most important supportive and challenging relationship tendencies across both charts.",
     "Compare partnership, emotional and communication-related natal factors with supplied compatibility components.",
     "Pair each major difficulty with a constructive adjustment and avoid treating tendencies as behavior facts."),
    ("conflict_areas", "Understanding Conflict", "टकराव को समझना",
     "Identify interaction themes where the two people may need extra care during disagreements.",
     "Compare emotional expression, communication and partnership factors and relevant compatibility components in both charts.",
     "Describe possible friction patterns without blame, mind-reading or predicting a breakup."),
    ("emotional_communication_fit", "Emotional and Communication Fit", "भावनाओं और बातचीत का तालमेल",
     "Assess how the two charts describe emotional needs and communication tendencies.",
     "Read each person's Moon and communication-related placements within their house/lord context and relevant compatibility factors.",
     "Separate differences in expression from lack of affection; offer specific ways to clarify needs."),
    ("strengthen_relationship", "Strengthening Your Relationship", "रिश्ता मजबूत बनाना",
     "Translate the supplied two-chart strengths and friction themes into practical relationship focus.",
     "Anchor guidance in the strongest emotional, communication and partnership contrasts and actual compatibility facts.",
     "Offer a few mutual practices tied to the analysis, without claiming to control another person's choices."),
    ("relationship_care_periods", "Relationship Care Periods", "रिश्ते में ध्यान देने के समय",
     "Identify supplied periods when the relationship may benefit from more patient communication.",
     "Combine both charts' recurring interaction themes with their separately attributed MD/AD and Jupiter/Saturn timing.",
     "Explain which pressures may coincide and what care means; never predict separation or infidelity."),
])
_group("foreign_move_timing", E.FOREIGN_TIMING, [
    ("going_abroad_timing", "Going Abroad", "विदेश जाने का समय",
     "Assess the strongest supplied periods for pursuing an overseas move or journey.",
     "Read travel and residence-related natal houses/lords with MD/AD and Jupiter/Saturn/Rahu context.",
     "Distinguish astrological support for mobility from visas, bookings and confirmed departure."),
    ("foreign_work_timing", "Working Abroad", "विदेश में काम",
     "Assess timing for exploring work opportunities abroad.",
     "Connect career/service houses and lords with travel/residence factors, MD/AD and relevant transits.",
     "Separate professional readiness and overseas movement from a guaranteed job or visa."),
    ("study_abroad", "Study Abroad", "विदेश में पढ़ाई",
     "Assess whether studying abroad fits the user's learning and relocation tendencies.",
     "Connect education, higher learning and foreign-residence house/lord facts; use MD/AD and relevant transits as timing context.",
     "Balance learning opportunity with adaptation and practical costs, rather than predicting admission or visa approval."),
    ("foreign_settlement_timing", "Settling Abroad", "विदेश में बसना",
     "Assess periods supportive of pursuing a sustained overseas residence.",
     "Distinguish residence/home and foreign-movement houses/lords with MD/AD and Jupiter/Saturn/Rahu timing.",
     "Separate temporary travel from settlement aspirations; never guarantee permanent residence or citizenship."),
    ("relocation_timing", "Relocation Timing", "शिफ्ट होने का समय",
     "Assess conditions for a change of city or country.",
     "Read home/residence and movement-related house/lord facts together with MD/AD and relevant transits.",
     "Discuss readiness and adjustment windows without assuming relocation must be international or commanding a move."),
    ("foreign_plans_delay_reason", "Overseas Plans Delayed", "विदेश की योजना में देरी",
     "Explain timing pressures around stalled overseas plans.",
     "Balance natal travel/residence support against present MD/AD and relevant transit pressures.",
     "Distinguish astrological context from actual administrative obstacles; identify easing only within supported dates."),
])
_group("study_exam_timing", E.EDUCATION_TIMING, [
    ("study_strong_period", "Study Support", "पढ़ाई के अनुकूल समय",
     "Compare periods supportive of sustained learning and study effort.",
     "Read education and learning-related house/lord facts with MD/AD and Jupiter/Saturn context.",
     "Explain concentration, consistency and learning readiness without predicting grades."),
    ("exam_preparation_period", "Exam Preparation", "परीक्षा की तैयारी",
     "Identify periods supportive of disciplined exam preparation.",
     "Combine learning, effort and routine-related natal factors with MD/AD and relevant transits.",
     "Focus on preparation habits and revision rather than exam outcome or selection."),
    ("higher_education_timing", "Higher Education", "उच्च शिक्षा का समय",
     "Assess when beginning further or advanced study may be supported.",
     "Connect higher-learning house/lord facts and education tendencies with MD/AD and Jupiter/Saturn context.",
     "Distinguish academic readiness from admission decisions and practical course commitments."),
    ("study_progress_improvement", "Study Progress", "पढ़ाई में प्रगति",
     "Assess when slow learning progress may begin to improve.",
     "Compare education-related natal strengths and pressures with current and next MD/AD and relevant transits.",
     "Describe gradual improvement and useful study adjustments without promising results."),
])
_group("property_timing", E.PROPERTY_TIMING, [
    ("property_purchase_timing", "Property Purchase Timing", "प्रॉपर्टी खरीदने का समय",
     "Assess supportive periods for considering a property purchase.",
     "Read home/property houses and lords with acquisition/resource factors, MD/AD and Jupiter/Saturn context.",
     "Give timing context alongside affordability, title checks and practical readiness; no buy command."),
    ("property_current_period", "Property Readiness Now", "अभी प्रॉपर्टी की तैयारी",
     "Assess whether current conditions support considering property acquisition.",
     "Balance natal property and resource factors with current MD/AD and Jupiter/Saturn transits.",
     "Explain present support, mixed signals and constraints without substituting for financial or legal checks."),
    ("property_strongest_period", "Property Opportunity Windows", "प्रॉपर्टी के मजबूत समय",
     "Compare forthcoming periods for pursuing property acquisition.",
     "Combine home/property house-lord factors with dated MD/AD and Jupiter/Saturn windows.",
     "Rank supported windows and explain their differences without predicting a completed transaction."),
    ("property_delay_reason", "Property Purchase Delays", "प्रॉपर्टी लेने में देरी",
     "Explain astrological timing pressures around a delayed property purchase.",
     "Read property/resource houses and lords against present MD/AD and relevant transit pressures.",
     "Balance obstacles with supportive factors; do not diagnose legal or financing problems from a chart."),
    ("own_home_timing", "A Home of Your Own", "अपना घर लेने का समय",
     "Assess timing context for the aspiration to acquire a personal home.",
     "Connect home/residence and resource-related houses/lords with MD/AD and relevant transits.",
     "Distinguish readiness for a home from investment property and avoid ownership guarantees."),
])
_group("life_turning_points", E.LIFE_TIMING, [
    ("major_turning_points", "Major Life Phases", "जीवन के बड़े बदलाव",
     "Identify the main changes of emphasis in the supplied coming years.",
     "Read dated MD/AD transitions through their natal house/lord roles and relevant long-cycle transit context.",
     "Select only a few supported turning points, naming themes rather than inventing events."),
    ("next_life_change_period", "Next Phase Change", "अगला जीवन बदलाव",
     "Assess the next significant change in the user's astrological phase.",
     "Compare the current and next substantial MD/AD transitions with natal lordship and relevant transit context.",
     "Explain continuity versus change of emphasis; a phase boundary is not a guaranteed event day."),
    ("important_years_ahead", "Important Years Ahead", "आगे के महत्वपूर्ण साल",
     "Compare the coming years covered by the evidence for meaningful shifts of emphasis.",
     "Anchor comparison in full supplied MD/AD dates, natal lordship and relevant transit coverage.",
     "Explain why selected years deserve attention without portraying other years as meaningless."),
    ("current_phase_meaning", "Understanding Your Current Phase", "मौजूदा समय को समझना",
     "Explain the themes of the present phase and how the next one may differ.",
     "Read current MD/AD lords in their natal houses and lordships, then the next dated transition and relevant transits.",
     "Connect present experiences to a limited set of themes; distinguish a timing boundary from instant change."),
    ("areas_needing_attention", "Areas Needing Attention", "ध्यान देने वाले जीवन क्षेत्र",
     "Identify which life areas currently warrant constructive attention in the supplied short-term context.",
     "Map the supplied MD/AD lords and relevant transits to natal house/lord themes without inventing health or crisis events.",
     "Prioritize a small number of supported themes and practical attention, balancing pressure with resources."),
])
_group("life_direction_and_strengths", E.NATAL_DIRECTION, [
    ("natural_strengths", "Natural Strengths", "प्राकृतिक ताकतें",
     "Describe a few natural tendencies that the natal evidence consistently supports.",
     "Synthesize Lagna, planet sign/house placements and house/lord relationships without numeric strength rankings.",
     "Tie each tendency to real-life expression while allowing learning and choice; do not add timing without evidence."),
    ("life_direction", "Life Direction", "जीवन की दिशा",
     "Identify broad directions of effort that fit the supplied natal tendencies.",
     "Compare recurring natal house/lord and placement themes rather than imposing one predetermined career or lifestyle.",
     "Offer a few plausible directions and their tradeoffs, not a command or a fixed destiny."),
    ("focus_to_use_strengths", "Putting Strengths to Work", "ताकतों का सही इस्तेमाल",
     "Translate supported natal strengths into a small number of practical priorities.",
     "Connect recurring placement and house/lord themes with supplied current MD/AD and Jupiter/Saturn context for practice and balanced development.",
     "Explain what to focus on and why; keep advice linked to the reading rather than generic motivation."),
])
# 62 -- Birth + Current obstacle diagnostic. Distinct from career_growth_delay_reason/marriage_delay_reason/etc.
# (each narrow to one family's own delay) and from life_direction_and_strengths (natal-only, no obstacles at all):
# this is a whole-chart 2-4-factor obstacle reading, birth-durable vs. currently-activated, with concise remedies.
_group("kundali_obstacles", E.NATAL_DIRECTION, [
    ("major_kundali_obstacles", "Major Obstacles in Your Kundali", "आपकी कुंडली की प्रमुख बाधाएँ",
     "Identify the 2-4 most meaningful obstacles the whole chart supports, separating durable birth-chart challenges "
     "from what is currently active, then offer concise, relevant remedies.",
     "Synthesize whole-chart house/lord facts and existing career/wealth yogas for birth-chart challenges; the current "
     "MD/AD and Jupiter/Saturn/Rahu transits for what is presently activated.",
     "Prioritized 2-4 obstacles only, clearly split into birth-chart vs. currently-active, followed by concise "
     "practical-first remedies; never an exhaustive negativity list and never an invented dosha."),
])
# 63 -- Birth + Current strength diagnostic. Distinct from natural_strengths (natal-only, "What are my natural
# strengths according to my birth chart?" -- no current-activation dimension at all): this pairs the SAME kind of
# durable natal strengths with which of them current Dasha/transit evidence actively supports right now, plus how
# to use them in this window. natural_strengths/life_direction/focus_to_use_strengths are unchanged.
_group("kundali_strengths", E.NATAL_DIRECTION, [
    ("major_kundali_strengths", "Major Strengths in Your Kundali", "आपकी कुंडली की प्रमुख शक्तियाँ",
     "Identify the 2-4 most meaningful strengths the whole chart supports, separating durable birth-chart strengths "
     "from what is currently active, then explain how to use them effectively right now.",
     "Synthesize whole-chart house/lord facts and existing career/wealth yogas for birth-chart strengths; the current "
     "MD/AD and Jupiter/Saturn/Rahu transits for which of them are presently activated.",
     "Prioritized 2-4 strengths only, clearly split into birth-chart vs. currently-active, followed by concise, "
     "practical guidance for using them in the supplied current window; never an exhaustive list."),
])

PROMPT_SPECS = MappingProxyType(_specs)
del _specs


class MissingPromptSpecError(LookupError):
    code = "focused_prompt_spec_missing"


def get_prompt_spec(question_key):
    get_question(question_key)  # preserve controlled UnknownQuestionError
    try:
        return PROMPT_SPECS[question_key]
    except KeyError:
        raise MissingPromptSpecError(f"No focused prompt specification for '{question_key}'.") from None
