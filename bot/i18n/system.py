"""Bot-level text: the command list, /help, the error handler's apology.

`system.*`

`system.cmd.*` is read twice — by setMyCommands (the blue command menu) and by /help — so the two
cannot drift. Command descriptions are plain text: Telegram parses no HTML there.
"""

EN: dict[str, str] = {
    "system.cmd.start": "Home — how much you can spend today",
    "system.cmd.add": "Record money in or out",
    "system.cmd.settings": "Language, monthly income, log out",
    "system.cmd.help": "What this bot does",
    "system.cmd.lock": "Log out",
    "system.cmd.cancel": "Stop the step you are on",

    "system.help.title": "❓ <b>Tracker bot</b>",
    "system.help.body": (
        "Three things, fast:\n"
        "• <b>Record</b> — type <code>50000 lunch</code> (or <code>+2000000 salary</code> for "
        "income) and tap Save. Or ➕ Add.\n"
        "• <b>Pay</b> — tap a Pay button on Home, then the wallet.\n"
        "• <b>Check wallets</b> — 👛 Wallets shows every balance; Check wallets fixes them.\n\n"
        "Home says how much you can spend a day. ☰ More has everything the web app has: History, "
        "Savings, Loans &amp; bills, Profile and Settings."
    ),
    "system.help.commandsTitle": "<b>Commands</b>",
    "system.help.cmdLine": "/{cmd} — {desc}",
    "system.help.stuck": "Stuck halfway? Send /cancel — nothing is saved until you tap Save.",

    # Not "please try again": a write that reached the backend may already have moved money.
    "system.error.title": "⚠️ <b>Something went wrong</b>",
    "system.error.body": "That step failed before it could finish. It may or may not have been "
                         "saved, so look on Home before you repeat it.",
    "system.error.toast": "Something went wrong",
}

UZ: dict[str, str] = {
    "system.cmd.start": "Bosh sahifa — bugun qancha sarflash mumkin",
    "system.cmd.add": "Pul kirimi yoki chiqimini yozish",
    "system.cmd.settings": "Til, oylik daromad, chiqish",
    "system.cmd.help": "Bot nima qiladi",
    "system.cmd.lock": "Tizimdan chiqish",
    "system.cmd.cancel": "Turgan qadamingizni toʻxtatish",

    "system.help.title": "❓ <b>Tracker bot</b>",
    "system.help.body": (
        "Uchta ish, tez:\n"
        "• <b>Yozish</b> — <code>50000 tushlik</code> deb yozing (daromad uchun "
        "<code>+2000000 maosh</code>) va Saqlashni bosing. Yoki ➕ Qoʻshish.\n"
        "• <b>Toʻlash</b> — Bosh sahifadagi Toʻlash tugmasini, keyin hamyonni bosing.\n"
        "• <b>Hamyonlarni tekshirish</b> — 👛 Hamyonlar har bir balansni koʻrsatadi; "
        "Hamyonlarni tekshirish ularni toʻgʻrilaydi.\n\n"
        "Bosh sahifa kuniga qancha sarflash mumkinligini aytadi. ☰ Yana boʻlimida veb-ilovadagi "
        "hamma narsa bor: Tarix, Jamgʻarmalar, Qarzlar va toʻlovlar, Profil va Sozlamalar."
    ),
    "system.help.commandsTitle": "<b>Buyruqlar</b>",
    "system.help.cmdLine": "/{cmd} — {desc}",
    "system.help.stuck": "Yarim yoʻlda qoldingizmi? /cancel yuboring — Saqlashni bosmaguningizcha "
                         "hech narsa saqlanmaydi.",

    "system.error.title": "⚠️ <b>Nimadir xato ketdi</b>",
    "system.error.body": "Bu qadam oxirigacha yetmay uzilib qoldi. Saqlangan boʻlishi ham, "
                         "saqlanmagan boʻlishi ham mumkin — takrorlashdan oldin Bosh sahifaga qarang.",
    "system.error.toast": "Nimadir xato ketdi",
}
