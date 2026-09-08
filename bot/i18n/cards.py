"""Wallets: the bank cards and the one cash pot.

`cards.*`

The key prefix still says `cards` because that is the endpoint and the callback namespace,
but the SCREEN is Wallets — cards plus cash on one list — which is what the web app calls it
for this same person. Strings that talk about one piece of plastic still say "card".

Cash is singular here, not a list. The app has been UZS-only since the currency pivot and the
backend upserts one cash row per currency, so "cash balances" could only ever render a list of
exactly one; it is now "your cash", with the amount you hold as the thing you set.

The cash pot has TWO readings and the strings have to keep them apart, because the question the
bot asks and the field the endpoint stores are not the same number. `cards.cashNow` is what is
in hand; `cards.cashStart` is the opening figure `POST /cash-balances` writes; `cards.cashDelta`
is the difference between them, which is the net of every cash transaction on record. The old
`cashStart` said "Starting amount" while the prompt above it asked for "right now", so the two
lines read as the same quantity printed twice.
"""

EN: dict[str, str] = {
    # ── the Wallets list ────────────────────────────────────────────────────
    "cards.title": "💳 <b>Wallets</b>",
    "cards.noneYet": "No cards yet.",
    "cards.line": "{name} — {bank} {type} ···{last4}: {balance}",
    "cards.cashRow": "💵 <b>Cash</b>: {balance}",
    "cards.cashRowUnset": "💵 <b>Cash</b>: not set yet",
    "cards.cashRowUnavailable": "💵 <b>Cash</b>: couldn't be loaded",
    "cards.totalHeld": "<b>Everything you hold: {total}</b>",
    "cards.totalSplit": "<i>Cards {cards} · Cash {cash}</i>",
    "cards.addCard": "➕ Add card",
    "cards.backToWallets": "⬅️ Wallets",
    "cards.loadError": "❌ Couldn't load Wallets.",
    # ── one card ────────────────────────────────────────────────────────────
    "cards.viewLoadError": "❌ Couldn't load that card.",
    "cards.viewHeader": "💳 <b>{name}</b>\n{bank} · {type} · ···{last4}",
    "cards.initial": "Starting balance: {amount}",
    "cards.current": "Balance now: <b>{amount}</b>",
    "cards.deleteConfirm": "Delete <b>{name}</b>?\n\nTransactions paid with it keep their history but "
                           "lose the card link. Nothing else is deleted.",
    "cards.gone": "That card no longer exists.",
    "cards.deleted": "🗑 Card deleted.",
    # ── editing a card ──────────────────────────────────────────────────────
    "cards.editTitle": "✏️ <b>Edit card</b>\nWhich part is wrong?",
    "cards.editPrompt": "<b>{field}</b>\nNow: {current}\n\nSend the new value:",
    "cards.editBalancePrompt": "<b>{field}</b>\nNow: {current} — the card holds {balance} today."
                               "\n\nThis is the opening figure, not today's balance: every "
                               "transaction on the card is added to it."
                               "\n\nSend the new starting balance:",
    "cards.editPickType": "<b>{field}</b>\nNow: {current}\n\nPick the card network:",
    "cards.emptyValue": "Send the new value as text.",
    "cards.saved": "✅ Card updated.",
    "cards.saveError": "❌ Couldn't save that change.",
    "cards.deleteError": "❌ Couldn't delete that card.",
    "cards.expired": "That form is no longer open. Start again from Wallets.",
    # ── the cash pot ────────────────────────────────────────────────────────
    "cards.cashTitle": "💵 <b>Cash</b>",
    "cards.cashNow": "In hand now: <b>{amount}</b>",
    "cards.cashDelta": "Cash transactions recorded: {amount}",
    "cards.cashStart": "Opening figure: {amount}",
    "cards.cashNote": "<i>Tell Tracker what you hold now; it works out the opening figure that, "
                      "plus every cash transaction you record, adds back up to it.</i>",
    "cards.noCashSet": "You haven't told Tracker how much cash you hold yet.",
    "cards.setCashBalance": "💵 Set cash amount",
    "cards.cashPrompt": "How much cash do you hold <b>right now</b>?",
    "cards.cashPromptNote": "<i>Tracker works the opening figure out from your answer — that "
                            "figure, plus every cash transaction you record, is the balance "
                            "you see.</i>",
    "cards.cashSaved": "✅ Cash amount saved.",
    "cards.cashLoadError": "❌ Couldn't load your cash balance.",
    "cards.cashReadFirst": "❌ Couldn't read your cash balance, so nothing was saved — the "
                           "opening figure is worked out from it.",
    # ── the create wizard's field labels ────────────────────────────────────
    "cards.new.title": "New card",
    "cards.new.name": "Card name",
    "cards.new.bankName": "Bank name",
    "cards.new.type": "Card network",
    "cards.new.last4": "Last 4 digits",
    "cards.new.last4Msg": "Enter exactly 4 digits.",
    "cards.new.initialBalance": "Starting balance",
    "cards.new.success": "Card added.",
}

