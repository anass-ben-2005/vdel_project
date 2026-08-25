import pandas as pd


def revenue_by_region(df: pd.DataFrame) -> pd.DataFrame:
    """Total revenue (quantity * unit_price) per region."""
    # @gap:id=g_ag_revenue concepts=[sql.aggregation] difficulty=0.5
    # @instruct: Compute a 'revenue' column as quantity * unit_price, then group
    #            by 'region' and sum 'revenue'. Return a DataFrame with columns
    #            ['region', 'revenue'].
    df = df.assign(revenue=df["quantity"] * df["unit_price"])
    return df.groupby("region", as_index=False)["revenue"].sum()
    # @endgap


def top_products(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """The n products with the highest total quantity sold."""
    # @gap:id=g_ag_top concepts=[py.data_structures] difficulty=0.35
    # @instruct: Group by 'product', sum 'quantity', sort descending, and return
    #            exactly the top n rows -- watch the off-by-one on n.
    totals = df.groupby("product", as_index=False)["quantity"].sum()
    return totals.sort_values("quantity", ascending=False).head(n).reset_index(drop=True)
    # @endgap
