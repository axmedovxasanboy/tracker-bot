"""Months: the running summary, the permanent close flow, the closed-month history.

`months.*`

The vocabulary here has to match the Home and Plan screens exactly — the owner reads the
same month's income on all three. In Uzbek that word is "daromad" everywhere; the bare
participle "topildi" used to make the Months figure look like a different quantity.

Three lines carry the distinction the whole envelope rests on, and they are the reason this
screen is worded the way it is (`MonthSummaryResponse`):

* `taggedTotal` — the "Set aside" headline. It COUNTS "already paid" marks.
* `taggedRecorded` — the half that really left a wallet, and the only half a close freezes.
* `markedNotMoved` — the difference: money declared paid that never moved.

So `taggedRecorded` and `markedNotMoved` never claim money "went" anywhere on their own, and
`marksNote` says outright that a mark moved nothing. The failure being prevented is the owner
reading the headline, believing the money left, and freezing that belief into a month that no
endpoint can reopen.

The close copy (`introBody`, `permanentWarning`, `reviewHint`) sits in front of exactly that
irreversible commit, so it is plain rather than reassuring.
"""

EN: dict[str, str] = {
    # ── the month summary ───────────────────────────────────────────────────
    "months.summaryTitle": "🗓 <b>Monthly Summary</b> · {currency} · {month}",
    "months.closed": "🔒 Closed",
    "months.open": "🟡 Open — not closed yet",
    "months.startedWith": "▶️ Started with: {amount}",
    "months.earned": "📈 Earned: <b>{amount}</b>",
    "months.spent": "📉 Spent: <b>{amount}</b>",
    "months.left": "💰 Left: <b>{amount}</b>",
    "months.whereItWent": "<b>Where it went</b>",
    "months.donation": "• Donation: {amount}",
    "months.emergency": "• Emergency fund: {amount}",
    "months.investments": "• Investments: {amount}",
    "months.stocks": "• Stocks: {amount}",
    "months.savingsGoals": "• Savings goals: {amount}",
    "months.taggedTotal": "• Set aside total: <b>{amount}</b>",
    # Printed only when there are marks. Indented, because they are the two halves of the
    # line above them — never a third bucket.
    "months.taggedRecorded": "   ↳ Set aside that left your wallets: <b>{amount}</b>",
    "months.markedNotMoved": "   ↳ Marked as paid, but never moved: {amount}",
    "months.marksNote": "<i>A mark is you saying a bill is settled — no money left a wallet for it. "
                        "Only what really left counts as spent when the month closes.</i>",
    "months.everydaySpending": "• Everyday spending: {amount}",
    "months.everydayPending": "• Everyday spending: <i>known once you close the month</i>",
    "months.closeThisMonth": "🔒 Close this month",
    "months.closeMonthBtn": "🔒 Close {month}",
    "months.historyBtn": "📜 History",
    "months.backBtn": "⬅️ Months",
    "months.summaryLoadError": "❌ Couldn't load the monthly summary.",
    # ── closed-month history ────────────────────────────────────────────────
    "months.historyTitle": "📜 <b>Closed months</b> · {currency}\n",
    "months.noneClosedYet": "No months closed yet.",
    "months.historyLine": "<b>{month}</b>: earned {earned} · spent {spent} · left {left}",
    "months.historyLoadError": "❌ Couldn't load history.",
    # ── why a month can't be closed ─────────────────────────────────────────
    "months.closePreviewError": "❌ Couldn't load the close preview.",
    "months.cantCloseYet": "This month can't be closed yet.",
    "months.allClosed": "✅ <b>Everything up to {month} is closed.</b>\n\n"
                        "There is no month left to reconcile. The next one can be closed once it has ended.",
    # Each names one refusal from the backend and what to do about it. They are rendered
    # after a 🔒 or ❌ prefix, so none of them carries an emoji of its own.
    "months.blocked.alreadyClosed": "<b>{month}</b> is already closed and locked, so there is nothing "
                                    "left to enter for it. Move on to the next open month.",
    "months.blocked.futureMonth": "That month has not finished yet. Only the month you are in now, or an "
                                  "earlier one, can be closed — come back once it has ended.",
    "months.blocked.outOfOrder": "Months are closed in order, so <b>{month}</b> has to go first. "
                                 "Finish that one and this month becomes the next in line.",
    "months.blocked.locked": "<b>{month}</b> is closed and locked — its transactions can no longer be "
                             "changed. Record this in a month that is still open.",
    "months.blocked.noIncome": "Your monthly stable income isn't set yet, and every figure on this screen "
                               "is worked out from it. Set it in Settings, then come back and close the month.",
    "months.closeRefused": "❌ The server refused to close the month. Nothing was saved and every balance "
                           "you typed is still here.",
    # ── picking the month to close ──────────────────────────────────────────
    "months.pickTitle": "🗓 <b>Which month are you closing?</b>",
    "months.pickBody": "Nothing has been closed yet, so you can start wherever you like. Pick the earliest "
                       "month you can still remember real wallet balances for — after this first one, "
                       "months close in order.",
    "months.pickAnotherBtn": "🗓 A different month",
    # ── the close intro: the figures, then the warning ──────────────────────
    "months.introTitle": "🔒 <b>Closing {month}</b>",
    "months.pastMonthNote": "<i>This is a past month — {count} behind the one you are in now. Enter the "
                            "balances as they stood at the end of it, not the ones you hold today.</i>",
    "months.spendableNow": "💵 Spendable right now: <b>{amount}</b>",
    "months.introBody": "Next you enter each wallet's <b>real</b> balance at the end of the month — "
                        "{count} in all. Whatever the app can't account for becomes your everyday "
                        "spending, and the balance you enter carries into next month.",
    "months.permanentWarning": "\n⚠️ This is <b>permanent</b> — the month locks and can't be reopened.",
    "months.startBtn": "▶️ Enter balances",
    "months.tapStart": "There is nothing to type here yet. Use the buttons below to start entering your "
                       "wallet balances.",
    # ── one wallet at a time ────────────────────────────────────────────────
    "months.noWallets": "No wallets to reconcile for this month.",
    "months.closeHeader": "🔒 <b>Close {month}</b> · wallet {index}/{total}",
    "months.walletPrompt": "<b>{label}</b>\nApp computed: {computed}\n\n"
                           "Send this wallet's <b>real balance</b> at month-end (in {currency}):",
    "months.walletComputed": "App computed: {amount}",
    "months.overdrawnNote": "<i>That is below zero — more spending is recorded against this wallet than "
                            "money went into it. A balance can't be negative, so send what you actually "
                            "hold, or 0 if it is empty.</i>",
    "months.walletAsk": "Send this wallet's <b>real balance</b> at the end of the month (in {currency}):",
    "months.useComputed": "Use {amount}",
    "months.useZero": "Use 0",
    "months.keepEntered": "Keep {amount}",
    "months.negativeBalance": "A balance can't be negative. Send what you actually hold, or 0 if the "
                              "wallet is empty.",
    "months.unnamedWallet": "Unnamed wallet",
    # ── review, then the irreversible commit ────────────────────────────────
    "months.confirmCloseHeader": "🔒 <b>Confirm closing {month}</b>",
    "months.realBalancesEntered": "Real balances entered:",
    "months.walletLine": "{index}. {label}: <b>{amount}</b>",
    "months.reviewTotal": "<b>Total entered: {amount}</b>",
    "months.reviewHint": "Check every figure. Tap a wallet to correct it — once you confirm, nothing here "
                         "can be changed again, by you or by anyone.",
    "months.editWalletBtn": "✏️ {label}",
    "months.confirmClose": "✅ Confirm close",
    "months.tapConfirm": "There is nothing to type here. Tap a wallet above to correct its balance, or "
                         "confirm the close with the button.",
    # ── the result ──────────────────────────────────────────────────────────
    "months.closedResultTitle": "✅ <b>{month} closed.</b> ({currency})",
    "months.resultEarned": "📈 Earned: {amount}",
    "months.resultSpent": "📉 Spent: {amount}",
    "months.resultEveryday": "🧹 Everyday: {amount}",
    "months.resultLeftover": "💰 Left → next month: {amount}",
    # ── a tap that outlived its flow ────────────────────────────────────────
    "months.flowExpired": "⌛ That month close was interrupted, and the balances you had entered are gone. "
                          "No month was closed — start again when you are ready.",
    "months.startAgainBtn": "🔒 Start again",
}

