"""The seven evaluation variables (Module 1).

Every module here is transcribed from VDEL_Modules_1_2_Build.md Part B. The function
signatures, formulas, constants and return shapes are the document's. This package
deliberately imposes no uniform return contract of its own -- the variables return
different shapes because they answer different questions, and normalising them here
would mean rewriting the documented interfaces.

  mastery.py          V1  BKT + KT-IDEM + Beta posterior
  habits.py           V2  Engineering Discipline, V3  Effort Regulation
  pace.py             V4  Learning Pace (censoring-aware)
  error_response.py   V5  Jadud/Watwin + wheel-spinning
  error_frequency.py  V6  opportunity-normalised + recurrence

V7 (Help-Seeking) has no module: it needs the coach's interaction log, which does not
exist until Module 7. The nullable learner_features.help_seeking column is its seam.
"""
