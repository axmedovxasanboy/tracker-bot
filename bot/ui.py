"""Reusable keyboard shapes, so every screen in the bot is laid out the same way.

`keyboards.py` owns this product's own menus. This module owns the geometry: how a list of
choices becomes rows, where Back and Cancel sit, what a pager looks like. Seven routers build
screens and each one used to decide these things for itself, which is how the category picker
ended up rendering fourteen seeded categories as sixteen full-width rows and pushing Skip and
Cancel off the bottom of the most-used screen in the bot.

Two rules the builders here enforce for you:

* **Back on the left, Cancel on the right.** Always, on every screen, so the thumb learns one
  position instead of eight.
* **A destructive confirmation puts the safe choice first**, because the muscle memory built
  by every other confirm row in the bot is "the left button is the one I meant".
"""
from .i18n import t
from .keyboards import ikb

__all__ = ["NOOP", "confirm_row", "grid", "ikb", "nav", "pager"]

# A callback for a button that must exist but must do nothing. One router has to register a
# handler for it (transactions.py does today); if none does, the tap leaves a live spinner.
# Prefer a self-referential callback — see `pager`, which re-renders instead of doing nothing.
NOOP = "noop"

Row = list[tuple[str, str]]


def grid(items: list[tuple[str, str]], per_row: int = 2) -> list[Row]:
    """Lay (text, callback_data) pairs out N to a row.

    Two per row is the default because a Telegram inline keyboard scrolls with the message,
    not inside itself: a long one-per-row list pushes the actions underneath it out of sight.
    Drop to one per row only when the labels are genuinely long (a card name plus a balance).
    """
    per_row = max(1, per_row)
    return [items[i:i + per_row] for i in range(0, len(items), per_row)]


def nav(chat_id: int | None, back: str | None = None, cancel: str | None = None,
        menu: bool = False) -> Row:
    """The navigation row: Back on the left, Menu in the middle, Cancel on the right.

    `back` and `cancel` are callback_data strings; pass None to leave that button out. Returns
    an empty list when nothing is asked for — `ikb` drops empty rows, so appending the result
    unconditionally is safe.
    """
    row: Row = []
    if back:
        row.append((t(chat_id, "common.back"), back))
    if menu:
        row.append((t(chat_id, "common.menu"), "menu:home"))
    if cancel:
        row.append((t(chat_id, "common.cancel"), cancel))
    return row


def pager(chat_id: int | None, page: int, total: int, prefix: str) -> Row:
    """◀️ 2/5 ▶️ — `page` is 0-based, the label is not.

    `prefix` is prepended verbatim to the target page number, so `"txpage:"` produces
    `"txpage:3"`. The counter in the middle points at the current page rather than at a dead
    `noop`: re-rendering the page the user is already on costs one edit that Telegram answers
    with "message is not modified" (which `common.show` swallows), and it turns a button that
    used to do nothing into a refresh.
    """
    total = max(1, total)
    row: Row = []
    if page > 0:
        row.append(("◀️", f"{prefix}{page - 1}"))
    row.append((t(chat_id, "ui.pageOf", page=page + 1, total=total), f"{prefix}{page}"))
    if page + 1 < total:
        row.append(("▶️", f"{prefix}{page + 1}"))
    return row


def confirm_row(chat_id: int | None, ok_cb: str, cancel_cb: str, *,
                ok_key: str = "common.confirm", cancel_key: str = "common.cancel",
                destructive: bool = False) -> Row:
    """Confirm on the left, Cancel on the right — reversed when the confirm destroys data.

    `destructive=True` also defaults the label to "Yes, delete", since a bare "Confirm" next to
    a Cancel is exactly the pair a thumb picks wrong.
    """
    if destructive and ok_key == "common.confirm":
        ok_key = "common.deleteYes"
    ok = (t(chat_id, ok_key), ok_cb)
    cancel = (t(chat_id, cancel_key), cancel_cb)
    return [cancel, ok] if destructive else [ok, cancel]

