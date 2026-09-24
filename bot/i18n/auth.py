"""The front door: welcome, login, signup, lock.

`auth.*`

`auth.accountCreated` / `auth.loggedIn` are the two halves of `auth.loginSuccess`'s {verb}.
They are fragments on purpose and the two languages put them in different places in the
sentence — which is exactly why they are separate keys and not concatenated at the call site.

`auth.err.*` are the backend's own authentication sentences, translated. The backend answers
in English prose and gives no code to key off, so `bot/routers/auth.py` matches the exact
sentence; when the wording on the Java side changes the bot falls back to printing it
verbatim, which is what it did for all four before.

`auth.loggedOut` is sent when the backend rejects the saved login (bot/keepalive.py).
"""

EN: dict[str, str] = {
    # ── The welcome screen ──────────────────────────────────────────────────
    "auth.loginButton": "🔑 Log in",
    "auth.setupButton": "🆕 Set this bot up",
    # Honest about what this is. Tracker is one person's account — there is no "sign up and
    # get your own copy" here — and the guard in bot/middlewares.py enforces exactly that, so
    # the welcome screen should not read like an invitation to the world.
    "auth.welcome": (
        "👋 <b>Tracker</b> — one person's money, in one chat.\n\n"
        "Record in one message, pay from a button, check your wallets. This bot serves a single "
        "account — log in with it to continue. You stay logged in until you log out."
    ),
    "auth.welcomeFirstRun": (
        "👋 <b>Tracker</b> — one person's money, in one chat.\n\n"
        "No account exists yet, so the next username and password typed here <b>create</b> it, "
        "and this chat becomes its owner for good. If you did not set this bot up, close it and "
        "tell whoever did.\n\n"
        "The password must be at least 6 characters."
    ),
    "auth.pleaseLoginFirst": "🔒 Please log in first.",

    # ── The typed flow ──────────────────────────────────────────────────────
    "auth.enterUsername": "👤 Enter your <b>username</b>:",
    "auth.enterPassword": "🔑 Now enter your <b>password</b>:",
    "auth.chooseUsername": "👤 Pick a <b>username</b> for the new account:",
    "auth.choosePassword": "🔑 Now pick a <b>password</b> — at least 6 characters:",
    "auth.usernameNeeded": "👤 Send your username as plain text.",
    "auth.passwordNeeded": "🔑 Send your password as plain text.",
    "auth.commandDuringLogin": (
        "🤔 <code>/{cmd}</code> isn't a command I know, and you're in the middle of logging in — "
        "so I haven't taken it as your username or password. Answer the question above, or tap "
        "Cancel."
    ),
    "auth.accountCreated": "Account created",
    "auth.loggedIn": "Logged in",
    "auth.loginSuccess": "✅ {verb} as <b>{username}</b>. You stay logged in until /lock.",
    "auth.setIncomeNext": (
        "Nothing can be recorded until your monthly income is set — the daily figure and your "
        "savings are worked out from it. Set it now."
    ),
    "auth.loggedOut": "🔒 Your login has run out. Log in again to keep recording.",
    "auth.tryAgain": "Tap /login to try again.",
    "auth.serverUnreachable": "❌ Couldn't reach the server. Is the backend running?",
    "auth.locked": "🔒 Logged out. Log in again whenever you like.",
    "auth.lockedToast": "Logged out",

    # ── The backend's own authentication sentences ──────────────────────────
    "auth.err.invalidCredentials": "❌ Wrong username or password.",
    "auth.err.passwordTooShort": "❌ The password must be at least 6 characters.",
    "auth.err.usernameRequired": "❌ A username is required.",
    "auth.err.accountExists": "❌ An account already exists — log in with it instead.",

    # ── The password message ────────────────────────────────────────────────
    "auth.passwordNotDeleted": (
        "⚠️ I couldn't delete the message you typed your password into, so it is still sitting "
        "in this chat's history. Delete it yourself — long-press it → Delete."
    ),

    # ── Rescuing the bot's own config after a factory reset ─────────────────
    "auth.configRestored": (
        "🔧 Put this bot's own settings back (webhook and web-view URL). The reset had wiped "
        "them along with everything else, and without the webhook URL the bot would not have "
        "come back after its next restart."
    ),
    "auth.configRestoreFailed": (
        "⚠️ I couldn't write this bot's webhook URL back into Settings. The reset wiped it, so "
        "the bot will not start again once it is restarted. Set it in the web app → Developer → "
        "Webhook URL:\n<code>{url}</code>"
    ),
    "auth.webhookUnknown": (
        "⚠️ Settings has no webhook URL and I couldn't read the one Telegram is using, so I have "
        "nothing to put back. Set it in the web app → Developer → Webhook URL before restarting "
        "the bot, or it will not come back."
    ),

}