UZ: dict[str, str] = {
    "months.summaryTitle": "🗓 <b>Oylik hisobot</b> · {currency} · {month}",
    "months.closed": "🔒 Yopilgan",
    "months.open": "🟡 Ochiq — hali yopilmagan",
    "months.startedWith": "▶️ Boshlangʻich: {amount}",
    "months.earned": "📈 Daromad: <b>{amount}</b>",
    "months.spent": "📉 Sarflandi: <b>{amount}</b>",
    "months.left": "💰 Qoldi: <b>{amount}</b>",
    "months.whereItWent": "<b>Qayerga ketdi</b>",
    "months.donation": "• Xayriya: {amount}",
    "months.emergency": "• Favqulodda jamgʻarma: {amount}",
    "months.investments": "• Investitsiyalar: {amount}",
    "months.stocks": "• Aksiyalar: {amount}",
    "months.savingsGoals": "• Jamgʻarma maqsadlari: {amount}",
    # "Ajratilgan", not "Belgilangan": in the web app "Belgilangan" is the marked-as-paid
    # badge, so using it here for the set-aside total names two different things one word.
    "months.taggedTotal": "• Ajratilgan jami: <b>{amount}</b>",
    # The web app's own words for the split: "Hamyondan chiqqan ajratma" against
    # "toʻlangan deb belgilangan (pul hamyondan chiqmagan)".
    "months.taggedRecorded": "   ↳ Hamyondan chiqqan ajratma: <b>{amount}</b>",
    "months.markedNotMoved": "   ↳ Toʻlangan deb belgilangan, lekin chiqmagan: {amount}",
    "months.marksNote": "<i>Belgilash — hisobni toʻladim deb qayd etish, pul esa hamyondan chiqmagan. "
                        "Oy yopilganda faqat haqiqatan chiqqan pul sarflangan hisoblanadi.</i>",
    "months.everydaySpending": "• Kundalik xarajat: {amount}",
    "months.everydayPending": "• Kundalik xarajat: <i>oy yopilgach maʼlum boʻladi</i>",
    "months.closeThisMonth": "🔒 Bu oyni yopish",
    "months.closeMonthBtn": "🔒 {month} ni yopish",
    "months.historyBtn": "📜 Tarix",
    "months.backBtn": "⬅️ Oylar",
    "months.summaryLoadError": "❌ Oylik hisobotni yuklab boʻlmadi.",
    "months.historyTitle": "📜 <b>Yopilgan oylar</b> · {currency}\n",
    "months.noneClosedYet": "Hali hech qanday oy yopilmagan.",
    "months.historyLine": "<b>{month}</b>: daromad {earned} · sarflandi {spent} · qoldi {left}",
    "months.historyLoadError": "❌ Tarixni yuklab boʻlmadi.",
    "months.closePreviewError": "❌ Yopish oldindan koʻrishni yuklab boʻlmadi.",
    "months.cantCloseYet": "Bu oyni hali yopib boʻlmaydi.",
    "months.allClosed": "✅ <b>{month} gacha hamma oy yopilgan.</b>\n\n"
                        "Solishtiradigan oy qolmadi. Keyingisini u tugagach yopasiz.",
    "months.blocked.alreadyClosed": "<b>{month}</b> allaqachon yopilgan va qulflangan, unga endi hech "
                                    "narsa kiritib boʻlmaydi. Keyingi ochiq oyga oʻting.",
    "months.blocked.futureMonth": "Bu oy hali tugamagan. Faqat hozirgi oyni yoki undan oldingisini yopish "
                                  "mumkin — oy tugagach qaytib keling.",
    "months.blocked.outOfOrder": "Oylar navbati bilan yopiladi, shuning uchun avval <b>{month}</b> "
                                 "yopilishi kerak. Oʻshani yakunlasangiz, navbat bu oyga keladi.",
    "months.blocked.locked": "<b>{month}</b> yopilgan va qulflangan — undagi tranzaksiyalarni endi "
                             "oʻzgartirib boʻlmaydi. Buni hali ochiq boʻlgan oyga yozing.",
    "months.blocked.noIncome": "Oylik barqaror daromadingiz hali kiritilmagan, bu sahifadagi har bir raqam "
                               "oʻshandan hisoblanadi. Uni Sozlamalardan kiriting va qaytib kelib oyni yoping.",
    "months.closeRefused": "❌ Server oyni yopishni rad etdi. Hech narsa saqlanmadi, siz kiritgan qoldiqlar "
                           "joyida turibdi.",
    "months.pickTitle": "🗓 <b>Qaysi oyni yopyapsiz?</b>",
    "months.pickBody": "Hali birorta oy yopilmagan, shuning uchun istagan oydan boshlashingiz mumkin. "
                       "Haqiqiy hamyon qoldiqlarini eslay oladigan eng eski oyni tanlang — birinchisidan "
                       "keyin oylar navbati bilan yopiladi.",
    "months.pickAnotherBtn": "🗓 Boshqa oy",
    "months.introTitle": "🔒 <b>{month} ni yopish</b>",
    "months.pastMonthNote": "<i>Bu oʻtgan oy — hozirgi oydan {count} oy orqada. Bugungi emas, oʻsha oy "
                            "oxiridagi qoldiqlarni kiriting.</i>",
    "months.spendableNow": "💵 Hozir sarflash mumkin: <b>{amount}</b>",
    "months.introBody": "Endi har bir hamyonning oy oxiridagi <b>haqiqiy</b> qoldigʻini kiritasiz — jami "
                        "{count} ta. Ilova hisobga ololmagan farq kundalik xarajatingiz boʻladi, siz "
                        "kiritgan qoldiq esa keyingi oyga oʻtadi.",
    "months.permanentWarning": "\n⚠️ Bu <b>qaytarib boʻlmaydigan</b> amal — oy qulflanadi va qayta ochilmaydi.",
    "months.startBtn": "▶️ Qoldiqlarni kiritish",
    "months.tapStart": "Bu yerda hozircha yozadigan narsa yoʻq. Hamyon qoldiqlarini kiritishni boshlash "
                       "uchun quyidagi tugmalardan foydalaning.",
    "months.noWallets": "Bu oy uchun solishtiriladigan hamyonlar yoʻq.",
    "months.closeHeader": "🔒 <b>{month} ni yopish</b> · hamyon {index}/{total}",
    "months.walletPrompt": "<b>{label}</b>\nIlova hisoblagani: {computed}\n\n"
                           "Oy oxiridagi <b>haqiqiy balansni</b> yuboring ({currency} da):",
    "months.walletComputed": "Ilova hisoblagani: {amount}",
    "months.overdrawnNote": "<i>Bu noldan past — bu hamyonga tushganidan koʻra koʻproq xarajat yozilgan. "
                            "Qoldiq manfiy boʻlolmaydi, shuning uchun qoʻlingizda qancha bor boʻlsa, "
                            "oʻshani yuboring, boʻsh boʻlsa 0 ni.</i>",
    "months.walletAsk": "Oy oxiridagi <b>haqiqiy qoldiqni</b> yuboring ({currency} da):",
    "months.useComputed": "{amount} dan foydalanish",
    "months.useZero": "0 dan foydalanish",
    "months.keepEntered": "{amount} qolsin",
    "months.negativeBalance": "Qoldiq manfiy boʻlolmaydi. Qoʻlingizda qancha bor boʻlsa, oʻshani yuboring, "
                              "hamyon boʻsh boʻlsa 0 ni.",
    "months.unnamedWallet": "Nomsiz hamyon",
    "months.confirmCloseHeader": "🔒 <b>{month} ni yopishni tasdiqlash</b>",
    "months.realBalancesEntered": "Kiritilgan haqiqiy balanslar:",
    "months.walletLine": "{index}. {label}: <b>{amount}</b>",
    "months.reviewTotal": "<b>Jami kiritilgan: {amount}</b>",
    "months.reviewHint": "Har bir raqamni tekshiring. Tuzatish uchun hamyon tugmasini bosing — "
                         "tasdiqlaganingizdan keyin bu yerdagi hech narsani hech kim, hatto siz ham "
                         "oʻzgartira olmaysiz.",
    "months.editWalletBtn": "✏️ {label}",
    "months.confirmClose": "✅ Yopishni tasdiqlash",
    "months.tapConfirm": "Bu yerda yozadigan narsa yoʻq. Qoldiqni tuzatish uchun yuqoridagi hamyonni "
                         "bosing yoki tugma orqali yopishni tasdiqlang.",
    "months.closedResultTitle": "✅ <b>{month} yopildi.</b> ({currency})",
    "months.resultEarned": "📈 Daromad: {amount}",
    "months.resultSpent": "📉 Sarflandi: {amount}",
    "months.resultEveryday": "🧹 Kundalik: {amount}",
    "months.resultLeftover": "💰 Qoldi → keyingi oyga: {amount}",
    "months.flowExpired": "⌛ Oyni yopish jarayoni uzilib qoldi, kiritgan qoldiqlaringiz saqlanmadi. "
                          "Hech qanday oy yopilmadi — tayyor boʻlganingizda qaytadan boshlang.",
    "months.startAgainBtn": "🔒 Qaytadan boshlash",
}
