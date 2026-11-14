"""Oracle hints: where the truth is for each item, read from its label.

This is the one place the arms comparison touches labels, and it is only for the `oracle_pull`
arm, the upper bound (labels instead of detection). The hints go to the runner as plain data; the
runner itself never reads a label. Test and held-out labels stay sealed until the freeze, because
`EvalStore.label` refuses them before it.
"""

from __future__ import annotations

from currant.evalset import EvalStore, ItemRow
from currant.harness.arms import OracleHint


def oracle_hints(evals: EvalStore, items: list[ItemRow]) -> dict[str, OracleHint]:
    """A hint for every item that has a stale sentence replaced by an update on another page."""
    hints: dict[str, OracleHint] = {}
    for item in items:
        label = evals.label(item.item_id)
        update_page, quote = label.get("update_page_id"), label.get("update_quote")
        if not update_page or not quote:
            continue  # a clean item has no update page: nothing was replaced, nothing to pull
        start, end = label["stale_span"]
        hints[item.item_id] = OracleHint(
            label["stale_page_id"], int(start), int(end), label["stale_quote"],
            str(update_page), str(quote),
        )  # fmt: skip
    return hints
