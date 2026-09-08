"""The one-message capture path: a typed amount becomes a draft, one tap saves it.

`quickadd.*`  — owned by R-tx, alongside `bot/routers/quickadd.py`.

Deliberately self-contained rather than borrowing `tx.*`. The full add flow and this one are
being written by different hands at the same time, and a screen whose labels live in someone
else's module breaks the moment they split a key (they already split `tx.savedOk` into
`tx.savedOk.income` / `tx.savedOk.expense`). Only `common.*` is shared, because `common.py`
is frozen and cannot move under anyone.

Three rules the strings here follow, all learned from the same defect class:

* **A translated word is never spliced into a translated sentence.** English wants "Expense of
  <b>{amount}</b> saved"; Uzbek wants "<b>{amount}</b> xarajat saqlandi". So the direction gets
  a whole sentence each (`quickadd.saved.expense` / `quickadd.saved.income`) instead of a noun
  interpolated into one template and `.lower()`ed at the call site.
* **Backend prose is never printed.** `AllocationPreviewResponse.message` is composed as
  English in `OverviewService`, with a raw ungrouped BigDecimal inside it. Every statement it
  makes is rebuilt here from the numbers in the same payload.
* **A backend enum is never shown as a string.** `bucket` and `subType` arrive as
  `EMERGENCY` / `STOCK_PURCHASE`; they are mapped to `quickadd.bucket.*` / `quickadd.kind.*`.
"""

