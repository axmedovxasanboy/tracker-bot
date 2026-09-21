"""Shared chrome: the words that appear on more than one screen.

`common.*` `guard.*` `lang.*` `settings.*`

This module is FROZEN. Every other area module may read these keys but none may redefine
them — the merge in `__init__` raises on a duplicate, so a second definition anywhere is a
hard import error, not a silently-shadowed button label. If a word here reads wrong on one
screen, the fix is a key in that screen's own module, not an edit here.
"""

EN: dict[str, str] = {
    # Language / settings
    "lang.title": "🌐 <b>Language</b>",
    "lang.pick": "Pick the language for this chat:",
    "lang.changed": "Language set to English.",
    "settings.language": "🌐 Language",
    "settings.backToSettings": "⬅️ Settings",
    # Buttons — every screen's navigation row is built out of these four
    "common.cancel": "✖️ Cancel",
    "common.back": "⬅️ Back",
    "common.menu": "🏠 Home",
    "common.confirm": "✅ Confirm",
    "common.skip": "⏭ Skip",
    "common.add": "➕ Add",
    "common.edit": "✏️ Edit",
    "common.delete": "🗑 Delete",
    "common.deleteYes": "✅ Yes, delete",
    "common.yes": "✅ Yes",
    "common.no": "✖️ No",
    "common.today": "📅 Today",
    "common.retry": "🔄 Retry",
    # Transient status. `saving` replaces the screen (keyboard removed) for the whole
    # duration of a write, so it is the double-submit guard as much as it is feedback.
    "common.saving": "⏳ Saving…",
    "common.loading": "⏳ Loading…",
    "common.done": "✅ Done",
    "common.cancelled": "Cancelled.",
    "common.none": "—",
    "common.nothingHere": "Nothing here yet.",
    # Failures
    "common.sessionExpired": "🔒 Session expired. Please log in.",
    "common.serverUnreachable": "❌ Couldn't reach the server.",
    "common.somethingWentWrong": "❌ Something went wrong. Please try again.",
    "common.notForYou": "🚫 This bot is private.",
    "common.unknownSection": "Unknown section.",
    # Input validation
    "common.positiveNumber": "Send a positive number.",
    "common.sendNumberExample": "Send a number (e.g. 0 or 250000).",
    # Money words used as data labels, not as sentences
    "common.cash": "Cash",
    "common.cashBtn": "💵 Cash",
    "common.typeIncome": "Income",
    "common.typeExpense": "Expense",
    "common.typeBoth": "Both",
    # Income guard — the backend refuses every money write until stable income is set
    "guard.incomeTitle": "⚠️ <b>Set your monthly income first</b>",
    "guard.incomeBody": "Nothing can be recorded until it is set — your tier and every allocation "
                        "figure are calculated from it. Set it in Settings to continue.",
}

UZ: dict[str, str] = {
    "lang.title": "🌐 <b>Til</b>",
    "lang.pick": "Ushbu chat uchun tilni tanlang:",
    "lang.changed": "Til oʻzbekchaga oʻzgartirildi.",
    "settings.language": "🌐 Til",
    "settings.backToSettings": "⬅️ Sozlamalar",
    "common.cancel": "✖️ Bekor qilish",
    "common.back": "⬅️ Orqaga",
    "common.menu": "🏠 Bosh sahifa",
    "common.confirm": "✅ Tasdiqlash",
    "common.skip": "⏭ Oʻtkazib yuborish",
    "common.add": "➕ Qoʻshish",
    "common.edit": "✏️ Tahrirlash",
    "common.delete": "🗑 Oʻchirish",
    "common.deleteYes": "✅ Ha, oʻchirilsin",
    "common.yes": "✅ Ha",
    "common.no": "✖️ Yoʻq",
    "common.today": "📅 Bugun",
    "common.retry": "🔄 Qayta urinish",
    "common.saving": "⏳ Saqlanmoqda…",
    "common.loading": "⏳ Yuklanmoqda…",
    "common.done": "✅ Tayyor",
    "common.cancelled": "Bekor qilindi.",
    "common.none": "—",
    "common.nothingHere": "Hozircha hech narsa yoʻq.",
    "common.sessionExpired": "🔒 Sessiya tugadi. Iltimos, qaytadan kiring.",
    "common.serverUnreachable": "❌ Serverga ulanib boʻlmadi.",
    "common.somethingWentWrong": "❌ Nimadir xato ketdi. Qayta urinib koʻring.",
    "common.notForYou": "🚫 Bu bot shaxsiy.",
    "common.unknownSection": "Nomaʼlum boʻlim.",
    "common.positiveNumber": "Musbat son yuboring.",
    "common.sendNumberExample": "Son yuboring (masalan, 0 yoki 250000).",
    "common.cash": "Naqd",
    "common.cashBtn": "💵 Naqd",
    "common.typeIncome": "Daromad",
    "common.typeExpense": "Xarajat",
    "common.typeBoth": "Ikkalasi",
    "guard.incomeTitle": "⚠️ <b>Avval oylik daromadingizni kiriting</b>",
    "guard.incomeBody": "U kiritilmaguncha hech narsa yozib qoʻyilmaydi — darajangiz va barcha "
                        "taqsimot hisob-kitoblari shundan olinadi. Davom etish uchun Sozlamalardan kiriting.",
}
