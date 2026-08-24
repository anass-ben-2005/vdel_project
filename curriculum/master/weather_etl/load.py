import sqlite3


def insert_readings(conn: sqlite3.Connection, records: list[dict]) -> int:
    """Insert readings, parameterised. Returns the number of rows inserted."""
    # @gap:id=g_ld_insert concepts=[sql.select_filter] difficulty=0.25
    # @instruct: Use executemany with a parameterised INSERT (never string-format
    #            values into the SQL). Return cursor.rowcount.
    cur = conn.executemany(
        "INSERT INTO readings (temp, humidity, wind_speed, timestamp) "
        "VALUES (:temp, :humidity, :wind_speed, :timestamp)",
        records,
    )
    conn.commit()
    return cur.rowcount
    # @endgap


def readings_since(conn: sqlite3.Connection, since_ts: str) -> list[dict]:
    """Fetch all readings with timestamp >= since_ts."""
    # @gap:id=g_ld_select concepts=[sql.select_filter] difficulty=0.25
    # @instruct: SELECT all columns WHERE timestamp >= the given value, parameterised.
    cur = conn.execute("SELECT * FROM readings WHERE timestamp >= ?", (since_ts,))
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]
    # @endgap