EN: dict[str, str] = {
    # ── The /add prompt, shown when the command arrives with nothing after it ──
    "quickadd.startTitle": "⚡ <b>Quick add</b>",
    "quickadd.startBody": "Send the amount and what it was for, in one message:\n"
                          "<code>50000 lunch</code> · <code>50k taxi</code> · "
                          "<code>1.5m rent</code> · <code>250 ming coffee</code>\n"
                          "A leading <code>+</code> records income, a leading <code>-</code> "
                          "an expense.",

    # ── The draft card ────────────────────────────────────────────────────────
    "quickadd.draftTitle": "⚡ <b>Quick add</b>",
    "quickadd.headExpense": "📉 <b>Expense</b> · <b>{amount}</b>",
    "quickadd.headIncome": "📈 <b>Income</b> · <b>{amount}</b>",
    "quickadd.field.date": "Date",
    "quickadd.field.wallet": "Wallet",
    "quickadd.field.category": "Category",
    "quickadd.field.description": "Description",
    "quickadd.field.kind": "Kind",
    "quickadd.suffixToday": "(today)",
    "quickadd.suffixYesterday": "(yesterday)",
    "quickadd.draftFoot": "<i>Nothing is saved until you tap Save.</i>",

    # ── Buttons. Not HTML-parsed, so nothing here is escaped or tagged ────────
    "quickadd.btnAmount": "💰 Amount",
    "quickadd.btnDate": "📅 Date",
    "quickadd.btnWallet": "💳 Wallet",
    "quickadd.btnCategory": "🗂 Category",
    "quickadd.btnDesc": "📝 Description",
    "quickadd.btnToIncome": "🔁 Make it income",
    "quickadd.btnToExpense": "🔁 Make it an expense",
    "quickadd.save": "✅ Save",
    "quickadd.repeat": "🔁 Repeat last",
    "quickadd.another": "➕ Add another",
    "quickadd.help": "❓ Help",
    "quickadd.noCategory": "🚫 No category",
    "quickadd.noDesc": "🚫 No description",
    "quickadd.useCategory": "▫️ Use “{name}”",
    "quickadd.yesterday": "📅 Yesterday",

    # ── Editing one field of the draft ────────────────────────────────────────
    "quickadd.amountAsk": "Send the new <b>amount</b> in {currency}:",
    "quickadd.badAmount": "That doesn't look like an amount. Send something like "
                          "<code>50000</code>, <code>50k</code>, <code>1.5m</code> or "
                          "<code>250 ming</code>.",
    "quickadd.descAsk": "Send a <b>description</b> for this entry:",
    "quickadd.dateAsk": "Which date should it be filed under?",
    "quickadd.walletAskOut": "Which wallet did it come from?",
    "quickadd.walletAskIn": "Which wallet did it go into?",
    "quickadd.walletError": "❌ Couldn't load your wallets.\nRecording this as cash would put "
                            "the money in the wrong one, so nothing is offered until the list "
                            "loads.",
    "quickadd.cardShort": "⚠️ Cards marked with a warning hold less than {amount} — the backend "
                          "refuses a card payment larger than the card's balance.",
    "quickadd.categoryAsk": "Pick a <b>category</b>:",
    "quickadd.subCategoryAsk": "Pick a sub-category:",
    "quickadd.categoryError": "❌ Couldn't load your categories. The draft is unchanged.",
    "quickadd.categoryNone": "No categories are set up for this yet.",

    # ── Saving ────────────────────────────────────────────────────────────────
    "quickadd.notSaved": "Nothing was saved — the draft is still here. Fix what's wrong and "
                         "tap Save again.",
    "quickadd.saved.expense": "✅ Expense of <b>{amount}</b> saved.",
    "quickadd.saved.income": "✅ Income of <b>{amount}</b> saved.",
    "quickadd.savedProgress": "📊 <b>{label}</b>: {paid} / {target}",

    # ── A draft that outlived the process that held it ────────────────────────
    "quickadd.expiredToast": "That draft is gone.",
    "quickadd.expired": "⌛️ <b>That draft is gone</b>\n\nThe bot restarted while it was open, so "
                        "nothing was saved. Send the amount again and it takes one tap.",

    # ── Repeat last ───────────────────────────────────────────────────────────
    "quickadd.repeatNone": "Nothing to repeat yet — record something first.",
    "quickadd.repeatError": "❌ Couldn't load your last entry.",
    "quickadd.repeatTransfer": "🔄 Your last entry was money moved between wallets. That is a "
                               "paired entry, so quick add can't copy it — record it from "
                               "Transactions.",
    "quickadd.repeatPlug": "🧮 Your last entry was a month-close adjustment, not something you "
                           "record by hand. There is nothing to repeat.",
    "quickadd.repeatNote": "<i>Copied from your last entry, dated today.</i>",
    "quickadd.repeatKindReset": "<i>The original was recorded as a special kind that needs "
                                "details this screen doesn't ask for, so the copy is a plain "
                                "entry. Use the full Add flow if you need that kind again.</i>",

    # ── Anything typed that isn't an amount ───────────────────────────────────
    "quickadd.notUnderstood": "🤔 <b>I didn't understand that.</b>\n\nTo record something, put "
                              "the amount first: <code>50000 lunch</code>, "
                              "<code>+2000000 salary</code>, <code>-50000 taxi</code>.\n"
                              "Everything else lives in the menu.",

    # ── Sub-types a repeated entry may carry ──────────────────────────────────
    "quickadd.kind.emergency": "🛟 Emergency fund",
    "quickadd.kind.investment": "📈 Investment",
    "quickadd.kind.stocks": "📊 Stocks",
    "quickadd.stocksNote": "<i>📊 Recorded as stocks. Stocks are not an allocation bucket, so "
                           "there is no monthly target for them.</i>",

    # ── Allocation preview, rebuilt locally from the response's numbers ───────
    "quickadd.countsToward": "📊 Counts toward <b>{label}</b>",
    "quickadd.allocTarget": "Target",
    "quickadd.allocPaid": "Set aside so far",
    "quickadd.allocAfter": "After this",
    "quickadd.allocStillToGo": "{amount} still to go.",
    "quickadd.allocCovered": "Fully covered. 🎉",
    "quickadd.allocNotRequired": "<i>Recorded, but nothing is expected there at your current "
                                 "level.</i>",
    "quickadd.bucket.donation": "Donation",
    "quickadd.bucket.emergency": "Emergency fund",
    "quickadd.bucket.investments": "Investments",
    "quickadd.bucket.savings": "Savings goals",
    "quickadd.bucket.stocks": "Stocks",
}

