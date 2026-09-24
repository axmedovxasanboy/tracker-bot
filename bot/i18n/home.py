"""Home: the daily figure, Coming up, Savings this month, You have — and its buttons.

`home.*`

Mirrors the web Home (tracker-frontend en.home.ts / uz.home.ts). One name per thing: "You can
spend … a day", "Coming up", "Savings this month", "You have". No engine words.
"""

EN: dict[str, str] = {
    "home.perDay": "💸 You can spend <b>~{amount}</b> a day (until {date})",
    "home.paceRunsOut": "⚠️ Lately ~{pace} a day → at that pace your money runs out around {date}",
    "home.paceOk": "✅ Lately ~{pace} a day — within your limit.",
    "home.short": "⚠️ <b>You’ll be short {amount}</b> on {date} — even if you spend nothing.",
    "home.noIncome": "Set your monthly income, and I’ll show how much you can spend each day.",

    "home.upcoming.title": "<b>Coming up</b>",
    "home.upcoming.empty": "Nothing due in the next 5 weeks.",
    "home.upcoming.row": "• {date} · {name} · {amount}",
    "home.upcoming.more": "  +{count} more in the app",
    "home.upcoming.overdue": "<b>overdue</b>",
    "home.upcoming.repayFast": "repay fast",
    "home.upcoming.recorded": "✓ recorded",

    "home.savings.title": "<b>Savings this month</b>",
    "home.savings.row": "• {name} · {paid} of {target}",
    "home.savings.done": "• {name} · ✓ {amount}",
    "home.bucket.donation": "Donation",
    "home.bucket.emergency": "Emergency fund",
    "home.bucket.investments": "Investments",
    "home.bucket.goal": "Savings goal",

    "home.have": "👛 You have <b>{amount}</b>",
    "home.have.checkedToday": "checked today",
    "home.have.checkedAgo": "checked {days} days ago",
    "home.have.notChecked": "not checked yet",

    "home.typeHint": "Type <code>50000 lunch</code> to record.",
    "home.loadError": "❌ Couldn't load Home.",

    "home.btn.add": "➕ Add",
    "home.btn.wallets": "👛 Wallets",
    "home.btn.app": "🌐 Open app",
    "home.btn.settings": "⚙️",
    "home.btn.refresh": "🔄",

    # The optional evening message (bot/reminders.py) puts one of these above Home.
    "home.remind.evening": "🌙 <b>Evening check</b>",
    "home.remind.weekly": "📅 <b>Your week</b>",
}

UZ: dict[str, str] = {
    "home.perDay": "💸 Kuniga <b>~{amount}</b> sarflashingiz mumkin ({date} gacha)",
    "home.paceRunsOut": "⚠️ Soʻnggi paytda kuniga ~{pace} → shu surʼatda pulingiz taxminan {date} kuni tugaydi",
    "home.paceOk": "✅ Soʻnggi paytda kuniga ~{pace} — chegaradan oshmayapsiz.",
    "home.short": "⚠️ <b>{date} kuni {amount} yetmay qoladi</b> — hech narsa sarflamasangiz ham.",
    "home.noIncome": "Oylik daromadingizni kiriting — har kuni qancha sarflash mumkinligini koʻrsataman.",

    "home.upcoming.title": "<b>Yaqin toʻlovlar</b>",
    "home.upcoming.empty": "Keyingi 5 haftada toʻlanadigan narsa yoʻq.",
    "home.upcoming.row": "• {date} · {name} · {amount}",
    "home.upcoming.more": "  yana {count} ta — ilovada",
    "home.upcoming.overdue": "<b>muddati oʻtgan</b>",
    "home.upcoming.repayFast": "tez qaytarish",
    "home.upcoming.recorded": "✓ yozilgan",

    "home.savings.title": "<b>Shu oydagi jamgʻarmalar</b>",
    "home.savings.row": "• {name} · {target} dan {paid}",
    "home.savings.done": "• {name} · ✓ {amount}",
    "home.bucket.donation": "Xayriya",
    "home.bucket.emergency": "Favqulodda jamgʻarma",
    "home.bucket.investments": "Investitsiyalar",
    "home.bucket.goal": "Jamgʻarma maqsadi",

    "home.have": "👛 Sizda bor: <b>{amount}</b>",
    "home.have.checkedToday": "bugun tekshirilgan",
    "home.have.checkedAgo": "{days} kun oldin tekshirilgan",
    "home.have.notChecked": "hali tekshirilmagan",

    "home.typeHint": "Yozish uchun <code>50000 tushlik</code> deb yuboring.",
    "home.loadError": "❌ Bosh sahifani yuklab boʻlmadi.",

    "home.btn.add": "➕ Qoʻshish",
    "home.btn.wallets": "👛 Hamyonlar",
    "home.btn.app": "🌐 Ilovani ochish",
    "home.btn.settings": "⚙️",
    "home.btn.refresh": "🔄",

    "home.remind.evening": "🌙 <b>Kechki koʻrik</b>",
    "home.remind.weekly": "📅 <b>Haftangiz</b>",
}
