"""Transactions: the add flow, move money, the recent list, one transaction, editing.

`tx.*` and `alloc.*`

`alloc.*` lives here rather than in `menu.py` because the allocation-preview block is
rendered inline by the add flow — after the owner picks a kind the bot tells them, on the
confirmation screen itself, what the entry does to that bucket's target.

Two rules this module exists to enforce, both learned the hard way:

* **A translated word is never spliced into a translated sentence.** English wants "Add
  {type}" with a lowercase noun; Uzbek wants "{type} qoʻshish" with the noun sentence-initial
  and capitalised. Applying `.lower()` at the call site guarantees one of the two dictionaries
  is wrong, so each direction gets its own whole sentence (`tx.addHeader.income` /
  `tx.addHeader.expense`, `tx.savedOk.income` / `tx.savedOk.expense`).
* **Backend prose is never printed.** `AllocationPreviewResponse.message` is composed as
  English in `OverviewService`, with an ungrouped raw BigDecimal in it. Every statement it
  makes is reconstructed here from the numbers in the same payload, so the most-walked screen
  in the bot is Uzbek all the way down.
"""

EN: dict[str, str] = {
    # ── Section menu ──────────────────────────────────────────────────────────
    "tx.menuTitle": "💸 <b>Transactions</b>\nChoose an action:",
    "tx.recentBtn": "📋 Recent",
    "tx.moveBtn": "🔄 Move money",

    # ── Add: direction ────────────────────────────────────────────────────────
    "tx.addTitle": "➕ <b>Add transaction</b>",
    "tx.incomeOrExpense": "Money in or money out?",
    "tx.income": "📈 Income",
    "tx.expense": "📉 Expense",

    # ── Add: amount ───────────────────────────────────────────────────────────
    "tx.addHeader.income": "➕ <b>Add income</b>\nSend the <b>amount</b> in {currency}:",
    "tx.addHeader.expense": "➕ <b>Add expense</b>\nSend the <b>amount</b> in {currency}:",
    "tx.positiveNumber": "Please send a positive number, e.g. 50000.",

    # ── Add: kind of expense ──────────────────────────────────────────────────
    "tx.whatKind": "What kind of expense is this?",
    "tx.kindRegular": "🧾 Regular expense",
    "tx.kindDonation": "🎁 Donation",
    "tx.kindEmergency": "🛟 Emergency fund",
    "tx.kindInvestment": "📈 Investment",
    "tx.kindStocks": "📊 Stocks",

    # ── Add: donation recipient ───────────────────────────────────────────────
    # The backend creates a Donation record from this sub-type and names it after the
    # counterparty; with nothing sent it falls back to the description, or to the literal
    # word "Donation". Asking properly is the difference between a donations list and a
    # column of rows all called "Donation".
    "tx.donationWho": "🎁 <b>Who received it?</b>\nSend a name, or skip and the entry keeps "
                      "its description.",
    "tx.fieldRecipient": "Recipient",

    # ── Add: investment target ────────────────────────────────────────────────
    # An INVESTMENT expense with no investmentId makes the backend create a BRAND NEW holding
    # every single time, so a monthly top-up of the same gold savings grows a new junk row
    # each month. This step is what turns those into one holding.
    "tx.investmentWhich": "📈 <b>Which holding is this going into?</b>",
    "tx.investmentNew": "➕ A new holding",
    "tx.investmentFirst": "📈 <b>Your first holding</b>\nWhat should it be called?",
    "tx.investmentNameAsk": "📈 <b>New holding</b>\nWhat should it be called?",
    "tx.investmentTypeAsk": "What kind of holding is it?",
    "tx.investmentLoadError": "❌ Couldn't load your holdings. Without the list this would "
                              "create a duplicate one, so pick again in a moment.",
    "tx.invType.realEstate": "🏠 Real estate",
    "tx.invType.bonds": "📜 Bonds",
    "tx.invType.mutualFund": "🏦 Mutual fund",
    "tx.invType.gold": "🪙 Gold",
    "tx.invType.other": "📦 Other",
    "tx.fieldHolding": "Holding",
    "tx.newHolding": "{name} (new)",

    # ── Add: category ─────────────────────────────────────────────────────────
    "tx.pickCategory": "Pick a <b>category</b>:",
    "tx.pickSubCategory": "Pick a sub-category:",
    "tx.skipCategory": "⏭ No category",
    "tx.useCategory": "▫️ Use “{name}”",
    "tx.catLoadError": "❌ Couldn't load your categories.",
    "tx.catNoneForKind": "No category is set up for this kind of expense yet.",
    "tx.catShowAll": "📂 Show every category",

    # ── Add: payment source ───────────────────────────────────────────────────
    "tx.paymentSource": "Which wallet did it come from?",
    "tx.incomeSource": "Which wallet did it go into?",
    "tx.sourceLoadError": "❌ Couldn't load your cards.\nRecording this as cash would put the "
                          "money in the wrong wallet, so nothing is offered until the list loads.",
    "tx.cardShortNote": "⚠️ Marked cards hold less than {amount} — a card payment over its "
                        "balance is refused.",

    # ── Add: date ─────────────────────────────────────────────────────────────
    "tx.dateHeader": "Which date? Tap Today, or send <code>YYYY-MM-DD</code>:",
    "tx.sendDateFormat": "Send the date as YYYY-MM-DD, e.g. 2026-05-25.",
    "tx.monthClosed": "🔒 <b>{month}</b> is closed and locked — its transactions can no longer "
                      "be changed. Pick a date from an open month.",
    "tx.lockedThrough": "🔒 Closed and locked through <b>{month}</b>.",

    # ── Add: description ──────────────────────────────────────────────────────
    "tx.addDescription": "Add a <b>description</b>, or skip:",

    # ── Add: confirm ──────────────────────────────────────────────────────────
    "tx.confirmPlease": "Please confirm:",
    "tx.fieldType": "Type",
    "tx.fieldAmount": "Amount",
    "tx.fieldCategory": "Category",
    "tx.fieldKind": "Kind",
    "tx.fieldSource": "Wallet",
    "tx.fieldDate": "Date",
    "tx.fieldDescription": "Description",
    "tx.fieldNote": "Note",
    "tx.saveFailedHint": "Nothing was saved. Change what's wrong and confirm again — your "
                         "answers are still here.",
    "tx.changeSource": "💳 Change wallet",
    "tx.changeAmount": "💰 Change amount",
    "tx.savedOk.income": "✅ Income of <b>{amount}</b> saved.",
    "tx.savedOk.expense": "✅ Expense of <b>{amount}</b> saved.",
    "tx.savedProgressHeader": "📊 <b>{label}</b>: {paid} / {target}",

    # ── Move money ────────────────────────────────────────────────────────────
    # POST /transactions/transfer writes a TRANSFER_OUT / TRANSFER_IN pair, so neither leg
    # counts as income or spending. Recording a card top-up as an income + an expense — the
    # only thing the bot could do before — inflated both figures in the month being closed.
    "tx.moveTitle": "🔄 <b>Move money</b>\nWhich wallet is it leaving?",
    "tx.moveTo": "🔄 <b>Move money</b>\nWhich wallet is it going into?",
    "tx.moveAmount": "How much is moving? Send the amount in {currency}:",
    "tx.moveDate": "Which date did it move? Tap Today, or send <code>YYYY-MM-DD</code>:",
    "tx.moveConfirm": "Please confirm the move:",
    "tx.fieldFrom": "From",
    "tx.fieldTo": "To",
    "tx.moveSaved": "✅ <b>{amount}</b> moved from {source} to {target}.\n"
                    "<i>Neither side counts as income or spending.</i>",
    "tx.moveNote": "<i>This is not income and not spending — only the two wallet balances "
                   "change.</i>",
    "tx.moveNoCards": "A move needs at least one card. Add one under Wallets first.",
    "tx.moveCardsError": "❌ Couldn't load your wallets.",

    # ── Recent list ───────────────────────────────────────────────────────────
    "tx.recentTitle": "📋 <b>Recent</b> · {currency}",
    "tx.loadError": "❌ Couldn't load transactions.",
    "tx.noTransactionsYet": "No transactions yet.",

    # ── One transaction ───────────────────────────────────────────────────────
    "tx.txHeader": "🧾 <b>Transaction #{id}</b>",
    "tx.viewLoadError": "❌ Couldn't load it.",
    "tx.selected": "selected",
    "tx.lockedRow": "🔒 <b>{month}</b> is closed — this row can no longer be edited or deleted.",
    "tx.transferRow": "🔄 One leg of a money move. Delete it and both legs go; to change it, "
                      "delete and record the move again.",
    "tx.deleteConfirm": "Delete transaction #{id}? This can't be undone.",
    "tx.deleted": "🗑 Deleted.",

    # ── Edit ──────────────────────────────────────────────────────────────────
    "tx.editWhat": "✏️ <b>What needs changing?</b>",
    "tx.editAmount": "💰 Amount",
    "tx.editDate": "📅 Date",
    "tx.editCategory": "🗂 Category",
    "tx.editDescription": "📝 Description",
    "tx.editSource": "💳 Wallet",
    "tx.editAmountAsk": "Send the new <b>amount</b> in {currency}:",
    "tx.editDateAsk": "Send the new date as <code>YYYY-MM-DD</code>, or tap Today:",
    "tx.editDescAsk": "Send the new <b>description</b>:",
    "tx.editDescClear": "🚫 No description",
    "tx.editSourceAsk": "Which wallet should it come from?",
    "tx.editSaved": "✅ Updated.",

    # ── A screen that outlived its flow ───────────────────────────────────────
    "tx.flowExpired": "That screen is out of date.",
    "tx.flowExpiredBody": "⌛️ That form is gone — the bot restarted while it was open, so "
                          "nothing was saved. Start again:",

    # ── Allocation preview ────────────────────────────────────────────────────
    "alloc.countsToward": "📊 Counts toward <b>{label}</b>",
    "alloc.notRequired": "<i>Recorded, but nothing is expected there at your current level.</i>",
    "alloc.target": "Target",
    "alloc.paidSoFar": "Set aside so far",
    "alloc.afterThis": "After this",
    "alloc.stillToGo": "{amount} still to go.",
    "alloc.fullyCovered": "Fully covered. 🎉",
    "alloc.completes": "This covers the rest of it for this month. 🎉",
    "alloc.alreadyCovered": "It was already covered this month.",
    "alloc.stocksNoBucket": "<i>📊 Recorded as stocks. Stocks are not an allocation bucket, "
                            "so there is no monthly target for them.</i>",
    "alloc.bucket.donation": "Donation",
    "alloc.bucket.emergency": "Emergency fund",
    "alloc.bucket.investments": "Investments",
    "alloc.bucket.savings": "Savings goals",
    "alloc.bucket.stocks": "Stocks",
}

