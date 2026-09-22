# modules/focused_reports/__init__.py

"""
modules/focused_reports/ -- Focused Personalised Reports, FIRST PROTOTYPE.

Isolated prototype for "Promotion Report -- Next 12 Months". It is NOT wired
to orders, payment, the dispatcher, tasks.py, the PDF renderer, e-mail or the
frontend, and it never calls Luna itself. It only assembles

    existing Kundali  ->  existing Career Report evidence
                      ->  a few relevant transit facts
                      ->  a focused Luna prompt

Backend = authoritative astrology facts. Luna = Jyotish interpretation and
report writing. There is no prediction or scoring engine here.
"""
