"""
Q4.2D -- shared paid-report narrative renderer hardening (convert_headings()).

Reproduces the exact structures Q4.2C's real Luna output produced and asserts
STRUCTURAL HTML properties (no pixel-specific checks):

  1. '---' is never a bullet.
  2. '***' / '___' (and spaced variants) are never bullets or paragraphs.
  3-5. '**...:**' lead-ins stay bold lead-ins, never major headings.
  6. Numbered section headings still render as headings.
  7. Legitimate bullets still render as bullets.
  8. No empty narrative card is emitted after a heading.
  9. English narrative rendering is valid.
 10. Hindi narrative rendering is valid.
 + inline lead-ins ('**Label:** text') never leak stray asterisks,
 + no page ends on an orphaned section heading (real WeasyPrint layout).

No AI call, no DB, no network.
"""
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from weasyprint import HTML

from pdf_generator_weasy import convert_headings, env, BASE_DIR
from modules.payments.report_i18n_labels import labels_for_language

passed = 0
failed = 0


def check(label, condition):
    global passed, failed
    if condition:
        print(f"  PASS: {label}")
        passed += 1
    else:
        print(f"  FAIL: {label}")
        failed += 1


def text_of(html):
    return re.sub(r"<[^>]+>", "", html)


def cards(html):
    return re.findall(r"<div class='card'>(.*?)</div>", html, re.S)


def headings(html, tag="h2"):
    return re.findall(rf"<{tag} class='section-heading'>(.*?)</{tag}>", html, re.S)


# ---- the exact shapes Q4.2C's real Luna output produced -------------------
# (whole-line lead-ins carry a markdown hard-break: two trailing spaces)
HI_SECTION_WHOLE_LINE_LEADINS = (
    "**1. Legal Dispute का Pressure**\n"
    "\n"
    "**मुख्य बात:**  \n"
    "आपकी कुंडली में Legal Dispute-Pressure की tendency **Elevated** दिखती है।\n"
    "\n"
    "**Astrology क्या कहती है:**  \n"
    "आपके 6th House में Mars है। 7th House का Lord Mars 6th House में है।\n"
    "\n"
    "**आपके लिए Practical मतलब:**  \n"
    "हर important बात को लिखित रूप में रखें।\n"
    "\n"
    "---\n"
    "\n"
    "**2. जुड़े हुए Houses के संकेत**\n"
    "\n"
    "**मुख्य बात:**  \n"
    "6th, 7th, 8th और 12th House के connections दिखते हैं।\n"
    "\n"
    "**Astrology क्या कहती है:**  \n"
    "- **6th House Pisces:** यहाँ Mars है।  \n"
    "- **7th House Aries:** यहाँ Venus है।  \n"
    "\n"
    "**आपके लिए Practical मतलब:**  \n"
    "Terms साफ़ रखें।\n"
    "\n"
    "---\n"
)

# Sade Sati's Luna variant: the lead-in is INLINE on the same line
HI_INLINE_LEADINS = (
    "**1. आपकी Sade Sati Status**\n"
    "\n"
    "**सीधी बात:** आपकी Sade Sati अभी Active है और इसका 3rd Phase चल रहा है।\n"
    "\n"
    "**Astrology क्या कहती है:** Saturn अभी Pisces में transit कर रहा है।\n"
    "\n"
    "**आपके लिए Practical मतलब:** जल्दबाज़ी वाले फैसले टालें।\n"
    "\n"
    "---\n"
    "\n"
    "**2. Timeline**\n"
    "\n"
    "**सीधी बात:** यह Phase 02/06/2027 तक है।\n"
)

# Children's Luna variant: '## N. Title' headings + whole-line lead-ins
HI_HASH_HEADINGS = (
    "## 1. आपका Parenting Pattern\n"
    "**मुख्य बात:**  \n"
    "आप बच्चे को structure देना चाहते हैं।\n"
    "\n"
    "**आपके लिए Practical मतलब:**  \n"
    "- घर के rules कम लेकिन clear रखें।  \n"
    "- Rules का reason बच्चे को समझाएँ।  \n"
    "\n"
    "## 2. Communication\n"
    "**मुख्य बात:**  \n"
    "Open conversation सबसे अच्छा रहता है।\n"
)

