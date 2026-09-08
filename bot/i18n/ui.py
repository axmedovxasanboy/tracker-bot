"""Shared UI chrome that is not `common.*`: pagers, grids, confirm rows, wallet pickers.

`ui.*`  — owned by F3, alongside `bot/ui.py`.

Add keys under the `ui.` prefix only; the merge in `__init__` rejects a key that belongs to
another module's namespace, and rejects a key present in one language and not the other.

Deliberately small. A string only belongs here if a *primitive* in `bot/ui.py`,
`bot/keyboards.py` or `bot/common.py` renders it — anything a screen renders belongs to that
screen's own module, and anything more than one screen renders is already in `common.py`.
"""

EN: dict[str, str] = {
    # The button that turns the "set your monthly income first" wall into a way through it.
    # Named the way the web app's Settings page names the same field ("Monthly stable income")
    # and the way the bot's own Settings screen labels it, so the owner is not asked to
    # believe that "monthly income" and "stable income" are two different figures.
    "ui.setIncome": "💰 Set stable income",

    # The middle of the pager row. Both languages print the same two numbers today; the key
    # exists so `ui.pager` is not hard-coding a format, and so this can become "Page 2 of 5"
    # in one place if a screen ever has room for it.
    "ui.pageOf": "{page}/{total}",
}

UZ: dict[str, str] = {
    "ui.setIncome": "💰 Barqaror daromadni kiritish",
    "ui.pageOf": "{page}/{total}",
}