UZ: dict[str, str] = {
    "tx.menuTitle": "💸 <b>Tranzaksiyalar</b>\nHarakatni tanlang:",
    "tx.recentBtn": "📋 Oxirgilar",
    "tx.moveBtn": "🔄 Pul koʻchirish",

    "tx.addTitle": "➕ <b>Tranzaksiya qoʻshish</b>",
    "tx.incomeOrExpense": "Pul kirdimi yoki chiqdimi?",
    "tx.income": "📈 Daromad",
    "tx.expense": "📉 Xarajat",

    "tx.addHeader.income": "➕ <b>Daromad qoʻshish</b>\n<b>Summani</b> {currency} da yuboring:",
    "tx.addHeader.expense": "➕ <b>Xarajat qoʻshish</b>\n<b>Summani</b> {currency} da yuboring:",
    "tx.positiveNumber": "Iltimos, musbat son yuboring, masalan 50000.",

    "tx.whatKind": "Bu qanday xarajat?",
    "tx.kindRegular": "🧾 Oddiy xarajat",
    "tx.kindDonation": "🎁 Xayriya",
    "tx.kindEmergency": "🛟 Favqulodda jamgʻarma",
    "tx.kindInvestment": "📈 Investitsiya",
    "tx.kindStocks": "📊 Aksiyalar",

    "tx.donationWho": "🎁 <b>Kimga berildi?</b>\nIsmini yuboring yoki oʻtkazib yuboring — u holda "
                      "yozuv tavsifi bilan qoladi.",
    "tx.fieldRecipient": "Kimga",

    "tx.investmentWhich": "📈 <b>Bu pul qaysi investitsiyaga tushmoqda?</b>",
    "tx.investmentNew": "➕ Yangi investitsiya",
    "tx.investmentFirst": "📈 <b>Birinchi investitsiyangiz</b>\nUni qanday nomlaymiz?",
    "tx.investmentNameAsk": "📈 <b>Yangi investitsiya</b>\nUni qanday nomlaymiz?",
    "tx.investmentTypeAsk": "Bu qanday investitsiya?",
    "tx.investmentLoadError": "❌ Investitsiyalar roʻyxatini yuklab boʻlmadi. Roʻyxatsiz davom "
                              "etsak, takroriy yozuv paydo boʻladi — biroz kutib, qaytadan tanlang.",
    "tx.invType.realEstate": "🏠 Koʻchmas mulk",
    "tx.invType.bonds": "📜 Obligatsiyalar",
    "tx.invType.mutualFund": "🏦 Investitsiya fondi",
    "tx.invType.gold": "🪙 Oltin",
    "tx.invType.other": "📦 Boshqa",
    "tx.fieldHolding": "Investitsiya",
    "tx.newHolding": "{name} (yangi)",

    "tx.pickCategory": "<b>Kategoriyani</b> tanlang:",
    "tx.pickSubCategory": "Ichki kategoriyani tanlang:",
    "tx.skipCategory": "⏭ Kategoriyasiz",
    "tx.useCategory": "▫️ “{name}” ni tanlash",
    "tx.catLoadError": "❌ Kategoriyalarni yuklab boʻlmadi.",
    "tx.catNoneForKind": "Bu turdagi xarajat uchun hali kategoriya yoʻq.",
    "tx.catShowAll": "📂 Barcha kategoriyalar",

    "tx.paymentSource": "Pul qaysi hamyondan chiqdi?",
    "tx.incomeSource": "Pul qaysi hamyonga tushdi?",
    "tx.sourceLoadError": "❌ Kartalar roʻyxatini yuklab boʻlmadi.\nBuni naqd deb yozib qoʻysak, "
                          "pul notoʻgʻri hamyonga tushadi — shuning uchun roʻyxat yuklanmaguncha "
                          "hech narsa taklif qilinmaydi.",
    "tx.cardShortNote": "⚠️ Belgilangan kartalarda {amount} dan kam pul bor — balansdan ortiq "
                        "karta toʻlovi qabul qilinmaydi.",

    "tx.dateHeader": "Qaysi sana? Bugun tugmasini bosing yoki <code>YYYY-MM-DD</code> yuboring:",
    "tx.sendDateFormat": "Sanani YYYY-MM-DD shaklida yuboring, masalan 2026-05-25.",
    "tx.monthClosed": "🔒 <b>{month}</b> yopilgan va qulflangan — undagi tranzaksiyalarni "
                      "oʻzgartirib boʻlmaydi. Ochiq oydan sana tanlang.",
    "tx.lockedThrough": "🔒 <b>{month}</b> gacha yopilgan va qulflangan.",

    "tx.addDescription": "<b>Tavsif</b> qoʻshing yoki oʻtkazib yuboring:",

    "tx.confirmPlease": "Iltimos, tasdiqlang:",
    "tx.fieldType": "Turi",
    "tx.fieldAmount": "Summa",
    "tx.fieldCategory": "Kategoriya",
    "tx.fieldKind": "Xarajat turi",
    "tx.fieldSource": "Hamyon",
    "tx.fieldDate": "Sana",
    "tx.fieldDescription": "Tavsif",
    "tx.fieldNote": "Izoh",
    "tx.saveFailedHint": "Hech narsa saqlanmadi. Xatoni tuzatib, yana tasdiqlang — javoblaringiz "
                         "joyida turibdi.",
    "tx.changeSource": "💳 Hamyonni oʻzgartirish",
    "tx.changeAmount": "💰 Summani oʻzgartirish",
    "tx.savedOk.income": "✅ <b>{amount}</b> daromad saqlandi.",
    "tx.savedOk.expense": "✅ <b>{amount}</b> xarajat saqlandi.",
    "tx.savedProgressHeader": "📊 <b>{label}</b>: {paid} / {target}",

    "tx.moveTitle": "🔄 <b>Pul koʻchirish</b>\nPul qaysi hamyondan chiqadi?",
    "tx.moveTo": "🔄 <b>Pul koʻchirish</b>\nPul qaysi hamyonga tushadi?",
    "tx.moveAmount": "Qancha pul koʻchmoqda? Summani {currency} da yuboring:",
    "tx.moveDate": "Qaysi sanada koʻchdi? Bugun tugmasini bosing yoki <code>YYYY-MM-DD</code> "
                   "yuboring:",
    "tx.moveConfirm": "Koʻchirishni tasdiqlang:",
    "tx.fieldFrom": "Qayerdan",
    "tx.fieldTo": "Qayerga",
    "tx.moveSaved": "✅ <b>{amount}</b> {source} dan {target} ga koʻchirildi.\n"
                    "<i>Ikkala tomon ham daromad yoki xarajat hisoblanmaydi.</i>",
    "tx.moveNote": "<i>Bu daromad ham, xarajat ham emas — faqat ikkita hamyon balansi "
                   "oʻzgaradi.</i>",
    "tx.moveNoCards": "Koʻchirish uchun kamida bitta karta kerak. Avval Hamyonlar boʻlimidan "
                      "karta qoʻshing.",
    "tx.moveCardsError": "❌ Hamyonlarni yuklab boʻlmadi.",

    "tx.recentTitle": "📋 <b>Oxirgilar</b> · {currency}",
    "tx.loadError": "❌ Tranzaksiyalarni yuklab boʻlmadi.",
    "tx.noTransactionsYet": "Hozircha tranzaksiyalar yoʻq.",

    "tx.txHeader": "🧾 <b>Tranzaksiya #{id}</b>",
    "tx.viewLoadError": "❌ Uni yuklab boʻlmadi.",
    "tx.selected": "tanlangan",
    "tx.lockedRow": "🔒 <b>{month}</b> yopilgan — bu yozuvni endi tahrirlab ham, oʻchirib ham "
                    "boʻlmaydi.",
    "tx.transferRow": "🔄 Bu pul koʻchirishning bir tomoni. Oʻchirsangiz, ikkala tomoni ham "
                      "oʻchadi; oʻzgartirish uchun oʻchirib, qaytadan koʻchiring.",
    "tx.deleteConfirm": "#{id}-tranzaksiya oʻchirilsinmi? Buni bekor qilib boʻlmaydi.",
    "tx.deleted": "🗑 Oʻchirildi.",

    "tx.editWhat": "✏️ <b>Nimani oʻzgartiramiz?</b>",
    "tx.editAmount": "💰 Summa",
    "tx.editDate": "📅 Sana",
    "tx.editCategory": "🗂 Kategoriya",
    "tx.editDescription": "📝 Tavsif",
    "tx.editSource": "💳 Hamyon",
    "tx.editAmountAsk": "Yangi <b>summani</b> {currency} da yuboring:",
    "tx.editDateAsk": "Yangi sanani <code>YYYY-MM-DD</code> shaklida yuboring yoki Bugun "
                      "tugmasini bosing:",
    "tx.editDescAsk": "Yangi <b>tavsifni</b> yuboring:",
    "tx.editDescClear": "🚫 Tavsifsiz",
    "tx.editSourceAsk": "Qaysi hamyondan chiqsin?",
    "tx.editSaved": "✅ Yangilandi.",

    "tx.flowExpired": "Bu ekran eskirgan.",
    "tx.flowExpiredBody": "⌛️ Bu forma yoʻqoldi — u ochiq turganda bot qayta ishga tushgan, "
                          "shuning uchun hech narsa saqlanmadi. Qaytadan boshlang:",

    "alloc.countsToward": "📊 <b>{label}</b>ga hisoblanadi",
    "alloc.notRequired": "<i>Yozib qoʻyiladi, lekin hozirgi darajangizda undan talab "
                         "qilinmaydi.</i>",
    "alloc.target": "Maqsad",
    "alloc.paidSoFar": "Hozirgacha ajratilgan",
    "alloc.afterThis": "Shundan keyin",
    "alloc.stillToGo": "Yana {amount} qoldi.",
    "alloc.fullyCovered": "Toʻliq qoplandi. 🎉",
    "alloc.completes": "Bu shu oyning qolgan qismini toʻliq qoplaydi. 🎉",
    "alloc.alreadyCovered": "U bu oyda allaqachon qoplangan edi.",
    "alloc.stocksNoBucket": "<i>📊 Aksiya sifatida yozildi. Aksiyalar taqsimot bandi emas, "
                            "shuning uchun ular uchun oylik maqsad yoʻq.</i>",
    "alloc.bucket.donation": "Xayriya",
    "alloc.bucket.emergency": "Favqulodda jamgʻarma",
    "alloc.bucket.investments": "Investitsiyalar",
    "alloc.bucket.savings": "Jamgʻarma maqsadlari",
    "alloc.bucket.stocks": "Aksiyalar",
}