UZ: dict[str, str] = {
    "cards.title": "💳 <b>Hamyonlar</b>",
    "cards.noneYet": "Hozircha kartalar yoʻq.",
    "cards.line": "{name} — {bank} {type} ···{last4}: {balance}",
    "cards.cashRow": "💵 <b>Naqd pul</b>: {balance}",
    "cards.cashRowUnset": "💵 <b>Naqd pul</b>: hali kiritilmagan",
    "cards.cashRowUnavailable": "💵 <b>Naqd pul</b>: yuklab boʻlmadi",
    "cards.totalHeld": "<b>Qoʻlingizdagi hamma pul: {total}</b>",
    "cards.totalSplit": "<i>Kartalar {cards} · Naqd {cash}</i>",
    "cards.addCard": "➕ Karta qoʻshish",
    "cards.backToWallets": "⬅️ Hamyonlar",
    "cards.loadError": "❌ Hamyonlarni yuklab boʻlmadi.",
    "cards.viewLoadError": "❌ Bu kartani yuklab boʻlmadi.",
    "cards.viewHeader": "💳 <b>{name}</b>\n{bank} · {type} · ···{last4}",
    "cards.initial": "Boshlangʻich balans: {amount}",
    "cards.current": "Hozirgi balans: <b>{amount}</b>",
    "cards.deleteConfirm": "<b>{name}</b> oʻchirilsinmi?\n\nShu karta bilan qilingan tranzaksiyalar "
                           "tarixda qoladi, faqat karta bilan bogʻlanishi yoʻqoladi. Boshqa hech "
                           "narsa oʻchmaydi.",
    "cards.gone": "Bu karta endi mavjud emas.",
    "cards.deleted": "🗑 Karta oʻchirildi.",
    "cards.editTitle": "✏️ <b>Kartani tahrirlash</b>\nQaysi qismi notoʻgʻri?",
    "cards.editPrompt": "<b>{field}</b>\nHozir: {current}\n\nYangi qiymatni yuboring:",
    "cards.editBalancePrompt": "<b>{field}</b>\nHozir: {current} — kartada bugun {balance} bor."
                               "\n\nBu boshlangʻich summa, bugungi balans emas: kartadagi har "
                               "bir tranzaksiya unga qoʻshiladi."
                               "\n\nYangi boshlangʻich balansni yuboring:",
    "cards.editPickType": "<b>{field}</b>\nHozir: {current}\n\nKarta tarmogʻini tanlang:",
    "cards.emptyValue": "Yangi qiymatni matn koʻrinishida yuboring.",
    "cards.saved": "✅ Karta yangilandi.",
    "cards.saveError": "❌ Oʻzgarishni saqlab boʻlmadi.",
    "cards.deleteError": "❌ Kartani oʻchirib boʻlmadi.",
    "cards.expired": "Bu shakl endi ochiq emas. Hamyonlardan qaytadan boshlang.",
    "cards.cashTitle": "💵 <b>Naqd pul</b>",
    "cards.cashNow": "Hozir qoʻlingizda: <b>{amount}</b>",
    "cards.cashDelta": "Yozilgan naqd tranzaksiyalar: {amount}",
    "cards.cashStart": "Boshlangʻich summa: {amount}",
    "cards.cashNote": "<i>Hozir qoʻlingizda qancha borligini ayting; Tracker boshlangʻich summani "
                      "oʻzi hisoblab qoʻyadi — oʻsha summa siz yozgan har bir naqd tranzaksiya "
                      "bilan qoʻshilib, aynan shu raqamni beradi.</i>",
    "cards.noCashSet": "Qoʻlingizda qancha naqd pul borligini hali kiritmagansiz.",
    "cards.setCashBalance": "💵 Naqd pul miqdorini kiritish",
    "cards.cashPrompt": "<b>Hozir</b> qoʻlingizda qancha naqd pul bor?",
    "cards.cashPromptNote": "<i>Boshlangʻich summani Tracker javobingizdan hisoblaydi — oʻsha "
                            "summa siz yozgan har bir naqd tranzaksiya bilan qoʻshilib, "
                            "koʻrinadigan balansni beradi.</i>",
    "cards.cashSaved": "✅ Naqd pul miqdori saqlandi.",
    "cards.cashLoadError": "❌ Naqd pul balansini yuklab boʻlmadi.",
    "cards.cashReadFirst": "❌ Naqd pul balansini oʻqib boʻlmadi, shuning uchun hech narsa "
                           "saqlanmadi — boshlangʻich summa oʻsha balansdan hisoblanadi.",
    "cards.new.title": "Yangi karta",
    "cards.new.name": "Karta nomi",
    "cards.new.bankName": "Bank nomi",
    "cards.new.type": "Karta tarmogʻi",
    "cards.new.last4": "Oxirgi 4 ta raqam",
    "cards.new.last4Msg": "Aniq 4 ta raqam kiriting.",
    "cards.new.initialBalance": "Boshlangʻich balans",
    "cards.new.success": "Karta qoʻshildi.",
}
