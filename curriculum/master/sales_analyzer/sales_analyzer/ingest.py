import pandas as pd


def read_sales_csv(path: str) -> pd.DataFrame:
    """Read the sales CSV, coercing dtypes and tolerating one malformed row.

    Columns: order_id, order_date, region, product, quantity, unit_price.
    """
    # @gap:id=g_ing_dtype concepts=[py.pandas] difficulty=0.4
    # @instruct: Read the CSV at `path` with pandas, parsing the 'order_date'
    #            column as a real date via parse_dates=.
    df = pd.read_csv(path, parse_dates=["order_date"])
    # @endgap

    # @gap:id=g_ing_malformed concepts=[py.errors_debugging] difficulty=0.4
    # @instruct: A row's 'quantity' or 'unit_price' may be non-numeric (a
    #            malformed row). Coerce both columns with
    #            pd.to_numeric(..., errors="coerce") and drop any row where
    #            either becomes NaN, instead of letting one bad row crash the
    #            whole read.
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce")
    df["unit_price"] = pd.to_numeric(df["unit_price"], errors="coerce")
    df = df.dropna(subset=["quantity", "unit_price"]).reset_index(drop=True)
    # @endgap

    return df
