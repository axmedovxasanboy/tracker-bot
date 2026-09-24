"""Shared words: buttons every screen uses, short dates, failures, the income guard, Settings.

`common.*` `guard.*` `lang.*` `settings.*`

Uzbek is Latin script with ʻ (Oʻzbek), and follows the web app's wording.
"""

EN: dict[str, str] = {
    # Buttons
    "common.cancel": "✖️ Cancel",
    "common.back": "⬅️ Back",
    "common.home": "🏠 Home",
    "common.skip": "⏭ Skip",
    "common.retry": "🔄 Retry",
    "common.cashBtn": "💵 Cash",
    "common.cash": "Cash",
    # Status
    "common.saving": "⏳ Saving…",
    "common.cancelled": "Cancelled.",
    # Failures
    "common.sessionExpired": "🔒 You're logged out. Please log in.",
    "common.serverUnreachable": "❌ Couldn't reach the server. Try again in a minute.",
    "common.notForYou": "🚫 This bot is private.",
    "common.oldButton": "That button is from an older screen.",
    "common.positiveNumber": "Send a positive number.",
    "common.sendNumberExample": "Send a number (e.g. 0 or 250000).",
    # Short dates
    "common.today": "Today",
    "common.tomorrow": "Tomorrow",
    "common.yesterday": "Yesterday",
    "common.mon.1": "Jan", "common.mon.2": "Feb", "common.mon.3": "Mar", "common.mon.4": "Apr",
    "common.mon.5": "May", "common.mon.6": "Jun", "common.mon.7": "Jul", "common.mon.8": "Aug",
    "common.mon.9": "Sep", "common.mon.10": "Oct", "common.mon.11": "Nov", "common.mon.12": "Dec",
    "common.wd.0": "Mon", "common.wd.1": "Tue", "common.wd.2": "Wed", "common.wd.3": "Thu",
    "common.wd.4": "Fri", "common.wd.5": "Sat", "common.wd.6": "Sun",

    # The backend refuses every money write until the monthly income is set.
    "guard.incomeTitle": "⚠️ <b>Set your monthly income first</b>",
    "guard.incomeBody": "Nothing can be recorded until it is set — it is what the daily figure "
                        "and your savings are worked out from.",

    "lang.changed": "Language set to English.",

    # Settings
    "settings.title": "⚙️ <b>Settings</b>",
    "settings.income": "Monthly income: <b>{amount}</b>",
    "settings.notSet": "not set",
    "settings.hint": "Categories, loans, bills and goals are in the web app.",
    "settings.langBtn": "🌐 Oʻzbekcha",
    "settings.incomeBtn": "💰 Monthly income",
    "settings.helpBtn": "❓ Help",
    "settings.lockBtn": "🔒 Log out",
    "settings.incomeTitle": "💰 <b>Monthly income</b>",
    "settings.incomeAsk": "Send your monthly stable income, e.g. <code>8000000</code> or <code>8m</code>.",
    "settings.incomeSaved": "✅ Monthly income saved: {amount}",
}

UZ: dict[str, str] = {
    "common.cancel": "✖️ Bekor qilish",
    "common.back": "⬅️ Orqaga",
    "common.home": "🏠 Bosh sahifa",
    "common.skip": "⏭ Oʻtkazib yuborish",
    "common.retry": "🔄 Qayta urinish",
    "common.cashBtn": "💵 Naqd",
    "common.cash": "Naqd",
    "common.saving": "⏳ Saqlanmoqda…",
    "common.cancelled": "Bekor qilindi.",
    "common.sessionExpired": "🔒 Tizimdan chiqdingiz. Iltimos, qaytadan kiring.",
    "common.serverUnreachable": "❌ Serverga ulanib boʻlmadi. Bir daqiqadan keyin qayta urinib koʻring.",
    "common.notForYou": "🚫 Bu bot shaxsiy.",
    "common.oldButton": "Bu tugma eski ekrandan.",
    "common.positiveNumber": "Musbat son yuboring.",
    "common.sendNumberExample": "Son yuboring (masalan, 0 yoki 250000).",
    "common.today": "Bugun",
    "common.tomorrow": "Ertaga",
    "common.yesterday": "Kecha",
    "common.mon.1": "yan", "common.mon.2": "fev", "common.mon.3": "mar", "common.mon.4": "apr",
    "common.mon.5": "may", "common.mon.6": "iyun", "common.mon.7": "iyul", "common.mon.8": "avg",
    "common.mon.9": "sen", "common.mon.10": "okt", "common.mon.11": "noy", "common.mon.12": "dek",
    "common.wd.0": "Dush", "common.wd.1": "Sesh", "common.wd.2": "Chor", "common.wd.3": "Pay",
    "common.wd.4": "Jum", "common.wd.5": "Shan", "common.wd.6": "Yak",

    "guard.incomeTitle": "⚠️ <b>Avval oylik daromadingizni kiriting</b>",
    "guard.incomeBody": "U kiritilmaguncha hech narsa yozib boʻlmaydi — kunlik summa va "
                        "jamgʻarmalaringiz shundan hisoblanadi.",

    "lang.changed": "Til oʻzbekchaga oʻzgartirildi.",

    "settings.title": "⚙️ <b>Sozlamalar</b>",
    "settings.income": "Oylik daromad: <b>{amount}</b>",
    "settings.notSet": "kiritilmagan",
    "settings.hint": "Kategoriyalar, qarzlar, toʻlovlar va maqsadlar veb-ilovada.",
    "settings.langBtn": "🌐 English",
    "settings.incomeBtn": "💰 Oylik daromad",
    "settings.helpBtn": "❓ Yordam",
    "settings.lockBtn": "🔒 Chiqish",
    "settings.incomeTitle": "💰 <b>Oylik daromad</b>",
    "settings.incomeAsk": "Oylik barqaror daromadingizni yuboring, masalan <code>8000000</code> yoki <code>8m</code>.",
    "settings.incomeSaved": "✅ Oylik daromad saqlandi: {amount}",
}