UZ: dict[str, str] = {
    # ── The welcome screen ──────────────────────────────────────────────────
    "auth.loginButton": "🔑 Kirish",
    "auth.setupButton": "🆕 Botni sozlash",
    "auth.welcome": (
        "👋 <b>Tracker</b> — bitta odamning puli, bitta chatda.\n\n"
        "Bitta xabar bilan yozing, tugma bilan toʻlang, hamyonlaringizni tekshiring. Bu bot faqat "
        "bitta hisobga xizmat qiladi — davom etish uchun oʻsha hisob bilan kiring. Chiqmaguningizcha "
        "tizimda qolasiz."
    ),
    "auth.welcomeFirstRun": (
        "👋 <b>Tracker</b> — bitta odamning puli, bitta chatda.\n\n"
        "Hali hisob yaratilmagan, shuning uchun bu yerga yoziladigan keyingi login va parol uni "
        "<b>yaratadi</b> va shu chat butunlay uning egasi boʻlib qoladi. Agar bu botni siz "
        "sozlamagan boʻlsangiz, yopib qoʻying va sozlagan odamga ayting.\n\n"
        "Parol kamida 6 ta belgidan iborat boʻlishi kerak."
    ),
    "auth.pleaseLoginFirst": "🔒 Avval tizimga kiring.",

    # ── The typed flow ──────────────────────────────────────────────────────
    "auth.enterUsername": "👤 <b>Loginingizni</b> kiriting:",
    "auth.enterPassword": "🔑 Endi <b>parolingizni</b> kiriting:",
    "auth.chooseUsername": "👤 Yangi hisob uchun <b>login</b> tanlang:",
    "auth.choosePassword": "🔑 Endi <b>parol</b> tanlang — kamida 6 ta belgi:",
    "auth.usernameNeeded": "👤 Loginingizni oddiy matn qilib yuboring.",
    "auth.passwordNeeded": "🔑 Parolingizni oddiy matn qilib yuboring.",
    "auth.commandDuringLogin": (
        "🤔 <code>/{cmd}</code> — bunday buyruq yoʻq, siz esa hozir tizimga kirayapsiz. Shuning "
        "uchun uni login yoki parol sifatida qabul qilmadim. Yuqoridagi savolga javob yozing "
        "yoki Bekor qilishni bosing."
    ),
    "auth.accountCreated": "hisobingiz yaratildi",
    "auth.loggedIn": "tizimga kirdingiz",
    "auth.loginSuccess": "✅ <b>{username}</b> — {verb}. /lock buyrugʻigacha tizimda qolasiz.",
    "auth.setIncomeNext": (
        "Oylik daromadingiz kiritilmaguncha hech narsa yozib boʻlmaydi — kunlik summa va "
        "jamgʻarmalaringiz shundan hisoblanadi. Uni hozir kiriting."
    ),
    "auth.loggedOut": "🔒 Kirish muddati tugadi. Yozishda davom etish uchun qaytadan kiring.",
    "auth.tryAgain": "Qayta urinish uchun /login bosing.",
    "auth.serverUnreachable": "❌ Serverga ulanib boʻlmadi. Backend ishlayaptimi?",
    "auth.locked": "🔒 Tizimdan chiqdingiz. Istalgan vaqtda qaytadan kiring.",
    "auth.lockedToast": "Chiqildi",

    # ── The backend's own authentication sentences ──────────────────────────
    "auth.err.invalidCredentials": "❌ Login yoki parol notoʻgʻri.",
    "auth.err.passwordTooShort": "❌ Parol kamida 6 ta belgidan iborat boʻlishi kerak.",
    "auth.err.usernameRequired": "❌ Login kiritilishi shart.",
    "auth.err.accountExists": "❌ Hisob allaqachon mavjud — oʻsha bilan kiring.",

    # ── The password message ────────────────────────────────────────────────
    "auth.passwordNotDeleted": (
        "⚠️ Parolingizni yozgan xabaringizni oʻchira olmadim, u hamon shu chat tarixida turibdi. "
        "Uni oʻzingiz oʻchiring — xabarni bosib turing → Oʻchirish."
    ),

    # ── Rescuing the bot's own config after a factory reset ─────────────────
    "auth.configRestored": (
        "🔧 Botning oʻz sozlamalarini (webhook va web-view manzillari) qaytarib qoʻydim. Toʻliq "
        "tozalash ularni ham oʻchirib yuborgan edi, webhook manzilisiz esa bot keyingi qayta "
        "ishga tushishida umuman koʻtarilmasdi."
    ),
    "auth.configRestoreFailed": (
        "⚠️ Botning webhook manzilini Sozlamalarga qaytarib yoza olmadim. Toʻliq tozalash uni "
        "oʻchirib yuborgan, demak bot qayta ishga tushirilsa koʻtarilmaydi. Uni veb-ilovada "
        "sozlang: Developer → Webhook URL:\n<code>{url}</code>"
    ),
    "auth.webhookUnknown": (
        "⚠️ Sozlamalarda webhook manzili yoʻq, Telegram ishlatayotganini ham oʻqiy olmadim — "
        "qaytaradigan narsam qolmadi. Botni qayta ishga tushirishdan oldin uni veb-ilovada "
        "sozlang: Developer → Webhook URL, aks holda bot koʻtarilmaydi."
    ),

}
