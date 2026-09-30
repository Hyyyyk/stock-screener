"""Streamlit과 독립적인 모집단·백분위·필터 계산."""
import pandas as pd

import data


def prepare_universe(df, markets, min_cap=0, drop_funds=True, only_up=False, only_turn=False):
    universe = df[df.market.isin(markets)]
    if drop_funds:
        universe = universe[universe.kind.fillna("EQUITY") == "EQUITY"]
    if min_cap:
        universe = universe[universe.market_cap_usd >= min_cap]
    if only_up:
        universe = universe[universe.rev_up_3y]
    if only_turn:
        universe = universe[universe.turnaround]
    return universe.assign(size_bucket=universe.groupby("country").market_cap.transform(data.size_bucket))


def percentiles(universe, core, by_sector):
    applicable, columns = {}, {}
    for _, col, _, higher_better, _ in core:
        applicable[col] = data.metric_applicable(universe, col)
        ranked = universe.copy()
        ranked.loc[~applicable[col], col] = pd.NA
        columns[col] = data.peer_pct(ranked, col, higher_better, by_sector)
    return pd.DataFrame(columns), applicable


def apply_filters(base, filters, cuts, pct, applicable, by_sector, roe_floor=None):
    steps, current = [("전체", base)], base
    for stage, col, direction, *_ in filters:
        if col not in cuts:
            continue
        value = cuts[col]
        if by_sector:
            keep = pct[col].loc[current.index] >= 100 - value
            if col == "roe" and roe_floor is not None:
                keep &= current.roe >= roe_floor
        else:
            keep = current[col] <= value if direction == "max" else current[col] >= value
        current = current[keep.fillna(False) | ~applicable[col].loc[current.index]]
        steps.append((stage, current))
    return steps