EN_NARRATIVE = (
    "**1. Career Direction**\n"
    "\n"
    "You are drawn to structured, analytical work.\n"
    "\n"
    "The 10th house shows steady professional growth.\n"
    "\n"
    "---\n"
    "\n"
    "**2. Practical Career Guidance**\n"
    "\n"
    "- Build a portfolio of **real** projects.\n"
    "- Review your goals every quarter.\n"
    "\n"
    "***\n"
    "\n"
    "**3. Summary**\n"
    "\n"
    "Consistent effort is your strongest asset.\n"
)

print("\n=== 1/2: horizontal rules are never bullets ===")
for hr in ("---", "***", "___", "- - -", "* * *", "_ _ _", "----------", "*****", "  ---  "):
    out = convert_headings(f"Before.\n{hr}\nAfter.")
    check(f"1/2: {hr!r} produces no <li>", "<li>" not in out)
    check(f"1/2: {hr!r} leaves no marker-only paragraph or stray dashes/asterisks",
          not re.search(r"<p>\s*[-*_\s]+</p>", out) and "--" not in text_of(out) and "*" not in text_of(out) and "___" not in text_of(out))
    check(f"1/2: {hr!r} keeps the surrounding paragraphs", "<p>Before.</p>" in out and "<p>After.</p>" in out)

out = convert_headings("- one\n- two\n---\n- three")
check("1/2: a rule inside a list ends the list cleanly (2 lists, no rule text)",
      out.count("<ul class='body-list'>") == 2 and "--" not in text_of(out))
check("1/2: '---' is never rendered as the literal bullet '• --' shape", "<li>--</li>" not in convert_headings("---") and convert_headings("---") == "")
check("1/2: '**' alone (bare bold marker) leaves no stray asterisks", "*" not in text_of(convert_headings("Text.\n**\nMore.")))

print("\n=== 3/4/5: bold lead-ins stay lead-ins, never major headings ===")
for label in ("मुख्य बात:", "Astrology क्या कहती है:", "आपके लिए Practical मतलब:", "सीधी बात:"):
    for src in (f"**{label}**  ", f"**{label}**", f"**{label[:-1]}**:"):
        out = convert_headings(f"Intro line.\n{src}\nBody text follows.")
        check(f"3-5: {src.strip()!r} is not an <h1>/<h2>/<h3>", not re.search(r"<h[123]", out))
        check(f"3-5: {src.strip()!r} renders as a bold lead-in <p class='lead-in'>",
              f"<p class='lead-in'><strong>{label[:-1] if src.endswith(':') else label}</strong></p>" in out
              or f"<p class='lead-in'><strong>{label}</strong></p>" in out)
        check(f"3-5: {src.strip()!r} leaves no raw asterisks", "*" not in text_of(out))
out = convert_headings("**Elevated**\nBody.")
check("3-5: an arbitrary un-numbered whole-line bold is NOT promoted to a section heading", "<h2" not in out and "<strong>Elevated</strong>" in out)
out = convert_headings("**First** and then **Second**\nBody.")
check("3-5: a line with several bold spans is never mistaken for one whole-line heading", "<h2" not in out)

print("\n=== 6: legitimate numbered section headings still render as headings ===")
out = convert_headings("**1. Career Direction**\nText.\n**9) Summary**\nText.")
check("6: '**N. Title**' -> <h2 class='section-heading'>", headings(out) == ["1. Career Direction", "9) Summary"])
check("6: '# ' -> h1", "<h1 class='section-heading'>Main</h1>" in convert_headings("# Main\nBody."))
check("6: '## ' -> h2", "<h2 class='section-heading'>Sub</h2>" in convert_headings("## Sub\nBody."))
check("6: '### ' -> h3", "<h3 class='sub-heading'>Deep</h3>" in convert_headings("### Deep\nBody."))
check("6: Devanagari numbered heading -> h2", headings(convert_headings("**2. जुड़े हुए Houses के संकेत**\nText.")) == ["2. जुड़े हुए Houses के संकेत"])
check("6: a decimal like '**3.5 points**' is not mistaken for a numbered heading", "<h2" not in convert_headings("**3.5 points**\nBody."))
check("6: a numbered heading whose TITLE starts with a digit is still a heading ('**3. 4th House -- अंदर का सुकून**')",
      headings(convert_headings("**3. 4th House -- अंदर का सुकून और Emotional Base**\nText.")) == ["3. 4th House -- अंदर का सुकून और Emotional Base"])
