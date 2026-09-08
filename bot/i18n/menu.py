"""Main menu, Home, Plan, Settings and the factory-reset danger zone.

`menu.*`

The three screen names here follow the web app, not the bot's own history: the landing
screen is Home (not "Dashboard"), the allocation screen is Plan (not "Overview") and the
cards+cash screen is Wallets (not "Cards"). The owner drives both clients over the same
data; one screen with two names costs them a translation every time they switch.

Three groups of keys in here exist purely to stop the backend's English reaching the owner,
and they are the reason this module is as long as it is:

* `menu.bucket.*` — the four allocation buckets. `AllocationLine.label` is a hard-coded
  English string on the server ("Donation", "Emergency", "Investments"); `AllocationLine.bucket`
  is the stable identifier the web app keys off instead. The Uzbek words match `months.*`
  verbatim, because the Months screen and the Plan screen name the same money.
* `menu.overview.scenario*` — `TierAllocation.scenarioLabel` is likewise English prose from a
  switch statement; `scenarioKey` ("1.2.3") is the identifier next to it. The level number is
  rendered separately by the screen, so these say only what the scenario IS, without repeating
  "Level 1.2" that the line above already carries.
* `menu.overview.act*` / `menu.overview.note*` — one per `TierAllocation.ActionItem.code`.
  The DTO's own Javadoc says the prose in `text` exists only "as the fallback for a client
  that has no entry for code", and this is the client that now has one. The `{amount}` values
  arrive from the API pre-formatted and pre-escaped by the router.
"""

