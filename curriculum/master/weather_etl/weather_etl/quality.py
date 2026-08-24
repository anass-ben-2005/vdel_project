def assert_no_nulls(records: list[dict], required_fields: list[str]) -> None:
    """Raise AssertionError if any record is missing a required field."""
    # @gap:id=g_qa_nulls concepts=[py.testing] difficulty=0.4
    # @instruct: For every record and every required field, assert the field is
    #            present and not None. Include the record index in the message.
    for i, r in enumerate(records):
        for field in required_fields:
            assert r.get(field) is not None, f"record {i} missing '{field}'"
    # @endgap


def assert_reasonable_range(records: list[dict], field: str, lo: float, hi: float) -> None:
    """Raise AssertionError if any record's field falls outside [lo, hi]."""
    # @gap:id=g_qa_range concepts=[py.testing] difficulty=0.45
    # @instruct: For every record, assert lo <= record[field] <= hi. Include the
    #            offending value in the message.
    for i, r in enumerate(records):
        val = r.get(field)
        assert lo <= val <= hi, f"record {i} field '{field}'={val} outside [{lo},{hi}]"
    # @endgap