check("6: '## 3. 4th House ...' keeps the sequence so a following plain '4.' heading is recognised",
      headings(convert_headings("## 3. 4th House Base\nBody.\n\n4. 12th House Rest\n\nBody.")) == ["3. 4th House Base", "4. 12th House Rest"])

print("\n=== 7: legitimate bullets still render as bullets ===")
for marker in ("-", "*", "•"):
    out = convert_headings(f"{marker} First point\n{marker} Second **bold** point")
    check(f"7: {marker!r} bullets -> one <ul> with two real <li>", out.count("<ul class='body-list'>") == 1 and out.count("<li>") == 2)
    check(f"7: {marker!r} bullet inline bold preserved", "<li>Second <strong>bold</strong> point</li>" in out)
out = convert_headings("- **6th House Pisces:** यहाँ Mars है।  \n- **7th House Aries:** यहाँ Venus है।")
check("7: bullets that START with a bold label keep the bold, with no stray asterisks",
      "<li><strong>6th House Pisces:</strong> यहाँ Mars है।</li>" in out and "*" not in text_of(out))
check("7: a hyphen with no following space is not a bullet ('-5 degrees')", "<li>" not in convert_headings("-5 degrees retrograde"))
for marker in ("-", "*", "•"):
    check(f"7: bare {marker!r} marker still renders nothing", convert_headings(f"{marker}\nReal.") == "<div class='card'>\n<p>Real.</p>\n</div>")

print("\n=== inline lead-ins ('**Label:** text') -- Sade Sati shape ===")
out = convert_headings(HI_INLINE_LEADINS)
check("inline lead-in stays a bold paragraph lead-in (not a bullet)", "<li>" not in out and "<p><strong>सीधी बात:</strong> आपकी Sade Sati अभी Active है" in out)
check("inline lead-ins leave no stray asterisks anywhere", "*" not in text_of(out))
check("inline lead-ins do not create extra headings (only the 2 numbered ones)", headings(out) == ["1. आपकी Sade Sati Status", "2. Timeline"])

print("\n=== 8: no empty narrative card after a heading ===")
for name, src in (("hi whole-line lead-ins", HI_SECTION_WHOLE_LINE_LEADINS), ("hi inline lead-ins", HI_INLINE_LEADINS),
                  ("hi ## headings", HI_HASH_HEADINGS), ("en", EN_NARRATIVE)):
    out = convert_headings(src)
    check(f"8: [{name}] no empty '<div class='card'></div>'", "<div class='card'></div>" not in out and "<div class='card'>\n</div>" not in out)
    check(f"8: [{name}] every card carries real content (<p> or <li>)", all(("<p" in c or "<li>" in c) for c in cards(out)))
    n_h = len(headings(out))
    check(f"8: [{name}] exactly one card per heading ({n_h} headings / {len(cards(out))} cards)", len(cards(out)) == n_h)
    check(f"8: [{name}] every heading is directly followed by its content card", len(re.findall(r"</h2>\n<div class='card'>", out)) == n_h)
out = convert_headings("**1. A**\n**2. B**\nBody of B.")
check("8: back-to-back headings emit no card between them", "</h2>\n<h2" in out)
out = convert_headings("**1. A**\n---\n**2. B**\nBody.")
check("8: a heading followed only by a rule emits no empty card", "</h2>\n<h2" in out and "<div class='card'></div>" not in out)
check("8: a trailing heading with no content emits no empty card", "<div class='card'>" not in convert_headings("**1. A**"))
check("8: plain narrative_style still has no card shell", "<div class='card'>" not in convert_headings(HI_SECTION_WHOLE_LINE_LEADINS, narrative_style="plain"))