EN: dict[str, str] = {
    # ── Main menu & navigation ──────────────────────────────────────────────
    # The one thing about this bot nobody can discover by looking at it: a bare message that
    # starts with an amount books a transaction. The main menu is the screen the owner sees
    # most, so the hint lives here rather than in a help screen they have no reason to open.
    # It replaces "Pick a section:", which eight labelled buttons already say.
    "menu.homeText": "🏠 <b>Tracker</b> — main menu\n"
                     "<i>Tip: type <code>50000 lunch</code> and the expense is recorded in "
                     "one message.</i>",
    "menu.openApp": "🚀 Open App",
    # Named with the same two words as `quickadd.startTitle`, the screen this button opens.
    "menu.quickAddBtn": "⚡ Quick add",
    "menu.helpBtn": "❓ Help",
    "menu.lock": "🔒 Lock",
    "menu.page.dashboard": "📊 Home",
    "menu.page.overview": "🎯 Plan",
    "menu.page.months": "🗓 Months",
    "menu.page.transactions": "💸 Transactions",
    "menu.page.cards": "💳 Wallets",
    "menu.page.finance": "🏦 Finance",
    "menu.page.categories": "🏷 Categories",
    "menu.page.settings": "⚙️ Settings",
    "menu.clearEverything": "🗑 Clear everything",
    "menu.lang.unchanged": "This is already the language in use.",

    # ── Home ────────────────────────────────────────────────────────────────
    # (the `dashboard` half of each key names the endpoint; the words name the screen)
    "menu.dashboardError": "❌ Couldn't load Home.",
    "menu.dashboard.title": "📊 <b>Home</b>",
    "menu.dashboard.spendable": "💵 Spendable",
    "menu.dashboard.netWorth": "🏦 Net worth",
    "menu.dashboard.netWorthNote": "<i>Net worth = spendable + investments &amp; savings</i>",
    "menu.dashboard.thisMonth": "<b>This month</b>",
    "menu.dashboard.income": "📈 Income",
    "menu.dashboard.expenses": "📉 Expenses",
    "menu.dashboard.net": "⚖️ Left over",
    # Lifetime totals are one grey line, not five headline figures: this is a monthly-envelope
    # product and a seven-digit all-time expense number answers nothing the owner asked.
    "menu.dashboard.allTime": "<i>All time: {income} in · {expense} out · {count} transactions</i>",
    # Shown instead of the month block and the all-time line when the account holds no
    # transactions at all. An empty Home is the one moment the owner is certain to be asking
    # "how do I put something in", so it answers that rather than printing six zeroes.
    "menu.dashboard.empty": "<i>Nothing recorded yet. Type <code>50000 lunch</code> straight "
                            "into the chat, or tap Quick add below.</i>",
    "menu.dashboard.byCategoryBtn": "🗂 Where it went",
    "menu.dashboard.yearBtn": "📆 This year",
    # Category breakdown
    "menu.dashboard.catsTitle": "🗂 <b>Where it went</b> · {month}",
    "menu.dashboard.catsSubExpense": "Spending by category",
    "menu.dashboard.catsSubIncome": "Income by category",
    "menu.dashboard.catsExpenseBtn": "📉 Expenses",
    "menu.dashboard.catsIncomeBtn": "📈 Income",
    "menu.dashboard.catLine": "• {name} — {amount} ({pct})",
    "menu.dashboard.catsTotal": "Total: <b>{amount}</b>",
    "menu.dashboard.catsMore": "<i>… and {n} smaller categories</i>",
    "menu.dashboard.catsError": "❌ Couldn't load the breakdown.",
    # Year view
    "menu.dashboard.yearTitle": "📆 <b>{year}</b> · month by month · {currency}",
    "menu.dashboard.yearLine": "<code>{month}</code>  +{income}  −{expense}  =  <b>{net}</b>",
    "menu.dashboard.yearTotals": "Year: +{income} · −{expense} · <b>{net}</b>",
    "menu.dashboard.yearEmpty": "<i>Nothing recorded in this year yet.</i>",
    "menu.dashboard.yearError": "❌ Couldn't load the year.",

    # ── Plan ────────────────────────────────────────────────────────────────
    "menu.overviewError": "❌ Couldn't load Plan.",
    "menu.overview.title": "🎯 <b>Plan</b>",
    "menu.overview.tierLine": "🏅 <b>{level}</b> · {scenario}",
    "menu.overview.tierLineBare": "🏅 <b>{level}</b>",
    "menu.overview.levelN": "Level {n}",
    "menu.overview.levelUnknown": "not computed yet",
    "menu.overview.levelAbove": "above the top tier",
    "menu.overview.stableIncome": "Stable income",
    "menu.overview.leftMoney": "Left money",
    "menu.overview.debtPayments": "Debt payments",
    "menu.overview.setIncomeWarning": "⚠️ <b>Set your monthly income in Settings</b> — tier &amp; allocation can't be computed yet.",
    "menu.overview.trackingStarts": "⏸ Allocation tracking starts <b>{month}</b> — nothing is due until then.",
    "menu.overview.subsPendingWarning": "🔒 <b>Pay your mandatory subscriptions first</b> — allocation unlocks once they're covered.",
    "menu.overview.subsPendingLine": "{name}: {paid} / {amount} paid",
    "menu.overview.allocationLocked": "🔒 Locked — clear the action items below first.",
    # Left balance is NOT the "Left money" line above it: it is that figure with the debt
    # payments already taken off, which is why the note spells the subtraction out.
    "menu.overview.baseNote": "<i>Percentages are taken from the left balance: {base} "
                              "(income − subscriptions − debt payments)</i>",
    "menu.overview.bucketsHeader": "<b>Set aside this month</b>",
    "menu.overview.bucketNoNeed": "{label}: <i>NO NEED this month</i>{extra}",
    "menu.overview.bucketPaidExtra": " · paid {paid}",
    "menu.overview.bucketLine": "{label}: <b>{left}</b> left of {minAmount} (≥{minPercent})",
    "menu.overview.bucketLineDone": "{label}: ✅ {minAmount} covered",
    "menu.overview.actionsHeader": "<b>Action items</b>",
    "menu.overview.actionProgress": "{text}\n   ↳ paid {paid} / {target}",
    "menu.overview.notesHeader": "<b>Notes</b>",
    "menu.overview.notesCount": "ℹ️ Notes: {n} — see Details.",
    "menu.overview.detailsBtn": "📋 Details",
    "menu.overview.historyBtn": "📜 History",
    # Plan → Details
    "menu.overview.detailsTitle": "📋 <b>Plan details</b> · {month}",
    "menu.overview.mathHeader": "<b>How the left balance is built</b>",
    "menu.overview.mandatorySubs": "Subscriptions",
    "menu.overview.leftBalance": "Left balance",
    "menu.overview.debtBank": "· bank loans",
    "menu.overview.debtLoans": "· loans taken",
    "menu.overview.debtDebts": "· debts",
    "menu.overview.debtRatio": "Debt ratio",
    "menu.overview.bucketsDetailHeader": "<b>Buckets</b>",
    "menu.overview.bucketDetailLine": "• {label}: target {target} · paid {paid} · left {left}",
    "menu.overview.bucketDetailNoNeed": "• {label}: not required this month · paid {paid}",
    "menu.overview.bucketMarkedNote": "   ✱ {amount} of that was marked as paid — no money left a wallet",

    # Scenario descriptors. The level number is printed on its own line above these, so none
    # of them repeats it — the server's own label does ("Level 1.2 — bank loan only, tight").
    "menu.overview.scenario11": "no debts",
    "menu.overview.scenario121Tight": "bank loan only · tight (under 5M UZS left after debt)",
    "menu.overview.scenario121Comfort": "bank loan only · comfortable (5M UZS or more left after debt)",
    "menu.overview.scenario122Tight": "debts only · tight (under 5M UZS left after debt)",
    "menu.overview.scenario122Comfort": "debts only · comfortable (5M UZS or more left after debt)",
    "menu.overview.scenario123": "bank loan and debts · fixed allocation",
    "menu.overview.scenario13": "heavy debt · over 70% of income",
    "menu.overview.scenarioUnset": "guidance for this tier isn't defined yet",

    # Action items, one per ActionItem.code the backend emits.
    "menu.overview.actPayBank": "Pay this month's bank installment.",
    "menu.overview.actPayPersonal": "Pay {amount} towards your personal loans this month.",
    "menu.overview.actPayDebts34": "Pay at least 34% of your debts / borrowed money "
                                   "(about {amount}) this month.",
    "menu.overview.actSetAside": "Set aside {amount} this month for your repayment plan.",
    "menu.overview.noteTight": "Less than 5M UZS is left after debt — allocations stay slim "
                               "until things ease up.",
    "menu.overview.noteComfortable": "5M UZS or more is left after debt — the higher "
                                     "allocations apply.",
    "menu.overview.noteLoanAndDebt": "Both a loan and debts — emergency fund and stocks are "
                                     "skipped at this tier; focus on the debt.",
    "menu.overview.noteHeavyDebt": "Heavy debt (over 70% of income): only a 2% donation this "
                                   "month. You may draw on the emergency fund if things get "
                                   "really bad.",
    "menu.overview.noteAboveCeiling": "You are above the top tier — guidance isn't defined for "
                                      "it yet.",
    "menu.overview.noteLevelRulesUnset": "You'll set the allocation rules for Level {level} "
                                         "yourself once you reach that tier.",
    "menu.overview.noteSubLevelRulesUnset": "Allocation for Level {subLevel} isn't set yet — "
                                            "define it in the rules editor in the web app.",
    "menu.overview.noteLoanPlanNotStarted": "{name}: your plan of {amount}/mo starts {month} — "
                                            "it isn't counted this month. Edit the loan to start "
                                            "it sooner.",
    "menu.overview.noteLoanChargeNotStarted": "{name}: the 34% charge of {amount}/mo starts "
                                              "{month} — it isn't counted this month. Edit the "
                                              "loan to start it sooner.",
    "menu.overview.noteDebtChargeNotStarted": "{name}: the 34% charge of {amount}/mo starts "
                                              "{month} — it isn't counted this month. Edit the "
                                              "debt to start it sooner.",

    # ── Bucket names ────────────────────────────────────────────────────────
    "menu.bucket.donation": "Donation",
    "menu.bucket.emergency": "Emergency fund",
    "menu.bucket.investments": "Investments",
    "menu.bucket.stocks": "Stocks",
    "menu.bucket.savings": "Savings goals",

    # ── Plan → one bucket ───────────────────────────────────────────────────
    "menu.bucket.btn": "🪣 {label}",
    "menu.bucket.title": "🪣 <b>{label}</b> · {month}",
    "menu.bucket.recommended": "Recommended: ≥{pct} — <b>{amount}</b>",
    "menu.bucket.notNeeded": "<i>Not required this month.</i>",
    "menu.bucket.paid": "Paid: <b>{amount}</b>",
    "menu.bucket.markedPart": "<i>of which marked as paid: {amount} — no money left a wallet, "
                              "and the month-close reconciliation ignores it</i>",
    "menu.bucket.left": "Left: <b>{amount}</b>",
    "menu.bucket.paymentsHeader": "<b>What makes up that figure</b>",
    "menu.bucket.row": "• <code>{date}</code> · {amount}{label}",
    "menu.bucket.markedBadge": " · <i>marked</i>",
    "menu.bucket.anonymous": "Anonymous",
    "menu.bucket.noPayments": "<i>Nothing recorded in this bucket this month.</i>",
    "menu.bucket.more": "<i>… and {n} older rows</i>",
    "menu.bucket.marksBtn": "🏷 Marked as paid",
    "menu.bucket.error": "❌ Couldn't load the payment list.",

    # ── Plan → allocation history (ledger) ──────────────────────────────────
    "menu.ledger.title": "📜 <b>Allocation history</b> · {month}",
    "menu.ledger.error": "❌ Couldn't load the allocation history.",
    "menu.ledger.startMonth": "<i>Tracked since {month}.</i>",
    "menu.ledger.due": "Due this month",
    "menu.ledger.carried": "Carried from earlier months",
    "menu.ledger.carriedRange": "<i>shortfalls from {start} to {end}</i>",
    "menu.ledger.totalDue": "Outstanding in total",
    "menu.ledger.bucketsHeader": "<b>By bucket</b>",
    "menu.ledger.bucketLine": "• {label}: {paid} / {recommended} · <b>{outstanding}</b> outstanding",
    "menu.ledger.bucketClear": "• {label}: {paid} / {recommended} · ✅",
    "menu.ledger.monthsHeader": "<b>Month by month</b>",
    "menu.ledger.monthLine": "<code>{month}</code>  due {due}  ·  paid {paid}",
    "menu.ledger.monthsMore": "<i>… and {n} earlier months</i>",

    # ── Settings ────────────────────────────────────────────────────────────
    "menu.settingsError": "❌ Couldn't load settings.",
    "menu.settings.title": "⚙️ <b>Settings</b>",
    "menu.settings.currency": "Currency",
    "menu.settings.stableIncome": "Stable income",
    "menu.settings.trackingMonth": "Allocation tracking starts",
    "menu.settings.trackingBtn": "📅 Tracking start month",
    "menu.settings.notSet": "not set",
    "menu.settings.locked": "🔒 locked",
    "menu.settings.hint": "<i>Every figure on Plan is calculated from your stable income, and "
                          "nothing can be recorded until it is set.</i>",

    # ── Settings → stable income ────────────────────────────────────────────
    "menu.income.title": "💰 <b>Monthly stable income</b>",
    "menu.income.current": "Now: <b>{amount}</b>",
    "menu.income.prompt": "Send the amount you can count on every month. Your tier and every "
                          "allocation figure are calculated from it.",
    "menu.income.examples": "<i>For example: 5000000 · 5 mln · 5 000 000</i>",
    "menu.income.saved": "✅ Stable income set to <b>{amount}</b>.",
    "menu.income.saveError": "❌ Couldn't save the income.",

    # ── Settings → allocation tracking start month ──────────────────────────
    "menu.track.title": "📅 <b>Allocation tracking start</b>",
    "menu.track.prompt": "Send the first month the allocation should be tracked from, "
                         "as YYYY-MM — for example {example}.",
    "menu.track.warning": "⚠️ <b>This can be set only once.</b> Once saved, neither the bot nor "
                          "the web app can change it.",
    "menu.track.lockedNow": "It is already set to <b>{month}</b> and can no longer be changed.",
    "menu.track.thisMonthBtn": "📅 This month ({month})",
    "menu.track.badMonth": "Send the month as YYYY-MM, for example {example}.",
    "menu.track.saved": "✅ Allocation tracking starts <b>{month}</b>.",
    "menu.track.saveError": "❌ Couldn't save the tracking start month.",

    # ── Danger zone / reset ─────────────────────────────────────────────────
    "menu.reset.title": "⚠️ <b>Danger Zone — Clear everything</b>",
    "menu.reset.body": "This permanently deletes <b>all</b> your data — transactions, wallets, "
                       "finance records, categories, settings, and your account — and starts the "
                       "app over from zero. This <b>cannot be undone</b>.",
    # The reset TRUNCATEs the settings table, and the bot's webhook + web-view URLs live in it.
    # The running process keeps working (it captured them at boot); the NEXT restart has nothing
    # to read and exits. Saying so before the password is typed is the whole point of this key.
    "menu.reset.botWarning": "⚠️ <b>It clears this bot's own setup too.</b> The webhook and "
                             "web-view URLs are stored in the same settings, so they go with "
                             "everything else. This bot keeps working until it is next "
                             "restarted — after that it cannot start at all until the URLs are "
                             "back in place.",
    "menu.reset.prompt": "Type your <b>password</b> to confirm, or tap Cancel.",
    "menu.reset.wrongPassword": "❌ Incorrect password. Nothing was deleted — type it again, "
                                "or tap Cancel.",
    "menu.reset.done": "✅ Everything was cleared. The app has started over from zero.\n\n"
                       "Tap below to create a new account.",
    "menu.reset.doneNote": "<i>The bot's webhook settings went with it. If the bot stops "
                           "answering after a restart, re-enter both URLs on the web app's "
                           "Developer page.</i>",
}

