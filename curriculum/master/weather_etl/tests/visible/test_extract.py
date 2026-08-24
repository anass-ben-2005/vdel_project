"""Visible smoke test for weather_etl/extract.py -- runs STANDALONE, nothing injected.

VDEL_REDESIGN.md 8.3: "Visible smoke tests the student can run locally (`pytest
tests/visible`) -- immediate feedback, while hidden tests stay hidden. This is
nbgrader's exact split." Deliberately thin: one ordinary, well-formed-input case for
parse_response. Missing-key handling, the retry loop, and the max-attempts failure are
the hidden suite's job (tests/hidden/test_extract.py, gap_id g_ext_parse / g_ext_retry)
-- this file exists for a quick "does it basically work" signal, not full correctness.

No conftest.py, no @pytest.mark.gap, no assessment/test_runner.py involvement of any
kind: this file is copied wholesale into every rendered student repo
(scripts/render_student_repo.py) and run with a bare `pytest tests/visible`, on the
student's own machine, before anything is pushed.
"""
from weather_etl.extract import parse_response


def test_parse_response_extracts_known_fields():
    result = parse_response({"current": {"temp": 20, "humidity": 55, "wind_speed": 3}})
    assert result == {"temp": 20, "humidity": 55, "wind_speed": 3}