print("\n=== 9: English narrative rendering stays valid ===")
out = convert_headings(EN_NARRATIVE)
check("9: 3 numbered English sections -> 3 <h2>", headings(out) == ["1. Career Direction", "2. Practical Career Guidance", "3. Summary"])
check("9: English paragraphs render as <p>", "<p>You are drawn to structured, analytical work.</p>" in out)
check("9: English bullets render as a real list with inline bold", "<li>Build a portfolio of <strong>real</strong> projects.</li>" in out and out.count("<li>") == 2)
check("9: English output has no stray markdown", not re.search(r"\*|^-{2,}|<li>-", text_of(out), re.M) and "---" not in out)
check("9: legacy '@@Label:' / inline bold / single paragraph behaviour unchanged",
      "<p><strong>Varna:</strong> text</p>" in convert_headings("@@Varna: text")
      and "<p>This is <strong>important</strong> mid sentence.</p>" in convert_headings("This is **important** mid sentence.")
      and convert_headings("Plain paragraph.") == "<div class='card'>\n<p>Plain paragraph.</p>\n</div>")

print("\n=== 10: Hindi narrative rendering stays valid ===")
for name, src, n_head in (("whole-line lead-ins", HI_SECTION_WHOLE_LINE_LEADINS, 2), ("hash headings", HI_HASH_HEADINGS, 2)):
    out = convert_headings(src)
    check(f"10: [{name}] only the {n_head} real section headings are headings", len(headings(out)) == n_head and not re.search(r"<h[13]", out))
    check(f"10: [{name}] lead-ins are inline bold lead-ins", out.count("<p class='lead-in'>") >= 3)
    check(f"10: [{name}] no lead-in text sits inside a heading tag", not re.search(r"<h[123][^>]*>[^<]*(मुख्य बात|Astrology क्या|Practical मतलब)", out))
    check(f"10: [{name}] no stray asterisks or rule text", "*" not in text_of(out) and "--" not in text_of(out))
    check(f"10: [{name}] Devanagari content survives intact", "आपके लिए Practical मतलब" in out and "मुख्य बात" in out)
out = convert_headings(HI_SECTION_WHOLE_LINE_LEADINS)
check("10: inline bold inside a Hindi paragraph is preserved", "<strong>Elevated</strong>" in out)
check("10: Hindi bullets with leading bold label render as bullets", "<li><strong>6th House Pisces:</strong> यहाँ Mars है।</li>" in out)
check("10: no <br/> or trailing hard-break spaces leak into Hindi lead-ins", "  <" not in out and "  \n" not in out)

print("\n=== plain-text variant (no markdown at all) -- the Children shape from the fresh Q4.2D run ===")
# The prompts say "report सादे text में", and Luna sometimes emits NO markdown:
# numbered headings are plain "N. Title" lines, lead-ins plain "Label:" lines.
HI_PLAIN_TEXT = (
    "1. आपका Parenting Pattern\n"
    "\n"
    "मुख्य बात:  \n"
    "आपका Parenting style caring होने के साथ-साथ responsible रहेगा।\n"
    "\n"
    "Astrology क्या कहती है:  \n"
    "आपका 5th House Aquarius राशि में है और इसमें Moon है।\n"
    "\n"
    "Practical मतलब:  \n"
    "- घर के rules कम लेकिन clear रखें।  \n"
    "- Rules का reason बच्चे को समझाएँ।  \n"
    "\n"
    "2. आपका 5th House Parenting के बारे में क्या बताता है\n"
    "\n"
    "मुख्य बात:  \n"
    "आपका Parenting approach practical और structured हो सकता है।\n"
    "\n"
    "3. Jupiter और Moon का असर\n"
    "\n"
    "मुख्य बात:  \n"
    "आपका प्यार समझदारी के जरिए दिखेगा।\n"
)
out = convert_headings(HI_PLAIN_TEXT)
check("plain: the three plain numbered lines become <h2> section headings",
      headings(out) == ["1. आपका Parenting Pattern", "2. आपका 5th House Parenting के बारे में क्या बताता है", "3. Jupiter और Moon का असर"])
check("plain: plain 'Label:' lines become bold lead-ins, not headings and not bare paragraphs",
      out.count("<p class='lead-in'>") == 5 and "<p class='lead-in'><strong>मुख्य बात:</strong></p>" in out
      and "<p class='lead-in'><strong>Astrology क्या कहती है:</strong></p>" in out and "<p class='lead-in'><strong>Practical मतलब:</strong></p>" in out)
check("plain: exactly one content card per heading, none empty", len(cards(out)) == 3 and all(("<p" in c or "<li>" in c) for c in cards(out)))
check("plain: the bullets under a plain lead-in stay a real list", out.count("<li>") == 2)
check("plain: no lead-in or heading text leaks out as an ordinary paragraph", "<p>मुख्य बात" not in out and "<p>1. " not in out and "<p>2. " not in out)

