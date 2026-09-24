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
    # Full month names — "September 2026", "September so far" (the web's formatMonth).
    "common.monthFull.1": "January", "common.monthFull.2": "February", "common.monthFull.3": "March",
    "common.monthFull.4": "April", "common.monthFull.5": "May", "common.monthFull.6": "June",
    "common.monthFull.7": "July", "common.monthFull.8": "August", "common.monthFull.9": "September",
    "common.monthFull.10": "October", "common.monthFull.11": "November", "common.monthFull.12": "December",
    "common.monthYear": "{month} {year}",
    # Buttons several screens share
    "common.edit": "✏️ Edit",
    "common.delete": "🗑 Delete",
    "common.prev": "‹ Newer",
    "common.next": "Older ›",
    "common.keep": "✔️ Keep “{value}”",
    "common.tapButton": "Tap a button below.",

    # The backend refuses every money write until the monthly income is set.
    "guard.incomeTitle": "⚠️ <b>Set your monthly income first</b>",
    "guard.incomeBody": "Nothing can be recorded until it is set — it is what the daily figure "
                        "and your savings are worked out from.",

    "lang.changed": "Language set to English.",

    # Settings
    "settings.title": "⚙️ <b>Settings</b>",
    "settings.income": "Monthly income: <b>{amount}</b>",
    "settings.notSet": "not set",
    "settings.countingFrom": "Counting from: <b>{month}</b> <i>(once set, this can’t be changed)</i>",
    "settings.countingNotSet": "Counting from: <i>not set yet</i>",
    "settings.categoriesBtn": "🏷 Categories",
    "settings.dangerBtn": "⚠️ Danger Zone",
    "settings.langBtn": "🌐 Oʻzbekcha",
    "settings.incomeBtn": "💰 Monthly income",
    "settings.helpBtn": "❓ Help",
    "settings.lockBtn": "🔒 Log out",
    "settings.incomeTitle": "💰 <b>Monthly income</b>",
    "settings.incomeAsk": "Send your monthly stable income, e.g. <code>8000000</code> or <code>8m</code>.",
    "settings.incomeSaved": "✅ Monthly income saved: {amount}",

    # Categories (Settings → Categories), the web's words.
    "settings.cat.title": "🏷 <b>Categories</b>",
    "settings.cat.intro": "Add, rename and group your categories.",
    "settings.cat.count": "{expense} expense · {income} income",
    "settings.cat.expenseBtn": "➖ Expense",
    "settings.cat.incomeBtn": "➕ Income",
    "settings.cat.expenseTitle": "🏷 <b>Expense categories</b>",
    "settings.cat.incomeTitle": "🏷 <b>Income categories</b>",
    "settings.cat.none": "No categories yet",
    "settings.cat.row": "• {name}",
    "settings.cat.rowSubs": "• {name} · {count} sub",
    "settings.cat.addBtn": "➕ Add category",
    "settings.cat.addSubBtn": "➕ Add sub-category",
    "settings.cat.renameBtn": "✏️ Rename",
    "settings.cat.subOf": "Sub-category of <b>{name}</b>",
    "settings.cat.typeExpense": "Expense",
    "settings.cat.typeIncome": "Income",
    "settings.cat.nameEn": "Name (English): <b>{name}</b>",
    "settings.cat.nameUz": "Name (Uzbek): <b>{name}</b>",
    "settings.cat.nameUzNone": "Name (Uzbek): <i>none — the English name is shown</i>",
    "settings.cat.subsTitle": "<b>Sub-categories</b>",
    "settings.cat.subsNone": "No sub-categories.",
    "settings.cat.pickType": "🏷 <b>Add category</b>\n\nIs it for income or expenses?",
    "settings.cat.askName": "🏷 <b>{title}</b>\n\nSend the name in English, e.g. <i>Food &amp; Dining</i>.",
    "settings.cat.askNameUz": ("🏷 <b>{title}</b>\n\nNow the Uzbek name — shown when the app is in "
                               "Uzbek. Skip it to use the English name."),
    "settings.cat.addTitle": "Add category",
    "settings.cat.addSubTitle": "Add sub-category to “{name}”",
    "settings.cat.editTitle": "Edit “{name}”",
    "settings.cat.clearUz": "🧹 No Uzbek name",
    "settings.cat.tooLong": "That name is too long — keep it under {limit} characters.",
    "settings.cat.saved": "✅ Category saved",
    "settings.cat.deleteTitle": "🗑 <b>Delete category?</b>\n\n<b>{name}</b>",
    "settings.cat.deleteMessage": "Existing transactions will lose their category link, and any sub-categories become top-level.",
    "settings.cat.deleted": "✅ Category deleted",
    "settings.cat.gone": "That category is gone.",

    # Danger Zone — the factory reset, behind the account password as on the web.
    "settings.danger.title": "⚠️ <b>Danger Zone</b>",
    "settings.danger.body": ("<b>Clear everything.</b> Permanently deletes all transactions, cards, "
                             "finance records, categories, settings, and your account — then starts "
                             "the app over from zero, exactly like a fresh install. This cannot be undone."),
    "settings.danger.clearBtn": "🧨 Clear everything",
    "settings.danger.confirmTitle": "⚠️ <b>Clear everything?</b>",
    "settings.danger.confirmBody": ("This permanently deletes ALL your data — transactions, cards, finance "
                                    "records, categories, settings, and your account itself — and starts the "
                                    "app over from zero. This cannot be undone. You will be asked for your "
                                    "password next."),
    "settings.danger.continueBtn": "Continue",
    "settings.danger.passwordTitle": "🔑 <b>Confirm with your password</b>",
    "settings.danger.passwordAsk": ("Enter your account password to permanently clear everything and start "
                                    "from zero. I delete your message as soon as I read it."),
    "settings.danger.notDeleted": "⚠️ I couldn’t delete your password message — delete it yourself.",
    "settings.danger.clearing": "⏳ Clearing…",
    "settings.danger.wrong": "❌ Incorrect password. Try again, or cancel.",
    "settings.danger.done": "✅ <b>Reset complete</b>\n\nEverything was cleared. Starting fresh — please sign up.",
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
    "common.monthFull.1": "Yanvar", "common.monthFull.2": "Fevral", "common.monthFull.3": "Mart",
    "common.monthFull.4": "Aprel", "common.monthFull.5": "May", "common.monthFull.6": "Iyun",
    "common.monthFull.7": "Iyul", "common.monthFull.8": "Avgust", "common.monthFull.9": "Sentabr",
    "common.monthFull.10": "Oktabr", "common.monthFull.11": "Noyabr", "common.monthFull.12": "Dekabr",
    "common.monthYear": "{month} {year}",
    "common.edit": "✏️ Tahrirlash",
    "common.delete": "🗑 Oʻchirish",
    "common.prev": "‹ Yangiroq",
    "common.next": "Eskiroq ›",
    "common.keep": "✔️ “{value}” qolsin",
    "common.tapButton": "Pastdagi tugmani bosing.",

    "guard.incomeTitle": "⚠️ <b>Avval oylik daromadingizni kiriting</b>",
    "guard.incomeBody": "U kiritilmaguncha hech narsa yozib boʻlmaydi — kunlik summa va "
                        "jamgʻarmalaringiz shundan hisoblanadi.",

    "lang.changed": "Til oʻzbekchaga oʻzgartirildi.",

    "settings.title": "⚙️ <b>Sozlamalar</b>",
    "settings.income": "Oylik daromad: <b>{amount}</b>",
    "settings.notSet": "kiritilmagan",
    "settings.countingFrom": "Hisob boshlangan oy: <b>{month}</b> <i>(bir marta belgilangach, buni oʻzgartirib boʻlmaydi)</i>",
    "settings.countingNotSet": "Hisob boshlangan oy: <i>hali belgilanmagan</i>",
    "settings.categoriesBtn": "🏷 Kategoriyalar",
    "settings.dangerBtn": "⚠️ Xavfli hudud",
    "settings.langBtn": "🌐 English",
    "settings.incomeBtn": "💰 Oylik daromad",
    "settings.helpBtn": "❓ Yordam",
    "settings.lockBtn": "🔒 Chiqish",
    "settings.incomeTitle": "💰 <b>Oylik daromad</b>",
    "settings.incomeAsk": "Oylik barqaror daromadingizni yuboring, masalan <code>8000000</code> yoki <code>8m</code>.",
    "settings.incomeSaved": "✅ Oylik daromad saqlandi: {amount}",

    "settings.cat.title": "🏷 <b>Kategoriyalar</b>",
    "settings.cat.intro": "Kategoriyalarni qoʻshish, nomini oʻzgartirish va guruhlash.",
    "settings.cat.count": "{expense} ta xarajat · {income} ta daromad",
    "settings.cat.expenseBtn": "➖ Xarajat",
    "settings.cat.incomeBtn": "➕ Daromad",
    "settings.cat.expenseTitle": "🏷 <b>Xarajat kategoriyalari</b>",
    "settings.cat.incomeTitle": "🏷 <b>Daromad kategoriyalari</b>",
    "settings.cat.none": "Hozircha kategoriya yoʻq",
    "settings.cat.row": "• {name}",
    "settings.cat.rowSubs": "• {name} · {count} ta ichki",
    "settings.cat.addBtn": "➕ Kategoriya qoʻshish",
    "settings.cat.addSubBtn": "➕ Ichki kategoriya qoʻshish",
    "settings.cat.renameBtn": "✏️ Nomini oʻzgartirish",
    "settings.cat.subOf": "Ichki kategoriyasi: <b>{name}</b>",
    "settings.cat.typeExpense": "Xarajat",
    "settings.cat.typeIncome": "Daromad",
    "settings.cat.nameEn": "Nomi (inglizcha): <b>{name}</b>",
    "settings.cat.nameUz": "Nomi (oʻzbekcha): <b>{name}</b>",
    "settings.cat.nameUzNone": "Nomi (oʻzbekcha): <i>yoʻq — inglizcha nomi koʻrsatiladi</i>",
    "settings.cat.subsTitle": "<b>Ichki kategoriyalar</b>",
    "settings.cat.subsNone": "Ichki kategoriya yoʻq.",
    "settings.cat.pickType": "🏷 <b>Kategoriya qoʻshish</b>\n\nDaromad uchunmi yoki xarajat uchunmi?",
    "settings.cat.askName": "🏷 <b>{title}</b>\n\nInglizcha nomini yuboring, masalan <i>Food &amp; Dining</i>.",
    "settings.cat.askNameUz": ("🏷 <b>{title}</b>\n\nEndi oʻzbekcha nomi — ilova oʻzbek tilida boʻlganda "
                               "koʻrsatiladi. Oʻtkazib yuborsangiz, inglizcha nomi ishlatiladi."),
    "settings.cat.addTitle": "Kategoriya qoʻshish",
    "settings.cat.addSubTitle": "“{name}” uchun ichki kategoriya qoʻshish",
    "settings.cat.editTitle": "“{name}” ni tahrirlash",
    "settings.cat.clearUz": "🧹 Oʻzbekcha nomsiz",
    "settings.cat.tooLong": "Nom juda uzun — {limit} ta belgidan qisqaroq boʻlsin.",
    "settings.cat.saved": "✅ Kategoriya saqlandi",
    "settings.cat.deleteTitle": "🗑 <b>Kategoriya oʻchirilsinmi?</b>\n\n<b>{name}</b>",
    "settings.cat.deleteMessage": "Mavjud tranzaksiyalar kategoriya bogʻlanishini yoʻqotadi, ichki kategoriyalar esa yuqori darajaga koʻtariladi.",
    "settings.cat.deleted": "✅ Kategoriya oʻchirildi",
    "settings.cat.gone": "Bu kategoriya endi yoʻq.",

    "settings.danger.title": "⚠️ <b>Xavfli hudud</b>",
    "settings.danger.body": ("<b>Hammasini tozalash.</b> Barcha tranzaksiyalar, kartalar, moliya yozuvlari, "
                             "kategoriyalar, sozlamalar va hisobingizni butunlay oʻchirib, ilovani xuddi yangi "
                             "oʻrnatilgandek noldan boshlaydi. Buni ortga qaytarib boʻlmaydi."),
    "settings.danger.clearBtn": "🧨 Hammasini tozalash",
    "settings.danger.confirmTitle": "⚠️ <b>Hammasi tozalansinmi?</b>",
    "settings.danger.confirmBody": ("Bu barcha maʼlumotlaringizni — tranzaksiyalar, kartalar, moliya yozuvlari, "
                                    "kategoriyalar, sozlamalar va hisobingizning oʻzini — butunlay oʻchirib, "
                                    "ilovani noldan boshlaydi. Buni ortga qaytarib boʻlmaydi. Keyingi qadamda "
                                    "parolingiz soʻraladi."),
    "settings.danger.continueBtn": "Davom etish",
    "settings.danger.passwordTitle": "🔑 <b>Parolingiz bilan tasdiqlang</b>",
    "settings.danger.passwordAsk": ("Hammasini butunlay tozalab, noldan boshlash uchun hisob parolingizni "
                                    "kiriting. Xabaringizni oʻqishim bilan oʻchirib tashlayman."),
    "settings.danger.notDeleted": "⚠️ Parol yozilgan xabarni oʻchira olmadim — uni oʻzingiz oʻchiring.",
    "settings.danger.clearing": "⏳ Tozalanmoqda…",
    "settings.danger.wrong": "❌ Parol notoʻgʻri. Qayta urinib koʻring yoki bekor qiling.",
    "settings.danger.done": "✅ <b>Tozalash yakunlandi</b>\n\nHammasi tozalandi. Yangidan boshlanmoqda — iltimos, roʻyxatdan oʻting.",
}
