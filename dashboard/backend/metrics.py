"""Honest summary statistics for the dashboard.

Missing values are represented as ``None`` (JSON ``null``) and the UI renders
them as "not recorded" — never as 0 or an invented number.
"""

import statistics


def _round(x, ndigits=3):
    return round(x, ndigits) if x is not None else None


def summarize(values, ndigits=3):
    """Return {n, median, p95, max} for a list of finite numbers.

    ``None``/non-finite entries are dropped.  An empty list yields all-None
    fields with ``n == 0`` (callers render "not recorded").
    """
    finite = [float(v) for v in values if v is not None and _is_finite(v)]
    finite.sort()
    n = len(finite)
    if n == 0:
        return {"n": 0, "median": None, "p95": None, "max": None}
    p95 = finite[max(0, int(0.95 * n) - 1)]
    return {
        "n": n,
        "median": _round(statistics.median(finite), ndigits),
        "p95": _round(p95, ndigits),
        "max": _round(finite[-1], ndigits),
    }


def _is_finite(v):
    try:
        return abs(float(v)) != float("inf") and float(v) == float(v)
    except (TypeError, ValueError):
        return False


def histogram(values, bin_edges):
    """Bucket finite values into right-open bins ``[lo, hi)``.

    ``bin_edges`` is a list of N edges defining N-1 bins; the last edge is the
    inclusive top.  Returns a list of {lo, hi, count} plus an ``overflow`` count.
    """
    bins = [{"lo": bin_edges[i], "hi": bin_edges[i + 1], "count": 0}
            for i in range(len(bin_edges) - 1)]
    overflow = 0
    for v in values:
        if v is None or not _is_finite(v):
            continue
        placed = False
        for i in range(len(bin_edges) - 1):
            lo, hi = bin_edges[i], bin_edges[i + 1]
            if i == len(bin_edges) - 2:
                if lo <= v <= hi:
                    bins[i]["count"] += 1
                    placed = True
                    break
            elif lo <= v < hi:
                bins[i]["count"] += 1
                placed = True
                break
        if not placed:
            overflow += 1
    return {"bins": bins, "overflow": overflow}