# A numbered LIST inside a section must never be promoted to a heading.
out = convert_headings("1. Career Direction\n\nमुख्य बात:  \nText.\n\nSteps to follow:\n1. Keep records of every agreement.\n2. Review the terms before signing.\n3. Ask for a written summary.\n")
check("plain: consecutive numbered list items are NOT headings", headings(out) == ["1. Career Direction"] and out.count("<h2") == 1)
out = convert_headings("1. Career Direction\n\nBody.\n\n2. Keep records of every agreement.\n\nMore body.")
check("plain: a numbered line ending in sentence punctuation is NOT a heading", headings(out) == ["1. Career Direction"])
out = convert_headings("1. Career Direction\n\nBody.\n\n5. Skipped Numbering Title\n\nMore body.")
check("plain: a numbered line that does not continue the 1,2,3 sequence is NOT a heading", headings(out) == ["1. Career Direction"])
out = convert_headings("Intro paragraph here.\n\n3. Not The First Section\n\nBody.")
check("plain: numbering must start at 1", "<h2" not in out)
out = convert_headings("1. Career Direction\n2. Adjacent list item without blank lines\nBody.")
check("plain: a numbered line with no blank line around it is NOT a heading", headings(out) == [])
out = convert_headings("**1. Career Direction**\n\nBody.\n\n2. Practical Guidance\n\nBody two.")
check("plain: bold-numbered and plain-numbered headings mix in one sequence", headings(out) == ["1. Career Direction", "2. Practical Guidance"])
check("plain: a plain line that merely ends with a colon mid-paragraph is not promoted (needs a blank line before)",
      "<p class='lead-in'>" not in convert_headings("Some paragraph text\nFollow these:\nItem"))
check("plain: a long colon-terminated sentence is NOT a lead-in",
      "<p class='lead-in'>" not in convert_headings("Body.\n\n" + ("बहुत लंबी line " * 8) + "यह है:\nText."))
check("plain: English plain-text numbered headings work too",
      headings(convert_headings("1. Career Direction\n\nYou are drawn to analytical work.\n\n2. Summary\n\nSteady effort wins.")) == ["1. Career Direction", "2. Summary"])