UZ: dict[str, str] = {
    # ── Bosh menyu ──────────────────────────────────────────────────────────
    "menu.homeText": "🏠 <b>Tracker</b> — bosh menyu\n"
                     "<i>Maslahat: <code>50000 tushlik</code> deb yozsangiz, xarajat bitta "
                     "xabar bilan yoziladi.</i>",
    "menu.openApp": "🚀 Ilovani ochish",
    "menu.quickAddBtn": "⚡ Tez qoʻshish",
    "menu.helpBtn": "❓ Yordam",
    "menu.lock": "🔒 Qulflash",
    "menu.page.dashboard": "📊 Bosh sahifa",
    "menu.page.overview": "🎯 Reja",
    "menu.page.months": "🗓 Oylar",
    "menu.page.transactions": "💸 Tranzaksiyalar",
    "menu.page.cards": "💳 Hamyonlar",
    "menu.page.finance": "🏦 Moliya",
    "menu.page.categories": "🏷 Kategoriyalar",
    "menu.page.settings": "⚙️ Sozlamalar",
    "menu.clearEverything": "🗑 Hammasini tozalash",
    "menu.lang.unchanged": "Bu til allaqachon tanlangan.",

    # ── Bosh sahifa ─────────────────────────────────────────────────────────
    "menu.dashboardError": "❌ Bosh sahifani yuklab boʻlmadi.",
    "menu.dashboard.title": "📊 <b>Bosh sahifa</b>",
    "menu.dashboard.spendable": "💵 Sarflash mumkin",
    "menu.dashboard.netWorth": "🏦 Sof boylik",
    # The note has to name the line two rows above it with the same words the label uses,
    # otherwise the reader has to guess that "sarflanadigan mablagʻ" meant "Sarflash mumkin".
    "menu.dashboard.netWorthNote": "<i>Sof boylik = sarflash mumkin boʻlgan pul + investitsiya va jamgʻarmalar</i>",
    "menu.dashboard.thisMonth": "<b>Shu oy</b>",
    "menu.dashboard.income": "📈 Daromad",
    "menu.dashboard.expenses": "📉 Xarajat",
    "menu.dashboard.net": "⚖️ Sof qoldiq",
    "menu.dashboard.allTime": "<i>Butun davr: {income} kirim · {expense} chiqim · "
                              "{count} ta tranzaksiya</i>",
    "menu.dashboard.empty": "<i>Hali hech narsa yozilmagan. Suhbatga <code>50000 tushlik</code> "
                            "deb yozing yoki quyidagi Tez qoʻshish tugmasini bosing.</i>",
    "menu.dashboard.byCategoryBtn": "🗂 Qayerga ketdi",
    "menu.dashboard.yearBtn": "📆 Shu yil",
    "menu.dashboard.catsTitle": "🗂 <b>Qayerga ketdi</b> · {month}",
    "menu.dashboard.catsSubExpense": "Kategoriyalar boʻyicha xarajat",
    "menu.dashboard.catsSubIncome": "Kategoriyalar boʻyicha daromad",
    "menu.dashboard.catsExpenseBtn": "📉 Xarajat",
    "menu.dashboard.catsIncomeBtn": "📈 Daromad",
    "menu.dashboard.catLine": "• {name} — {amount} ({pct})",
    "menu.dashboard.catsTotal": "Jami: <b>{amount}</b>",
    "menu.dashboard.catsMore": "<i>… va yana {n} ta kichikroq kategoriya</i>",
    "menu.dashboard.catsError": "❌ Taqsimotni yuklab boʻlmadi.",
    "menu.dashboard.yearTitle": "📆 <b>{year}</b> · oyma-oy · {currency}",
    "menu.dashboard.yearLine": "<code>{month}</code>  +{income}  −{expense}  =  <b>{net}</b>",
    "menu.dashboard.yearTotals": "Yil: +{income} · −{expense} · <b>{net}</b>",
    "menu.dashboard.yearEmpty": "<i>Bu yilga hali hech narsa yozilmagan.</i>",
    "menu.dashboard.yearError": "❌ Yilni yuklab boʻlmadi.",

    # ── Reja ────────────────────────────────────────────────────────────────
    "menu.overviewError": "❌ Rejani yuklab boʻlmadi.",
    "menu.overview.title": "🎯 <b>Reja</b>",
    "menu.overview.tierLine": "🏅 <b>{level}</b> · {scenario}",
    "menu.overview.tierLineBare": "🏅 <b>{level}</b>",
    "menu.overview.levelN": "Daraja {n}",
    "menu.overview.levelUnknown": "hali hisoblanmagan",
    "menu.overview.levelAbove": "eng yuqori darajadan yuqori",
    "menu.overview.stableIncome": "Barqaror daromad",
    "menu.overview.leftMoney": "Qolgan mablagʻ",
    "menu.overview.debtPayments": "Qarz toʻlovlari",
    "menu.overview.setIncomeWarning": "⚠️ <b>Sozlamalarda oylik daromadingizni kiriting</b> — daraja va taqsimot hali hisoblab boʻlmaydi.",
    "menu.overview.trackingStarts": "⏸ Taqsimot kuzatuvi <b>{month}</b> dan boshlanadi — shungacha hech narsa talab qilinmaydi.",
    # "obunalar", not "toʻlovlar": the Finance menu calls this entity Obunalar, and on this
    # very screen "Qarz toʻlovlari" is a different figure one line up.
    "menu.overview.subsPendingWarning": "🔒 <b>Avval majburiy obunalaringizni toʻlang</b> — ular qoplangach taqsimot ochiladi.",
    "menu.overview.subsPendingLine": "{name}: {paid} / {amount} toʻlandi",
    "menu.overview.allocationLocked": "🔒 Qulflangan — avval quyidagi bandlarni bajaring.",
    "menu.overview.baseNote": "<i>Foizlar qolgan balansdan hisoblanadi: {base} "
                              "(daromad − obunalar − qarz toʻlovlari)</i>",
    "menu.overview.bucketsHeader": "<b>Bu oy ajratiladi</b>",
    "menu.overview.bucketNoNeed": "{label}: <i>bu oy KERAK EMAS</i>{extra}",
    "menu.overview.bucketPaidExtra": " · toʻlandi {paid}",
    "menu.overview.bucketLine": "{label}: {minAmount} dan <b>{left}</b> qoldi (≥{minPercent})",
    "menu.overview.bucketLineDone": "{label}: ✅ {minAmount} qoplandi",
    "menu.overview.actionsHeader": "<b>Harakat kerak boʻlgan bandlar</b>",
    "menu.overview.actionProgress": "{text}\n   ↳ toʻlandi {paid} / {target}",
    "menu.overview.notesHeader": "<b>Izohlar</b>",
    "menu.overview.notesCount": "ℹ️ Izohlar: {n} — Tafsilotlarga qarang.",
    "menu.overview.detailsBtn": "📋 Tafsilotlar",
    "menu.overview.historyBtn": "📜 Tarix",
    "menu.overview.detailsTitle": "📋 <b>Reja tafsilotlari</b> · {month}",
    "menu.overview.mathHeader": "<b>Qolgan balans qanday hosil boʻladi</b>",
    "menu.overview.mandatorySubs": "Obunalar",
    "menu.overview.leftBalance": "Qolgan balans",
    "menu.overview.debtBank": "· bank kreditlari",
    "menu.overview.debtLoans": "· olingan qarzlar",
    "menu.overview.debtDebts": "· qarzlar",
    "menu.overview.debtRatio": "Qarz ulushi",
    "menu.overview.bucketsDetailHeader": "<b>Boʻlimlar</b>",
    "menu.overview.bucketDetailLine": "• {label}: maqsad {target} · toʻlandi {paid} · qoldi {left}",
    "menu.overview.bucketDetailNoNeed": "• {label}: bu oy talab qilinmaydi · toʻlandi {paid}",
    "menu.overview.bucketMarkedNote": "   ✱ shundan {amount} toʻlangan deb belgilangan — "
                                      "hamyondan pul chiqmagan",

    "menu.overview.scenario11": "qarzsiz",
    "menu.overview.scenario121Tight": "faqat bank krediti · tor (qarzdan keyin 5 mln UZS dan kam qoladi)",
    "menu.overview.scenario121Comfort": "faqat bank krediti · qulay (qarzdan keyin 5 mln UZS yoki koʻproq qoladi)",
    "menu.overview.scenario122Tight": "faqat qarzlar · tor (qarzdan keyin 5 mln UZS dan kam qoladi)",
    "menu.overview.scenario122Comfort": "faqat qarzlar · qulay (qarzdan keyin 5 mln UZS yoki koʻproq qoladi)",
    "menu.overview.scenario123": "bank krediti va qarzlar · belgilangan taqsimot",
    "menu.overview.scenario13": "ogʻir qarz · daromadning 70 foizidan koʻpi",
    "menu.overview.scenarioUnset": "bu daraja uchun yoʻriqnoma hali belgilanmagan",

    "menu.overview.actPayBank": "Bu oyning bank krediti toʻlovini toʻlang.",
    "menu.overview.actPayPersonal": "Bu oy shaxsiy qarzlaringizga {amount} toʻlang.",
    "menu.overview.actPayDebts34": "Bu oy qarzingizning kamida 34 foizini "
                                   "(taxminan {amount}) toʻlang.",
    "menu.overview.actSetAside": "Bu oy toʻlov rejangiz uchun {amount} ajratib qoʻying.",
    "menu.overview.noteTight": "Qarzdan keyin 5 mln UZS dan kam qoladi — ahvol yengillashguncha "
                               "ajratmalar kam boʻlib turadi.",
    "menu.overview.noteComfortable": "Qarzdan keyin 5 mln UZS yoki koʻproq qoladi — kattaroq "
                                     "ajratmalar qoʻllanadi.",
    "menu.overview.noteLoanAndDebt": "Ham kredit, ham qarz bor — bu darajada favqulodda "
                                     "jamgʻarma va aksiyalar oʻtkazib yuboriladi; eʼtiborni "
                                     "qarzga qarating.",
    "menu.overview.noteHeavyDebt": "Ogʻir qarz (daromadning 70 foizidan koʻpi): bu oy faqat 2% "
                                   "xayriya. Ahvol juda ogʻirlashsa, favqulodda jamgʻarmadan "
                                   "olishingiz mumkin.",
    "menu.overview.noteAboveCeiling": "Siz eng yuqori darajadan ham yuqoridasiz — buning uchun "
                                      "yoʻriqnoma hali belgilanmagan.",
    "menu.overview.noteLevelRulesUnset": "Daraja {level} uchun taqsimot qoidalarini oʻsha "
                                         "darajaga yetganingizda oʻzingiz belgilaysiz.",
    "menu.overview.noteSubLevelRulesUnset": "Daraja {subLevel} uchun taqsimot hali belgilanmagan "
                                            "— uni veb-ilovadagi qoidalar muharriridan "
                                            "belgilang.",
    "menu.overview.noteLoanPlanNotStarted": "{name}: {amount}/oy rejangiz {month} dan boshlanadi "
                                            "— bu oy hisobga olinmaydi. Ertaroq boshlash uchun "
                                            "kreditni tahrirlang.",
    "menu.overview.noteLoanChargeNotStarted": "{name}: {amount}/oy 34% toʻlovi {month} dan "
                                              "boshlanadi — bu oy hisobga olinmaydi. Ertaroq "
                                              "boshlash uchun kreditni tahrirlang.",
    "menu.overview.noteDebtChargeNotStarted": "{name}: {amount}/oy 34% toʻlovi {month} dan "
                                              "boshlanadi — bu oy hisobga olinmaydi. Ertaroq "
                                              "boshlash uchun qarzni tahrirlang.",

    # ── Boʻlim nomlari (months.* bilan bir xil soʻzlar) ──────────────────────
    "menu.bucket.donation": "Xayriya",
    "menu.bucket.emergency": "Favqulodda jamgʻarma",
    "menu.bucket.investments": "Investitsiyalar",
    "menu.bucket.stocks": "Aksiyalar",
    "menu.bucket.savings": "Jamgʻarma maqsadlari",

    "menu.bucket.btn": "🪣 {label}",
    "menu.bucket.title": "🪣 <b>{label}</b> · {month}",
    "menu.bucket.recommended": "Tavsiya: ≥{pct} — <b>{amount}</b>",
    "menu.bucket.notNeeded": "<i>Bu oy talab qilinmaydi.</i>",
    "menu.bucket.paid": "Toʻlangan: <b>{amount}</b>",
    "menu.bucket.markedPart": "<i>shundan toʻlangan deb belgilangani: {amount} — hamyondan pul "
                              "chiqmagan va oy yopilishida hisobga olinmaydi</i>",
    "menu.bucket.left": "Qoldi: <b>{amount}</b>",
    "menu.bucket.paymentsHeader": "<b>Bu raqam nimalardan tashkil topgan</b>",
    "menu.bucket.row": "• <code>{date}</code> · {amount}{label}",
    "menu.bucket.markedBadge": " · <i>belgilangan</i>",
    "menu.bucket.anonymous": "Anonim",
    "menu.bucket.noPayments": "<i>Bu oy bu boʻlimga hech narsa yozilmagan.</i>",
    "menu.bucket.more": "<i>… va yana {n} ta eskiroq yozuv</i>",
    "menu.bucket.marksBtn": "🏷 Toʻlangan deb belgilanganlar",
    "menu.bucket.error": "❌ Toʻlovlar roʻyxatini yuklab boʻlmadi.",

    # ── Taqsimot tarixi ─────────────────────────────────────────────────────
    "menu.ledger.title": "📜 <b>Taqsimot tarixi</b> · {month}",
    "menu.ledger.error": "❌ Taqsimot tarixini yuklab boʻlmadi.",
    "menu.ledger.startMonth": "<i>{month} dan beri kuzatilmoqda.</i>",
    "menu.ledger.due": "Bu oy talab qilinadi",
    "menu.ledger.carried": "Oldingi oylardan qolgan",
    "menu.ledger.carriedRange": "<i>{start} dan {end} gacha boʻlgan kamomad</i>",
    "menu.ledger.totalDue": "Jami qarzdorlik",
    "menu.ledger.bucketsHeader": "<b>Boʻlimlar boʻyicha</b>",
    "menu.ledger.bucketLine": "• {label}: {recommended} dan {paid} · <b>{outstanding}</b> qoldi",
    "menu.ledger.bucketClear": "• {label}: {recommended} dan {paid} · ✅",
    "menu.ledger.monthsHeader": "<b>Oyma-oy</b>",
    "menu.ledger.monthLine": "<code>{month}</code>  talab {due}  ·  toʻlandi {paid}",
    "menu.ledger.monthsMore": "<i>… va yana {n} ta oldingi oy</i>",

    # ── Sozlamalar ──────────────────────────────────────────────────────────
    "menu.settingsError": "❌ Sozlamalarni yuklab boʻlmadi.",
    "menu.settings.title": "⚙️ <b>Sozlamalar</b>",
    "menu.settings.currency": "Valyuta",
    "menu.settings.stableIncome": "Barqaror daromad",
    "menu.settings.trackingMonth": "Taqsimot kuzatuvi boshlanishi",
    "menu.settings.trackingBtn": "📅 Kuzatuv boshlanish oyi",
    "menu.settings.notSet": "kiritilmagan",
    "menu.settings.locked": "🔒 qulflangan",
    "menu.settings.hint": "<i>Rejadagi har bir raqam barqaror daromadingizdan hisoblanadi, u "
                          "kiritilmaguncha hech narsa yozib qoʻyilmaydi.</i>",

    "menu.income.title": "💰 <b>Oylik barqaror daromad</b>",
    "menu.income.current": "Hozir: <b>{amount}</b>",
    "menu.income.prompt": "Har oy ishonch bilan kutadigan summangizni yuboring. Darajangiz va "
                          "barcha taqsimot raqamlari shundan hisoblanadi.",
    "menu.income.examples": "<i>Masalan: 5000000 · 5 mln · 5 000 000</i>",
    "menu.income.saved": "✅ Barqaror daromad <b>{amount}</b> qilib belgilandi.",
    "menu.income.saveError": "❌ Daromadni saqlab boʻlmadi.",

    "menu.track.title": "📅 <b>Taqsimot kuzatuvining boshlanishi</b>",
    "menu.track.prompt": "Taqsimot qaysi oydan boshlab kuzatilishini YYYY-MM koʻrinishida "
                         "yuboring — masalan, {example}.",
    "menu.track.warning": "⚠️ <b>Buni faqat bir marta kiritish mumkin.</b> Saqlangandan keyin "
                          "uni na bot, na veb-ilova oʻzgartira oladi.",
    "menu.track.lockedNow": "U allaqachon <b>{month}</b> qilib belgilangan va endi "
                            "oʻzgartirilmaydi.",
    "menu.track.thisMonthBtn": "📅 Shu oy ({month})",
    "menu.track.badMonth": "Oyni YYYY-MM koʻrinishida yuboring, masalan {example}.",
    "menu.track.saved": "✅ Taqsimot kuzatuvi <b>{month}</b> dan boshlanadi.",
    "menu.track.saveError": "❌ Kuzatuv boshlanish oyini saqlab boʻlmadi.",

    # ── Xavfli hudud ────────────────────────────────────────────────────────
    "menu.reset.title": "⚠️ <b>Xavfli hudud — Hammasini tozalash</b>",
    "menu.reset.body": "Bu barcha maʼlumotlaringizni — tranzaksiyalar, hamyonlar, moliya "
                       "yozuvlari, kategoriyalar, sozlamalar va hisobingizni — butunlay "
                       "oʻchirib, ilovani noldan boshlaydi. Bu amalni <b>bekor qilib "
                       "boʻlmaydi</b>.",
    "menu.reset.botWarning": "⚠️ <b>Bu botning oʻz sozlamalarini ham tozalaydi.</b> Webhook va "
                             "veb-koʻrinish manzillari ham oʻsha sozlamalarda saqlanadi, "
                             "shuning uchun ular ham oʻchib ketadi. Bot keyingi qayta ishga "
                             "tushirilgunicha ishlab turadi — undan keyin esa manzillar joyiga "
                             "qaytmaguncha umuman ishga tushmaydi.",
    "menu.reset.prompt": "Tasdiqlash uchun <b>parolingizni</b> yozing yoki Bekor qilishni bosing.",
    "menu.reset.wrongPassword": "❌ Parol notoʻgʻri. Hech narsa oʻchirilmadi — qaytadan yozing "
                                "yoki Bekor qilishni bosing.",
    "menu.reset.done": "✅ Hammasi tozalandi. Ilova noldan qayta boshlandi.\n\n"
                       "Yangi hisob yaratish uchun quyidagini bosing.",
    "menu.reset.doneNote": "<i>Botning webhook sozlamalari ham oʻchib ketdi. Agar qayta ishga "
                           "tushirilgandan keyin bot javob bermay qolsa, veb-ilovaning "
                           "Developer sahifasida ikkala manzilni qaytadan kiriting.</i>",
}
