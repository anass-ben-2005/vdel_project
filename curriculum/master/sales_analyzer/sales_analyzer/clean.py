import pandas as pd


def drop_duplicate_orders(df: pd.DataFrame) -> pd.DataFrame:
    """Drop duplicate order_id rows, keeping the one with the latest order_date."""
    # @gap:id=g_cl_dedupe concepts=[py.pandas] difficulty=0.45
    # @instruct: Sort by 'order_date', then drop_duplicates on 'order_id' keeping
    #            the LAST occurrence -- the most recent order_date for that
    #            order_id.
    return (
        df.sort_values("order_date")
        .drop_duplicates(subset="order_id", keep="last")
        .reset_index(drop=True)
    )
    # @endgap


def fill_missing_region(df: pd.DataFrame, default: str) -> pd.DataFrame:
    """Fill missing 'region' values with `default`, without a SettingWithCopyWarning."""
    # @gap:id=g_cl_fillna concepts=[py.pandas] difficulty=0.5
    # @instruct: Fill missing values in the 'region' column with `default`. Work
    #            on an explicit copy of df first (df.copy()) so this never
    #            triggers a SettingWithCopyWarning or silently mutates the
    #            caller's DataFrame.
    df = df.copy()
    df["region"] = df["region"].fillna(default)
    return df
    # @endgap