print("\n=== Q4.3A: plain numbered headings that END IN '?' are still section headings ===")
# Q4.3 found that a trailing '?' disqualified a valid plain-text heading, and the
# 1,2,3 sequence rule then rejected every later heading (7 Hindi prompts prescribe
# question-style headings).
Q_HEAD = "1. Business में आपकी Suitability कैसी है?"
out = convert_headings(f"{Q_HEAD}\n\nसीधी बात: आप Business के लिए suitable हैं।\n")
check("Q4.3A-1: '1. Business में आपकी Suitability कैसी है?' is a heading", headings(out) == [Q_HEAD])
QSEQ = (
    "1. Business में आपकी Suitability कैसी है?\n\nपहली body line।\n\n"
    "2. Career के लिए कौन-से संकेत मजबूत हैं?\n\nदूसरी body line।\n\n"
    "3. Current Dasha अभी क्या कहती है?\n\nतीसरी body line।\n\n"
    "4. Practical Guidance\n\nचौथी body line।\n\n"
    "5. Summary\n\nपाँचवीं body line।\n"
)
out = convert_headings(QSEQ)
check("Q4.3A-2: three sequential question headings are all headings", headings(out)[:3] == ["1. Business में आपकी Suitability कैसी है?", "2. Career के लिए कौन-से संकेत मजबूत हैं?", "3. Current Dasha अभी क्या कहती है?"])
check("Q4.3A-3: after a question heading the sequence continues (4 and 5 non-question headings still recognised)", len(headings(out)) == 5 and headings(out)[3:] == ["4. Practical Guidance", "5. Summary"])
check("Q4.3A-3: one non-empty card per heading, no lead-in/heading leakage", len(cards(out)) == 5 and all("<p" in c for c in cards(out)))
out = convert_headings("1. Career Direction\n\nBody.\n\n2. Practical Guidance\n\nBody.\n\n3. आपको आगे क्या करना चाहिए?\n\nBody.\n\n4. Summary\n\nBody.\n")
check("Q4.3A-3: a question heading in the MIDDLE of the sequence does not break later headings", len(headings(out)) == 4)
check("Q4.3A-3: bold-markdown question heading still works (unchanged path)", headings(convert_headings("**1. Business में आपकी Suitability कैसी है?**\nBody."))[0].endswith("कैसी है?"))
check("Q4.3A-3: '## N. ...?' question heading still works (unchanged path)", headings(convert_headings("## 1. Business में आपकी Suitability कैसी है?\nBody.")) == ["1. Business में आपकी Suitability कैसी है?"])
# ---- 4: protections stay in force; a '?' does not make prose a heading -------
out = convert_headings("1. Career Direction\n\nBody.\n\nQuestions to ask:\n1. Did you review the terms?\n2. Did you ask for a written summary?\n3. Did you keep a copy?\n")
check("Q4.3A-4: consecutive numbered list items ending in '?' are NOT promoted", headings(out) == ["1. Career Direction"])
out = convert_headings("1. Career Direction\n\nBody.\n\n5. क्या यह sequence का अगला heading है?\n\nMore body.")
check("Q4.3A-4: a question that does not continue the sequence is NOT a heading", headings(out) == ["1. Career Direction"])
out = convert_headings("Intro paragraph.\n\n2. क्या यह पहला heading है?\n\nBody.")
check("Q4.3A-4: numbering must still start at 1 for a question line", "<h2" not in out)
out = convert_headings("1. क्या यह heading है?\n2. यह अगली line बिना blank line के है?\nBody.")
check("Q4.3A-4: question lines with no blank lines around them are NOT headings", headings(out) == [])
LONG_Q = "1. " + ("क्या आप जानते हैं कि यह बहुत लंबा सवाल एक section heading नहीं बल्कि पूरा paragraph है " * 3) + "?"
check("Q4.3A-4: a long prose question (over the heading length limit) is NOT a heading", headings(convert_headings(f"{LONG_Q}\n\nBody.")) == [])
for punct in (".", "।", "!", ":", ";", ","):
    check(f"Q4.3A-4: a trailing {punct!r} still disqualifies a plain numbered line", headings(convert_headings(f"1. आपका Career Pattern{punct}\n\nBody.")) == [])
check("Q4.3A-4: an un-numbered question line is never a heading", "<h2" not in convert_headings("क्या आप तैयार हैं?\n\nBody."))
# ---- 5/6/7: existing behaviour, EN and HI --------------------------------------
check("Q4.3A-5: existing plain numbered heading (no '?') unchanged", headings(convert_headings("1. Career Direction\n\nBody.\n\n2. Summary\n\nBody.")) == ["1. Career Direction", "2. Summary"])
check("Q4.3A-6: English question-style plain headings work too", headings(convert_headings("1. What does your chart say about Career?\n\nBody.\n\n2. Summary\n\nBody.")) == ["1. What does your chart say about Career?", "2. Summary"])
check("Q4.3A-7: Hindi plain lead-ins under a question heading stay lead-ins, not headings",
      convert_headings("1. Business में आपकी Suitability कैसी है?\n\nसीधी बात:  \nText।\n\nAstrology क्या कहती है:  \nText।\n").count("<p class='lead-in'>") == 2)

print("\n=== Q4.3A: EVERY standard prompt's own heading list survives the plain-text path (all 24 x EN/HI) ===")
from modules.payments.report_product_intelligence import REGISTRY  # noqa: E402
_std = sorted(s for s, p in REGISTRY.items() if p.generator == "standard_v1")
check("Q4.3A: registry has 24 standard_v1 products", len(_std) == 24)
_bad = []
_q_prompts = []
for _slug in _std:
    for _lang in ("en", "hi"):
        _txt = open(os.path.join(BASE_DIR, "prompts", f"{_slug}_{_lang}.txt"), encoding="utf-8").read()
        _heads = re.findall(r"^\*\*(\d+\..*?)\*\*\s*$", _txt, re.M)
        if any(h.endswith("?") for h in _heads):
            _q_prompts.append(f"{_slug}_{_lang}")
        _plain = "\n\n".join(f"{h}\n\nSection body for {i}." for i, h in enumerate(_heads, 1))
        _got = headings(convert_headings(_plain))
        if _got != _heads:
            _bad.append((f"{_slug}_{_lang}", len(_got), len(_heads)))