UZ: dict[str, str] = {
    "quickadd.startTitle": "⚡ <b>Tez qoʻshish</b>",
    "quickadd.startBody": "Summani va nima uchunligini bitta xabarda yuboring:\n"
                          "<code>50000 tushlik</code> · <code>50k taksi</code> · "
                          "<code>1.5m ijara</code> · <code>250 ming qahva</code>\n"
                          "Oldida <code>+</code> boʻlsa daromad, <code>-</code> boʻlsa xarajat "
                          "yoziladi.",

    "quickadd.draftTitle": "⚡ <b>Tez qoʻshish</b>",
    "quickadd.headExpense": "📉 <b>Xarajat</b> · <b>{amount}</b>",
    "quickadd.headIncome": "📈 <b>Daromad</b> · <b>{amount}</b>",
    "quickadd.field.date": "Sana",
    "quickadd.field.wallet": "Hamyon",
    "quickadd.field.category": "Kategoriya",
    "quickadd.field.description": "Tavsif",
    "quickadd.field.kind": "Xarajat turi",
    "quickadd.suffixToday": "(bugun)",
    "quickadd.suffixYesterday": "(kecha)",
    "quickadd.draftFoot": "<i>Saqlash bosilmaguncha hech narsa yozilmaydi.</i>",

    "quickadd.btnAmount": "💰 Summa",
    "quickadd.btnDate": "📅 Sana",
    "quickadd.btnWallet": "💳 Hamyon",
    "quickadd.btnCategory": "🗂 Kategoriya",
    "quickadd.btnDesc": "📝 Tavsif",
    "quickadd.btnToIncome": "🔁 Daromadga oʻzgartirish",
    "quickadd.btnToExpense": "🔁 Xarajatga oʻzgartirish",
    "quickadd.save": "✅ Saqlash",
    "quickadd.repeat": "🔁 Oxirgisini takrorlash",
    "quickadd.another": "➕ Yana qoʻshish",
    "quickadd.help": "❓ Yordam",
    "quickadd.noCategory": "🚫 Kategoriyasiz",
    "quickadd.noDesc": "🚫 Tavsifsiz",
    "quickadd.useCategory": "▫️ “{name}” ni tanlash",
    "quickadd.yesterday": "📅 Kecha",

    "quickadd.amountAsk": "Yangi <b>summani</b> {currency} da yuboring:",
    "quickadd.badAmount": "Bu summaga oʻxshamaydi. <code>50000</code>, <code>50k</code>, "
                          "<code>1.5m</code> yoki <code>250 ming</code> koʻrinishida yuboring.",
    "quickadd.descAsk": "Ushbu yozuv uchun <b>tavsif</b> yuboring:",
    "quickadd.dateAsk": "Qaysi sanaga yozilsin?",
    "quickadd.walletAskOut": "Pul qaysi hamyondan chiqdi?",
    "quickadd.walletAskIn": "Pul qaysi hamyonga tushdi?",
    "quickadd.walletError": "❌ Hamyonlarni yuklab boʻlmadi.\nBuni naqd deb yozib qoʻysak, pul "
                            "notoʻgʻri hamyonga tushadi — shuning uchun roʻyxat yuklanmaguncha "
                            "hech narsa taklif qilinmaydi.",
    "quickadd.cardShort": "⚠️ Belgisi bor kartalarda {amount} dan kam pul bor — balansdan ortiq "
                          "karta toʻlovini backend qabul qilmaydi.",
    "quickadd.categoryAsk": "<b>Kategoriyani</b> tanlang:",
    "quickadd.subCategoryAsk": "Ichki kategoriyani tanlang:",
    "quickadd.categoryError": "❌ Kategoriyalarni yuklab boʻlmadi. Qoralama oʻzgarmadi.",
    "quickadd.categoryNone": "Buning uchun hali kategoriya yaratilmagan.",

    "quickadd.notSaved": "Hech narsa saqlanmadi — qoralama joyida turibdi. Xatoni tuzatib, "
                         "yana Saqlashni bosing.",
    "quickadd.saved.expense": "✅ <b>{amount}</b> xarajat saqlandi.",
    "quickadd.saved.income": "✅ <b>{amount}</b> daromad saqlandi.",
    "quickadd.savedProgress": "📊 <b>{label}</b>: {paid} / {target}",

    "quickadd.expiredToast": "Bu qoralama yoʻqoldi.",
    "quickadd.expired": "⌛️ <b>Bu qoralama yoʻqoldi</b>\n\nU ochiq turganda bot qayta ishga "
                        "tushgan, shuning uchun hech narsa saqlanmadi. Summani qaytadan "
                        "yuboring — bitta bosishda tayyor boʻladi.",

    "quickadd.repeatNone": "Takrorlash uchun hali yozuv yoʻq — avval biror narsa yozing.",
    "quickadd.repeatError": "❌ Oxirgi yozuvingizni yuklab boʻlmadi.",
    "quickadd.repeatTransfer": "🔄 Oxirgi yozuvingiz hamyonlar orasida koʻchirilgan pul edi. U "
                               "juft yozuv, shuning uchun tez qoʻshish uni nusxalay olmaydi — "
                               "Tranzaksiyalar boʻlimidan yozing.",
    "quickadd.repeatPlug": "🧮 Oxirgi yozuvingiz oy yopilishidagi tenglashtirish edi, uni qoʻlda "
                           "yozilmaydi. Takrorlaydigan narsa yoʻq.",
    "quickadd.repeatNote": "<i>Oxirgi yozuvingizdan nusxa, bugungi sana bilan.</i>",
    "quickadd.repeatKindReset": "<i>Asl yozuv maxsus turda edi va u tur bu ekran soʻramaydigan "
                                "maʼlumotlarni talab qiladi, shuning uchun nusxa oddiy yozuv "
                                "boʻldi. Oʻsha tur yana kerak boʻlsa, toʻliq Qoʻshish oqimidan "
                                "foydalaning.</i>",

    "quickadd.notUnderstood": "🤔 <b>Buni tushunmadim.</b>\n\nBiror narsa yozish uchun avval "
                              "summani yuboring: <code>50000 tushlik</code>, "
                              "<code>+2000000 oylik</code>, <code>-50000 taksi</code>.\n"
                              "Qolgan hamma narsa menyuda.",

    "quickadd.kind.emergency": "🛟 Favqulodda jamgʻarma",
    "quickadd.kind.investment": "📈 Investitsiya",
    "quickadd.kind.stocks": "📊 Aksiyalar",
    "quickadd.stocksNote": "<i>📊 Aksiya sifatida yozildi. Aksiyalar taqsimot bandi emas, "
                           "shuning uchun ular uchun oylik maqsad yoʻq.</i>",

    "quickadd.countsToward": "📊 <b>{label}</b>ga hisoblanadi",
    "quickadd.allocTarget": "Maqsad",
    "quickadd.allocPaid": "Hozirgacha ajratilgan",
    "quickadd.allocAfter": "Shundan keyin",
    "quickadd.allocStillToGo": "Yana {amount} qoldi.",
    "quickadd.allocCovered": "Toʻliq qoplandi. 🎉",
    "quickadd.allocNotRequired": "<i>Yozib qoʻyiladi, lekin hozirgi darajangizda undan talab "
                                 "qilinmaydi.</i>",
    "quickadd.bucket.donation": "Xayriya",
    "quickadd.bucket.emergency": "Favqulodda jamgʻarma",
    "quickadd.bucket.investments": "Investitsiyalar",
    "quickadd.bucket.savings": "Jamgʻarma maqsadlari",
    "quickadd.bucket.stocks": "Aksiyalar",
}
