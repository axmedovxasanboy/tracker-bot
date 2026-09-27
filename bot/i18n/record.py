"""Recording: quick add ("50000 lunch"), ➕ Add, and the draft card they share.

`record.*`
"""

EN: dict[str, str] = {
    "record.start": ("➕ <b>Add</b>\n\nWhat are you recording?\n\n"
                     "<i>Faster: just type <code>50000 lunch</code> or <code>+2000000 salary</code>.</i>"),
    "record.amountAsk": "Send the amount. A note can follow it: <code>50000 lunch</code>",
    "record.badAmount": "Send an amount, e.g. <code>50000</code> or <code>50k lunch</code>.",
    "record.categoryAsk": "🏷 Category for {amount}?",
    "record.subCategoryAsk": "🏷 <b>{name}</b> — which one?",
    "record.chosen": "✓ {name}",
    "record.noCategories": "You have no categories for this yet — add one with ➕ New category.",
    "record.newCategoryAsk": "🏷 <b>New category</b> · {type}\n\nSend its name, e.g. <i>Gifts</i>.",
    "record.newSubAsk": "🏷 <b>New sub-category of {name}</b>\n\nSend its name.",
    "record.errSubCategory": "Pick a sub-category first.",
    "record.walletAskOut": "💳 From which wallet?",
    "record.walletAskIn": "💳 Into which wallet?",
    "record.dateAsk": "📅 Which day?",
    "record.noteAsk": "📝 Send a note (what it was for), or skip.",

    "record.card.expense": "➖ <b>Expense · {amount}</b>",
    "record.card.income": "➕ <b>Income · {amount}</b>",
    "record.card.expenseTitle": "➖ <b>Expense</b>",
    "record.card.incomeTitle": "➕ <b>Income</b>",
    "record.card.noCategory": "<i>No category — pick one below</i>",
    "record.card.pickSub": "{name} › <i>which one? Pick it below</i>",
    "record.card.salaryFor": "📅 For: {month}",
    "record.notSaved": "Nothing was saved. Fix it and tap Save again.",

    "record.btn.save": "✅ Save",
    "record.btn.category": "🏷 Category",
    "record.btn.wallet": "💳 Wallet",
    "record.btn.date": "📅 Date",
    "record.btn.note": "📝 Note",
    "record.btn.toIncome": "⇄ Income",
    "record.btn.toExpense": "⇄ Expense",
    "record.btn.more": "🏷 More…",
    "record.btn.noCategory": "No category",
    "record.btn.newCategory": "➕ New category",
    "record.btn.newSub": "➕ New sub-category",
    "record.btn.salaryMonth": "⇄ For {month} instead",
    "record.btn.expense": "➖ Expense",
    "record.btn.income": "➕ Income",
    "record.btn.repeat": "🔁 Repeat last",

    "record.saved.expense": "✅ Saved: expense {amount}",
    "record.saved.income": "✅ Saved: income {amount}",
    "record.repeatNone": "Nothing to repeat yet — record something first.",
    "record.repeatCant": "Your last entry was a payment or a transfer — repeat it from the web app.",
    "record.notUnderstood": ("🤔 I didn't get that. To record, start with the amount: "
                             "<code>50000 lunch</code>, or <code>+2000000 salary</code> for income."),
}

UZ: dict[str, str] = {
    "record.start": ("➕ <b>Qoʻshish</b>\n\nNimani yozasiz?\n\n"
                     "<i>Tezroq: shunchaki <code>50000 tushlik</code> yoki <code>+2000000 maosh</code> "
                     "deb yozing.</i>"),
    "record.amountAsk": "Summani yuboring. Undan keyin izoh ham yozish mumkin: <code>50000 tushlik</code>",
    "record.badAmount": "Summani yuboring, masalan <code>50000</code> yoki <code>50k tushlik</code>.",
    "record.categoryAsk": "🏷 {amount} qaysi kategoriyaga?",
    "record.subCategoryAsk": "🏷 <b>{name}</b> — qaysi biri?",
    "record.chosen": "✓ {name}",
    "record.noCategories": "Bunga hali kategoriyalaringiz yoʻq — ➕ Yangi kategoriya bilan qoʻshing.",
    "record.newCategoryAsk": "🏷 <b>Yangi kategoriya</b> · {type}\n\nNomini yuboring, masalan <i>Sovgʻalar</i>.",
    "record.newSubAsk": "🏷 <b>{name} uchun yangi ichki kategoriya</b>\n\nNomini yuboring.",
    "record.errSubCategory": "Avval ichki kategoriyani tanlang.",
    "record.walletAskOut": "💳 Qaysi hamyondan?",
    "record.walletAskIn": "💳 Qaysi hamyonga?",
    "record.dateAsk": "📅 Qaysi kun?",
    "record.noteAsk": "📝 Izoh yuboring (nima uchun), yoki oʻtkazib yuboring.",

    "record.card.expense": "➖ <b>Xarajat · {amount}</b>",
    "record.card.income": "➕ <b>Daromad · {amount}</b>",
    "record.card.expenseTitle": "➖ <b>Xarajat</b>",
    "record.card.incomeTitle": "➕ <b>Daromad</b>",
    "record.card.noCategory": "<i>Kategoriya yoʻq — pastdan tanlang</i>",
    "record.card.pickSub": "{name} › <i>qaysi biri? Pastdan tanlang</i>",
    "record.card.salaryFor": "📅 Qaysi oy uchun: {month}",
    "record.notSaved": "Hech narsa saqlanmadi. Toʻgʻrilab, Saqlashni yana bosing.",

    "record.btn.save": "✅ Saqlash",
    "record.btn.category": "🏷 Kategoriya",
    "record.btn.wallet": "💳 Hamyon",
    "record.btn.date": "📅 Sana",
    "record.btn.note": "📝 Izoh",
    "record.btn.toIncome": "⇄ Daromad",
    "record.btn.toExpense": "⇄ Xarajat",
    "record.btn.more": "🏷 Yana…",
    "record.btn.noCategory": "Kategoriyasiz",
    "record.btn.newCategory": "➕ Yangi kategoriya",
    "record.btn.newSub": "➕ Yangi ichki kategoriya",
    "record.btn.salaryMonth": "⇄ {month} uchun qilish",
    "record.btn.expense": "➖ Xarajat",
    "record.btn.income": "➕ Daromad",
    "record.btn.repeat": "🔁 Oxirgisini takrorlash",

    "record.saved.expense": "✅ Saqlandi: xarajat {amount}",
    "record.saved.income": "✅ Saqlandi: daromad {amount}",
    "record.repeatNone": "Takrorlaydigan narsa hali yoʻq — avval biror narsa yozing.",
    "record.repeatCant": "Oxirgi yozuvingiz toʻlov yoki oʻtkazma edi — uni veb-ilovadan takrorlang.",
    "record.notUnderstood": ("🤔 Tushunmadim. Yozish uchun summadan boshlang: "
                             "<code>50000 tushlik</code>, daromad uchun esa <code>+2000000 maosh</code>."),
}