check(f"Q4.3A: all 48 standard prompts' prescribed headings render as headings in plain-text form (bad: {_bad})", not _bad)
check(f"Q4.3A: the question-heading prompts are exercised (found {len(_q_prompts)})", len(_q_prompts) >= 7)

print("\n=== pagination structure: lead-ins keep with their text (template) ===")
tpl = open(os.path.join(BASE_DIR, "templates", "report_template.html"), encoding="utf-8").read()
check("template: .lead-in is kept with the paragraph that follows it (break-after: avoid)",
      re.search(r"\.lead-in\s*\{[^}]*page-break-after:\s*avoid", tpl, re.S) is not None)
check("template: cards were NOT made globally unbreakable for Hindi (body.hi .card stays breakable)",
      "body.hi .card { page-break-inside: auto; }" in tpl)


def _render_pages(body_html, hindi):
    labels = labels_for_language("hi" if hindi else "en")
    ctx = dict(
        report_title="Renderer Fixture", report_subtitle=None, is_sample=True, is_hindi=hindi,
        lang="hi" if hindi else "en", today_str="19/09/2026",
        user_info={"name": "Aarav Sharma", "dob": "15/06/1990", "tob": "14:30", "pob": "Lucknow"},
        kundali_img_src=None, logo_src=None, fonts_dir_rel="fonts",
        birth_chart_summary="Fixture summary.", mahadasha_summary="", current_transit_summary="",
        aspect_summary="", manglik_summary="", answer_hero=None, result_cards=[], fact_cards=[],
        timeline=None, tables=[], action_list=None, notices=[], highlights=[], gemstone=None,
        disclaimer="Disclaimer fixture.", app_download={"heading": "CTA", "play_store_url": "https://example.invalid/app"},
        labels=labels, gpt_response_html=body_html,
    )
    html = env.get_template("report_template.html").render(**ctx)
    return HTML(string=html, base_url=BASE_DIR).render()


def _iter_blocks(box):
    for child in getattr(box, "children", []) or []:
        yield child
        yield from _iter_blocks(child)


def _last_body_child_classes(page):
    body = None
    for b in _iter_blocks(page._page_box):
        if getattr(b, "element_tag", "") == "body":
            body = b
            break
    kids = [k for k in body.children if getattr(k, "element", None) is not None] if body else []
    return [(k.element.get("class") or "") for k in kids]


def _long_narrative(kind):
    sec = []
    for i in range(1, 15):
        if kind == "hi":
            sec.append(f"**{i}. Section {i} का Pressure**\n\n**मुख्य बात:**  \n" + ("आपकी कुंडली में tendency दिखती है और clarity की ज़रूरत रहती है। " * 4) +
                       "\n\n**Astrology क्या कहती है:**  \n" + ("आपके 6th House में Mars है और 7th House का Lord भी वहीं है। " * 6) +
                       "\n\n**आपके लिए Practical मतलब:**  \n" + ("हर important बात को लिखित रूप में रखें। " * 3) + "\n\n---\n")
        else:
            sec.append(f"**{i}. Section {i} Overview**\n\n" + ("Your chart shows steady growth and clear communication needs. " * 10) + "\n\n" + ("The house lord placement supports patience here. " * 8) + "\n\n---\n")
    return "\n".join(sec)


print("\n=== pagination structure: real WeasyPrint layout has no page ending on a section heading ===")
for kind, hindi in (("hi", True), ("en", False)):
    body = convert_headings(_long_narrative(kind))
    doc = _render_pages(body, hindi)
    orphan_pages = []
    for idx, page in enumerate(doc.pages, 1):
        classes = _last_body_child_classes(page)
        if classes and "section-heading" in classes[-1]:
            orphan_pages.append(idx)
    check(f"pagination [{kind}]: layout produced {len(doc.pages)} pages, none ends on an orphaned section heading (orphans on pages {orphan_pages})", not orphan_pages)
    check(f"pagination [{kind}]: no page holds nothing but the sample-report chrome (no unexpected blank page)",
          all(len(_last_body_child_classes(p)) >= 1 for p in doc.pages[1:]))

print("\n" + "=" * 50)
print(f"TOTAL: {passed} passed, {failed} failed")
print("=" * 50)

if failed:
    sys.exit(1)
