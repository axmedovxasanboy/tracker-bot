"""Bot-level plumbing the user can see: /help, the error handler's apology, boot notices.

`system.*`  — owned by F4, alongside `bot/main.py` and `bot/errors.py`.

Two conventions here are load-bearing:

* `system.cmd.*` is read TWICE — once by `setMyCommands` (the blue command menu Telegram
  draws) and once by the /help screen, which builds its command list out of the same keys.
  One source, so the two can never drift into telling the owner different things. The
  descriptions are therefore plain text: Telegram does not parse HTML in a command list.
* The section lines take the screen's name as `{name}` rather than spelling it out, and
  `/help` fills them from `menu.page.*`. The web app renamed three screens (Home, Plan,
  Wallets — see GLOSSARY.md); pulling the name from the menu's own key means /help cannot
  describe a button by a word that is no longer written on it.
"""

EN: dict[str, str] = {
    # --- Command descriptions: the blue menu AND the /help list ---
    "system.cmd.start": "Log in, or see where your money stands",
    "system.cmd.add": "Record money in or out",
    "system.cmd.menu": "Every section",
    "system.cmd.help": "What this bot can do",
    "system.cmd.lock": "End this session",
    "system.cmd.cancel": "Stop the step you are on",

    # --- /help ---
    "system.help.title": "❓ <b>Tracker bot</b>",
    "system.help.intro": "🏠 Home is your advisor: what you have, what's coming, what's still to "
                         "pay and set aside, what's free — and a button for each next step. It "
                         "also messages you in the evening when something needs you. Everything "
                         "else is under ☰ More, with the same account and figures as the web app.",
    "system.help.sectionsTitle": "<b>Sections</b>",
    "system.help.home": "{name} — spendable money, net worth, this month so far",
    "system.help.plan": "{name} — where this month's money is meant to go, bucket by bucket",
    "system.help.months": "{name} — close a month with your real end-of-month balances",
    "system.help.transactions": "{name} — add, review and fix what you spent or earned",
    "system.help.wallets": "{name} — your cards and cash, and what is on each",
    "system.help.finance": "{name} — debts, loans, subscriptions, donations, investments, goals",
    "system.help.categories": "{name} — the two-level list every transaction is filed under",
    "system.help.settings": "{name} — language, stable income, danger zone",
    "system.help.commandsTitle": "<b>Commands</b>",
    "system.help.cmdLine": "/{cmd} — {desc}",
    "system.help.quickTitle": "<b>Quick add</b>",
    # The second sentence is not padding. Typed text only becomes a draft when no form is
    # open, so the first sentence is advice a stuck owner cannot act on — and /help is the
    # screen a stuck owner opens. /add carries the same syntax and works from every state.
    "system.help.quick": "Send <code>50000 lunch</code> to book an expense in one message, or "
                         "<code>+2000000 salary</code> for income. You get a draft to check "
                         "before anything is saved. Another form already open? "
                         "<code>/add 50000 lunch</code> works from any screen and closes "
                         "that form for you.",
    "system.help.stuck": "Halfway through a form and want out? Send /cancel — nothing is written "
                         "until you confirm.",

    # --- The catch-all error screen (bot/errors.py) ---
    # Deliberately NOT common.somethingWentWrong: that one says "please try again", which is
    # the wrong advice after a write of unknown outcome. A POST that reached the backend and
    # then failed to render its confirmation has already moved money.
    "system.error.title": "⚠️ <b>Something went wrong</b>",
    "system.error.body": "That step failed before it could finish. It may or may not have been "
                         "saved, so open the screen and look before you repeat it.",
    "system.error.toast": "Something went wrong",
}

UZ: dict[str, str] = {
    "system.cmd.start": "Kirish yoki pulingiz holati",
    "system.cmd.add": "Pul kirimi yoki chiqimini yozish",
    "system.cmd.menu": "Barcha boʻlimlar",
    "system.cmd.help": "Bot nima qila oladi",
    "system.cmd.lock": "Sessiyani yakunlash",
    "system.cmd.cancel": "Turgan qadamingizni toʻxtatish",

    "system.help.title": "❓ <b>Tracker bot</b>",
    "system.help.intro": "🏠 Bosh sahifa — maslahatchingiz: nima bor, nima keladi, yana nimani "
                         "toʻlash va ajratish kerak, qancha boʻsh qoladi — va har bir keyingi "
                         "qadam uchun tugma. Biror ish boʻlsa, kechqurun oʻzi yozadi. Qolgan "
                         "hammasi ☰ Yana ichida, veb-ilova bilan bitta hisob va raqamlar.",
    "system.help.sectionsTitle": "<b>Boʻlimlar</b>",
    "system.help.home": "{name} — sarflash mumkin boʻlgan pul, sof boylik va shu oy manzarasi",
    "system.help.plan": "{name} — bu oydagi pul qayerga ketishi kerakligi, bandma-band",
    "system.help.months": "{name} — oyni haqiqiy oy oxiri balanslari bilan yopish",
    "system.help.transactions": "{name} — xarajat va daromadni qoʻshish, koʻrish, tuzatish",
    "system.help.wallets": "{name} — kartalaringiz va naqd pul, har birida qancha borligi",
    "system.help.finance": "{name} — qarzlar, kreditlar, obunalar, xayriya, investitsiyalar, "
                           "jamgʻarma maqsadlari",
    "system.help.categories": "{name} — har bir tranzaksiya yoziladigan ikki bosqichli roʻyxat",
    "system.help.settings": "{name} — til, barqaror daromad, xavfli hudud",
    "system.help.commandsTitle": "<b>Buyruqlar</b>",
    "system.help.cmdLine": "/{cmd} — {desc}",
    "system.help.quickTitle": "<b>Tez qoʻshish</b>",
    "system.help.quick": "Bitta xabar bilan xarajat yozish uchun <code>50000 tushlik</code>, "
                         "daromad uchun esa <code>+2000000 oylik</code> yuboring. Saqlashdan "
                         "oldin tekshirib olishingiz uchun qoralama koʻrsatiladi. Boshqa "
                         "shakl ochiq boʻlsa ham, <code>/add 50000 tushlik</code> istalgan "
                         "ekranda ishlaydi va oʻsha shaklni oʻzi yopadi.",
    "system.help.stuck": "Shakl oʻrtasida qolib ketdingizmi? /cancel yuboring — siz "
                         "tasdiqlamaguningizcha hech narsa yozilmaydi.",

    "system.error.title": "⚠️ <b>Nimadir xato ketdi</b>",
    "system.error.body": "Bu qadam oxirigacha yetmay uzilib qoldi. Saqlangan boʻlishi ham, "
                         "saqlanmagan boʻlishi ham mumkin — qaytadan urinishdan oldin ekranni "
                         "ochib koʻring.",
    "system.error.toast": "Nimadir xato ketdi",
}
