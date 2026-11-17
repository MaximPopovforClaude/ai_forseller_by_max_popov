"""Additional funnel ratios; missing observations never become organic traffic.

Advertising uses WB ad attribution. Organic is only a residual estimate across
two sources, not an independently observed organic funnel or a cohort rate.
"""
from math import isfinite

RATIOS = {"cr_cart": ("carts", "clicks"), "cr_order": ("orders", "carts"), "cro": ("orders", "clicks")}


def count(value):
    if value is None:
        return None
    value = float(value)
    return value if isfinite(value) and value >= 0 else None


class Conversions:
    """Stream matched SKU-day observations; retain only six sums/validity flags."""
    def __init__(self):
        self.sums = {f"{source}_{key}": [0.0, 0.0, True] for source in ("ad", "org") for key in RATIOS}
        self.observations = 0

    def add(self, entry, advertising):
        self.observations += 1
        for source in ("ad", "org"):
            for key, fields in RATIOS.items():
                values = []
                for field in fields:
                    value = count((advertising or {}).get(field))
                    if source == "org":
                        total = count((entry or {}).get(field))
                        value = total - value if total is not None and value is not None and total >= value else None
                    values.append(value)
                state = self.sums[f"{source}_{key}"]
                if any(v is None for v in values):
                    state[2] = False
                else:
                    state[0] += values[0]
                    state[1] += values[1]

    def result(self):
        return {key: num / den if self.observations and valid and den else None
                for key, (num, den, valid) in self.sums.items()}
