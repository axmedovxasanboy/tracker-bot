"""Finance: the nine record sections, their actions, their create wizards, and the marks.

`fin.*`

The list-line templates (`fin.debtLine` and friends) interpolate names that came from the
API, so every one of them is rendered through `t()` after the caller has passed the pieces
through `esc()`. `t()` substitutes in a single pass, so a creditor literally named
"{amount}" is printed, not re-expanded.

Two distinctions this dictionary exists to keep straight, both of them money the owner can
actually lose track of:

* **A mark is not a payment.** An "already paid" mark declares an obligation settled while
  moving no money at all — there is no transaction behind it. In Uzbek that is
  `toʻlangan deb belgilangan`, badge `Belgilangan`, exactly as the web app says it. The money
  genuinely set aside into a bucket is `Ajratilgan`, a different word for a different thing.
  Never let one of the two do the other's job: `menu.bucket.markedPart` and
  `months.taggedTotal` already draw the same line, and the owner reads all three screens.

* **Deleting a record is not always harmless.** `fin.deleteReversesMoney` covers donations,
  investments, savings goals and emergency contributions, where the mirror transaction dies
  with the row (`FinanceService.deleteDonation` / `deleteInvestment`, `EmergencyService.delete`)
  and the cash lands back in the wallet. Donations used to keep their expense standing and had
  their own warning saying so; since 2026-09-17 they reverse like the rest, and that warning
  is gone.
"""

EN: dict[str, str] = {
    # Section menu + list views
    "fin.menuTitle": "🏦 <b>Finance</b>\nPick a section:",
    "fin.menu.debts": "📕 Debts",
    "fin.menu.loanGiven": "📗 Loans given",
    "fin.menu.loanTaken": "📘 Loans taken",
    "fin.menu.bankLoan": "🏛 Bank loans",
    "fin.menu.subscriptions": "🔁 Subscriptions",
    "fin.menu.donations": "🎁 Donations",
    "fin.menu.investments": "📈 Investments",
    "fin.menu.savingsGoals": "🎯 Savings goals",
    "fin.menu.emergency": "🛟 Emergency fund",
    # The same label menu.py's bucket screen already uses for the same list, so both doors
    # into `fmarks` are named the same thing.
    "fin.menu.marks": "🏷 Marked as paid",
    "fin.backToFinance": "⬅️ Finance",
    # Sits to the left of "⬅️ Finance" on almost every screen, so it stays as short as it is.
    "fin.backToSection": "⬅️ List",
    "fin.backToRecord": "⬅️ Record",
    "fin.sectionLoadError": "❌ Couldn't load that section.",
    "fin.debtsTitle": "📕 <b>Debts</b> (you owe)\n",
    "fin.loansGivenTitle": "📗 <b>Loans given</b> (owed to you)\n",
    "fin.loansTakenTitle": "📘 <b>Loans taken</b> (you borrowed)\n",
    "fin.bankLoansTitle": "🏛 <b>Bank loans</b>\n",
    "fin.subscriptionsTitle": "🔁 <b>Subscriptions</b>\n",
    "fin.donationsTitle": "🎁 <b>Donations</b>\n",
    "fin.investmentsTitle": "📈 <b>Investments</b>\n",
    "fin.savingsTitle": "🎯 <b>Savings goals</b> · optional, apart from the 4 buckets\n",
    "fin.emergencyTitle": "🛟 <b>Emergency fund</b>\n",
    "fin.noSavingsGoalsYet": "No savings goals yet. Tap ➕ Add to start one.",
    "fin.suffixDue": " · due {date}",
    "fin.suffixPaysFrom": " · pays from {month}",
    "fin.suffixExpect": " · expect {date}",
    "fin.suffixPaused": " · paused",
    "fin.suffixDay": " · day {day}",
    "fin.suffixMonthly": " · {amount}/mo",
    "fin.suffixEnds": " · ends {date}",
    "fin.suffixOpening": " · <i>opening</i>",
    "fin.suffixTarget": " · target {amount}",
    "fin.suffixProgress": " · {pct}",
    "fin.suffixNote": " · {note}",
    # Read off the Plan's own pendingSubscriptions, so this says the same thing the Plan says.
    "fin.suffixPaidThisMonth": " · ✅ paid this month",
    "fin.suffixPartlyPaid": " · {paid} paid so far",
    # …and when the Plan is dormant it sends an EMPTY pendingSubscriptions, which is
    # indistinguishable from "everything is paid". The bot reads both of these as unknown
    # rather than as settled, and says which one it hit — otherwise the screen silently stops
    # marking anything paid and looks exactly like a month where nothing is.
    "fin.subsUnknownIncome": "<i>ℹ️ Until your stable monthly income is set, the Plan can't say "
                             "what has been paid this month — so every subscription still "
                             "offers Pay.</i>",
    "fin.subsUnknownTracking": "<i>ℹ️ Allocation tracking starts {month}, so the Plan isn't "
                               "working out what has been paid this month yet — every "
                               "subscription still offers Pay.</i>",
    "fin.debtLine": "{name}: {remaining} left / {total}{due}",
    "fin.loanTakenLine": "{name}: {remaining} left / {total}{due}{start}",
    "fin.loanGivenLine": "{name}: {pending} pending / {total}{exp}",
    "fin.monthlyLine": "{name}: {amount}{due}{active}",
    "fin.bankLoanLine": "{bank} — {loan}: {total}{monthly}{end}",
    "fin.donationLine": "{date} · {who}: {amount}",
    "fin.investmentLine": "{name} ({type}): {amount}{tag}",
    "fin.savingsLine": "{name}: {value}{target}{progress}",
    "fin.emergencyLine": "{date}: {amount}{note}",
    "fin.showingCount": "<i>Showing {shown} of {total}.</i>",
    "fin.repayBtn": "💸 Repay {name}",
    "fin.returnedByBtn": "✅ Returned by {name}",
    "fin.payBtn": "💸 Pay {name}",
    "fin.payInstallmentBtn": "💸 Installment · {name}",
    "fin.addToBtn": "📈 Add to {name}",
    "fin.addToGoalBtn": "💰 Add to {name}",
    "fin.valueBtn": "📈 Value",
    # The gear shares its row with the money verb, so it gives that button all the width it
    # can; on a row of its own the record's name goes on it.
    "fin.manageBtn": "⚙️",
    "fin.manageNamedBtn": "⚙️ {name}",
    # One record: the detail screen
    "fin.detailPaidTotal": "Payments made: {count} · total <b>{total}</b>",
    "fin.detailNextDue": "Next due: {date}",
    "fin.detailBroker": "Broker: {broker}",
    "fin.detailSince": "Since {date}",
    "fin.detailDescription": "📝 {text}",
    # Payment history
    "fin.historyBtn": "🧾 History",
    "fin.historyTitle": "🧾 <b>History</b> · {name}",
    "fin.historyEmpty": "Nothing recorded against this yet.",
    "fin.historyLine": "{date}: {amount} · {source}",
    "fin.historyMore": "<i>Showing the latest {shown} of {total}.</i>",
    # Pause / resume a subscription. Pausing is the way out of a chore that never ends: while
    # an active subscription is unpaid the Plan withholds the whole month's allocation.
    "fin.pauseBtn": "⏸ Pause",
    "fin.resumeBtn": "▶️ Resume",
    "fin.paused": "⏸ <b>{name}</b> is paused.\nIt no longer counts as a monthly payment and the "
                  "Plan stops waiting for it. Nothing already recorded changes.",
    "fin.resumed": "▶️ <b>{name}</b> is active again.\nIt counts as a monthly payment from this "
                   "month on.",
    # Delete a record
    "fin.deleteConfirm": "🗑 <b>Delete this record?</b>\n\n{line}",
    # Donations, investments, savings goals, emergency contributions: the mirror transaction is
    # deleted with the row, and wallet balances are summed from transactions.
    "fin.deleteReversesMoney": "⚠️ The transaction behind it is deleted too: <b>the money goes "
                               "back into that wallet</b> and this month's set-aside total drops "
                               "by the same amount.",
    "fin.deleted": "🗑 Record deleted.",
    # Edit one field. Every PUT is a full replace, so the bot rebuilds the whole record and
    # overwrites exactly the field named here.
    "fin.editTitle": "✏️ <b>Edit {name}</b>\nWhich field?",
    "fin.editPrompt": "✏️ <b>{label}</b>\nNow: {current}\n\nSend the new value:",
    "fin.editPromptAmount": "✏️ <b>{label}</b>\nNow: {current}\n\nSend the new amount in {currency}:",
    "fin.editPromptInt": "✏️ <b>{label}</b>\nNow: {current}\n\nSend a whole number from {min} to {max}:",
    "fin.editPromptDate": "✏️ <b>{label}</b>\nNow: {current}\n\nSend a date as YYYY-MM-DD, or tap Today:",
    "fin.editPromptChoice": "✏️ <b>{label}</b>\nNow: {current}\n\nPick the new one:",
    "fin.editClearBtn": "🚫 Leave empty",
    "fin.editConfirm": "Change <b>{label}</b>?\n\n{old} → <b>{new}</b>",
    "fin.edited": "✅ {label} updated.",
    "fin.editWholeNumber": "Send a whole number.",
    "fin.editRange": "Send a whole number from {min} to {max}.",
    "fin.editTapButton": "Tap one of the buttons above to pick it.",
    "fin.dateFormat": "Send the date as YYYY-MM-DD (e.g. {example}).",
    # Action conversation (repay / mark-returned / pay / contribute / bank installment)
    "fin.verbRepayDebt": "Repay debt to",
    "fin.verbRepayLoan": "Repay loan from",
    "fin.verbMarkReturned": "Mark returned by",
    "fin.verbPay": "Pay",
    "fin.verbContribute": "Contribute to",
    "fin.verbPayInstallment": "Pay installment for",
    "fin.recordGone": "That record no longer exists.",
    "fin.sendAmountPrompt": "{verb} <b>{name}</b>\nSend the amount in {currency}:",
    "fin.useSuggested": "Use {amount}",
    # Every button in the action flow carries its record's id, so a tap on an older message
    # cannot spend this record's balance on that one.
    "fin.staleButton": "That button belongs to a different record. Open that record again to "
                       "continue there.",
    # A tap that matched nothing at all: the flow's state died with a restart, or the tap was
    # queued while the container was down. Without an answer Telegram spins the button for
    # about fifteen seconds and then clears it, leaving no way to tell a lost repayment from a
    # recorded one — so the reassurance about what was NOT written is the point of the body.
    "fin.flowExpired": "That screen has expired.",
    "fin.flowExpiredBody": "⌛️ <b>That screen is no longer live.</b>\nThe bot restarted, or it "
                           "sat open too long. <b>Nothing was recorded.</b> Open the record "
                           "again to carry on.",
    "fin.alreadyPaidBtn": "✅ Already paid",
    "fin.markAlreadyPaid": "Mark <b>{name}</b> as already paid.\nSend the amount in {currency} — "
                           "<i>no transaction will be recorded</i>:",
    "fin.payFrom": "Pay from ({currency}):",
    # mark-returned books an INCOME: the money is arriving, so the wallet question and the
    # confirmation both have to point the other way.
    "fin.receiveInto": "Received into ({currency}):",
    "fin.noneRecordOnly": "🚫 None — just record (no wallet)",
    # A wallet list that failed to load is NOT an empty wallet list. Offering Cash alone reads
    # as "you have no cards", and the card payment then lands on the cash pot — wrong on two
    # balances, and not noticed until month-close.
    "fin.walletsLoadError": "❌ <b>Couldn't load your wallets.</b>\nYour cards would be missing "
                            "from the list, and a card payment booked against cash is wrong on "
                            "two balances. Nothing has been recorded — try again.",
    # The date step. The month a figure lands in is what the whole envelope model turns on.
    "fin.datePrompt": "📅 <b>When did this happen?</b>\nThis is the month it will count in. Tap a "
                      "button, or send a date as YYYY-MM-DD (e.g. {example}):",
    "fin.markMonthPrompt": "📅 <b>Which month is it paid for?</b>\nA mark is filed by month, and "
                           "the date you send picks it. Tap a button, or send a date as "
                           "YYYY-MM-DD (e.g. {example}):",
    "fin.yesterdayBtn": "📅 Yesterday",
    "fin.confirmHeader": "Confirm:\n\n{name}\nAmount: <b>{amount}</b>\n",
    "fin.fromNone": "From: None — <i>record only, no money moved</i>",
    "fin.fromSource": "From: {source}",
    "fin.intoSource": "Into: {source}",
    "fin.onDate": "\nDate: {date}",
    "fin.markConfirmHeader": "Mark as <b>already paid</b> (no transaction, no money moved):\n\n"
                             "{name}\nAmount: <b>{amount}</b>",
    "fin.markMonthLine": "\nCounts as paid for: <b>{month}</b>",
    "fin.markedPaid": "✅ Marked already paid: <b>{amount}</b> · {name}.",
    "fin.recorded": "✅ Recorded: <b>{amount}</b> · {name}.",
    # The bank installment is a BANK_LOAN_PAYMENT transaction, so this is the description it
    # is filed under — it shows up in the Transactions list, not in a message.
    "fin.bankInstallmentDesc": "Installment: {bank} — {loan}",
    # "Already paid" marks: the list and the undo. A mark is the only paid figure with no
    # transaction behind it, which is why it needs a screen of its own.
    "fin.marksTitle": "🏷 <b>Marked as paid</b> · {month}\n",
    "fin.marksEmpty": "Nothing marked in this month.",
    "fin.marksNote": "<i>Counted as paid with no transaction behind it — no money left a wallet.</i>",
    "fin.markLine": "{kind} · {name}: {amount}{note}",
    "fin.markKind.subscription": "Subscription",
    "fin.markKind.personalLoan": "Loan taken",
    "fin.markKind.debt": "Debt",
    "fin.markKind.bank": "Bank loan",
    # "Set aside", never "marked": this row is a bucket contribution declared without a
    # transaction, and the two words name two different things in this product.
    "fin.markKind.bucket": "Set aside",
    "fin.markBucket.donation": "Donation",
    "fin.markBucket.emergency": "Emergency fund",
    "fin.markBucket.investments": "Investments",
    "fin.markBucket.stocks": "Stocks",
    "fin.markDelBtn": "🗑 {name}",
    "fin.markDelConfirm": "🗑 <b>Remove this mark?</b>\n\nIt stops counting as paid this month, so "
                          "the Plan will ask for it again. No transaction is touched — a mark "
                          "never moved any money. For a debt or a loan taken, the amount goes "
                          "back onto the balance you still owe.",
    "fin.markDeleted": "🗑 Mark removed. It no longer counts as paid.",
    "fin.markMonthClosed": "That month is closed, so its marks are locked along with everything "
                           "else in it.",
    # Create wizard specs
    "fin.investmentType.realEstate": "Real estate",
    "fin.investmentType.bonds": "Bonds",
    "fin.investmentType.mutualFund": "Mutual fund",
    "fin.investmentType.gold": "Gold",
    "fin.investmentType.other": "Other",
    "fin.field.totalAmount": "Total amount",
    "fin.field.description": "Description",
    "fin.field.name": "Name",
    "fin.field.amount": "Amount",
    "fin.field.date": "Date",
    "fin.field.type": "Type",
    "fin.field.dueDate": "Due date",
    "fin.field.paymentStartMonth": "Payments start month",
    "fin.field.plannedMonthly": "Planned monthly payment",
    # Asked before the wizard starts, for the three records whose creation books a real
    # transaction — without it the whole amount is charged to cash whatever was really used.
    "fin.create.sourceQ": "Which wallet does this money come out of?",
    "fin.create.debt.title": "New debt",
    "fin.create.debt.creditorName": "Creditor (who you owe)",
    "fin.create.debt.borrowedDate": "Borrowed date",
    "fin.create.debt.success": "Debt created.",
    "fin.create.loanGiven.title": "New loan given",
    "fin.create.loanGiven.debtorName": "Debtor (who owes you)",
    "fin.create.loanGiven.amountLent": "Amount lent",
    "fin.create.loanGiven.lentDate": "Lent date",
    "fin.create.loanGiven.expectedReturnDate": "Expected return date",
    "fin.create.loanGiven.success": "Loan given created.",
    "fin.create.loanTaken.title": "New loan taken",
    "fin.create.loanTaken.lenderName": "Lender (who lent you)",
    "fin.create.loanTaken.borrowedDate": "Borrowed date",
    "fin.create.loanTaken.success": "Loan taken created.",
    "fin.create.bankLoan.title": "New bank loan",
    "fin.create.bankLoan.bankName": "Bank name",
    "fin.create.bankLoan.loanNameType": "Loan name / type",
    "fin.create.bankLoan.monthlyPayment": "Monthly payment",
    "fin.create.bankLoan.takenDate": "Taken date",
    "fin.create.bankLoan.endDate": "End date",
    "fin.create.bankLoan.success": "Bank loan created.",
    "fin.create.monthly.title": "New subscription",
    "fin.create.monthly.monthlyAmount": "Monthly amount",
    "fin.create.monthly.dueDay": "Due day of month",
    "fin.create.monthly.success": "Subscription created.",
    "fin.create.donation.title": "New donation",
    "fin.create.donation.recipient": "Recipient",
    "fin.create.donation.success": "Donation created.",
    "fin.create.investment.title": "New investment",
    "fin.create.investment.amountInvested": "Amount invested",
    "fin.create.investment.openingBalanceQ": "Do you already own this? An opening balance is tracked for net "
                                            "worth only — no money leaves your wallet and it isn't counted "
                                            "in this month's allocation.",
    "fin.create.investment.openingYes": "✅ I already own it (opening balance)",
    "fin.create.investment.openingNo": "🆕 New purchase",
    "fin.create.investment.broker": "Broker / platform",
    "fin.create.investment.purchaseDate": "Purchase date",
    "fin.create.investment.success": "Investment created.",
    "fin.create.goal.title": "New savings goal",
    "fin.create.goal.goalName": "Goal name (e.g. iPhone, Home)",
    "fin.create.goal.amountSaved": "Amount saved so far",
    "fin.create.goal.openingQ": "Is that amount already saved OUTSIDE your tracked wallets (a jar, another "
                                "account)? If so it's recorded for goal progress only — no cash is debited "
                                "and it isn't counted in this month's allocation.",
    "fin.create.goal.openingYes": "✅ Already saved elsewhere (record only)",
    "fin.create.goal.openingNo": "💵 Taking it from my cash now",
    "fin.create.goal.targetAmount": "Target amount",
    "fin.create.goal.currentValue": "Current value (if grown)",
    "fin.create.goal.startDate": "Start date",
    "fin.create.goal.notes": "Notes",
    "fin.create.goal.success": "Savings goal created.",
    "fin.create.emergency.title": "New emergency fund contribution",
    "fin.create.emergency.success": "Added to your emergency fund.",
    # Savings goal value update
    "fin.goalGone": "That goal no longer exists.",
    "fin.updateValueHeader": "📈 Update value of <b>{name}</b>\nCurrent: {current}\n\n"
                             "Send the new current value in {currency}:",
    "fin.updatedValue": "✅ Updated <b>{name}</b> value to {value}.",
}

UZ: dict[str, str] = {
    "fin.menuTitle": "🏦 <b>Moliya</b>\nBoʻlimni tanlang:",
    "fin.menu.debts": "📕 Qarzlar",
    "fin.menu.loanGiven": "📗 Berilgan qarzlar",
    "fin.menu.loanTaken": "📘 Olingan qarzlar",
    "fin.menu.bankLoan": "🏛 Bank kreditlari",
    "fin.menu.subscriptions": "🔁 Obunalar",
    "fin.menu.donations": "🎁 Xayriyalar",
    "fin.menu.investments": "📈 Investitsiyalar",
    "fin.menu.savingsGoals": "🎯 Jamgʻarma maqsadlari",
    "fin.menu.emergency": "🛟 Favqulodda jamgʻarma",
    # Aynan `menu.bucket.marksBtn` dagi nom: ikkala tugma ham shu roʻyxatni ochadi.
    "fin.menu.marks": "🏷 Toʻlangan deb belgilanganlar",
    "fin.backToFinance": "⬅️ Moliya",
    "fin.backToSection": "⬅️ Roʻyxat",
    "fin.backToRecord": "⬅️ Yozuv",
    "fin.sectionLoadError": "❌ Bu boʻlimni yuklab boʻlmadi.",
    "fin.debtsTitle": "📕 <b>Qarzlar</b> (sizning qarzingiz)\n",
    "fin.loansGivenTitle": "📗 <b>Berilgan qarzlar</b> (sizga qaytariladigan)\n",
    "fin.loansTakenTitle": "📘 <b>Olingan qarzlar</b> (siz olgan)\n",
    "fin.bankLoansTitle": "🏛 <b>Bank kreditlari</b>\n",
    "fin.subscriptionsTitle": "🔁 <b>Obunalar</b>\n",
    "fin.donationsTitle": "🎁 <b>Xayriyalar</b>\n",
    "fin.investmentsTitle": "📈 <b>Investitsiyalar</b>\n",
    "fin.savingsTitle": "🎯 <b>Jamgʻarma maqsadlari</b> · ixtiyoriy, 4 ta asosiy taqsimotdan tashqari\n",
    "fin.emergencyTitle": "🛟 <b>Favqulodda jamgʻarma</b>\n",
    "fin.noSavingsGoalsYet": "Hozircha jamgʻarma maqsadlari yoʻq. Boshlash uchun ➕ Qoʻshish tugmasini bosing.",
    "fin.suffixDue": " · muddati {date}",
    "fin.suffixPaysFrom": " · {month} dan toʻlanadi",
    "fin.suffixExpect": " · kutilmoqda {date}",
    "fin.suffixPaused": " · toʻxtatilgan",
    "fin.suffixDay": " · {day}-kun",
    "fin.suffixMonthly": " · oyiga {amount}",
    "fin.suffixEnds": " · tugaydi {date}",
    "fin.suffixOpening": " · <i>boshlangʻich</i>",
    "fin.suffixTarget": " · maqsad {amount}",
    "fin.suffixProgress": " · {pct}",
    "fin.suffixNote": " · {note}",
    # "yopilgan" emas — u yopilgan oyning soʻzi (`months.closed`), obunaniki emas.
    "fin.suffixPaidThisMonth": " · ✅ bu oy toʻlangan",
    "fin.suffixPartlyPaid": " · shu paytgacha {paid} toʻlangan",
    # Reja uxlab turganda boʻsh roʻyxat qaytaradi — bu "hammasi toʻlangan" dan farq qilmaydi.
    # Shuning uchun bot bunday holatni "toʻlangan" emas, "nomaʼlum" deb oʻqiydi va sababini
    # aytadi.
    "fin.subsUnknownIncome": "<i>ℹ️ Barqaror oylik daromadingiz kiritilmaguncha Reja bu oy nima "
                             "toʻlanganini ayta olmaydi — shuning uchun har bir obunada Toʻlash "
                             "tugmasi qoladi.</i>",
    "fin.subsUnknownTracking": "<i>ℹ️ Taqsimot hisobi {month} dan boshlanadi, shuning uchun Reja "
                               "bu oy nima toʻlanganini hali hisoblamaydi — har bir obunada "
                               "Toʻlash tugmasi qoladi.</i>",
    "fin.debtLine": "{name}: {remaining} qoldi / {total}{due}",
    "fin.loanTakenLine": "{name}: {remaining} qoldi / {total}{due}{start}",
    "fin.loanGivenLine": "{name}: {pending} kutilmoqda / {total}{exp}",
    "fin.monthlyLine": "{name}: {amount}{due}{active}",
    "fin.bankLoanLine": "{bank} — {loan}: {total}{monthly}{end}",
    "fin.donationLine": "{date} · {who}: {amount}",
    "fin.investmentLine": "{name} ({type}): {amount}{tag}",
    "fin.savingsLine": "{name}: {value}{target}{progress}",
    "fin.emergencyLine": "{date}: {amount}{note}",
    "fin.showingCount": "<i>{total} tadan {shown} tasi koʻrsatilmoqda.</i>",
    "fin.repayBtn": "💸 {name}ga toʻlash",
    "fin.returnedByBtn": "✅ {name} qaytardi",
    "fin.payBtn": "💸 {name}ni toʻlash",
    "fin.payInstallmentBtn": "💸 {name} toʻlovi",
    "fin.addToBtn": "📈 {name}ga qoʻshish",
    "fin.addToGoalBtn": "💰 {name}ga qoʻshish",
    "fin.valueBtn": "📈 Qiymat",
    "fin.manageBtn": "⚙️",
    "fin.manageNamedBtn": "⚙️ {name}",
    "fin.detailPaidTotal": "Toʻlovlar: {count} ta · jami <b>{total}</b>",
    "fin.detailNextDue": "Keyingi toʻlov: {date}",
    "fin.detailBroker": "Broker: {broker}",
    "fin.detailSince": "{date} dan beri",
    "fin.detailDescription": "📝 {text}",
    "fin.historyBtn": "🧾 Tarix",
    "fin.historyTitle": "🧾 <b>Tarix</b> · {name}",
    "fin.historyEmpty": "Bunga hali hech narsa yozilmagan.",
    "fin.historyLine": "{date}: {amount} · {source}",
    "fin.historyMore": "<i>{total} tadan eng soʻnggi {shown} tasi koʻrsatilmoqda.</i>",
    "fin.pauseBtn": "⏸ Toʻxtatish",
    "fin.resumeBtn": "▶️ Davom ettirish",
    "fin.paused": "⏸ <b>{name}</b> toʻxtatildi.\nEndi u oylik toʻlov sifatida hisoblanmaydi va "
                  "Reja uni kutmaydi. Avval yozilganlar oʻzgarmaydi.",
    "fin.resumed": "▶️ <b>{name}</b> yana faol.\nShu oydan boshlab oylik toʻlov sifatida "
                   "hisoblanadi.",
    "fin.deleteConfirm": "🗑 <b>Bu yozuv oʻchirilsinmi?</b>\n\n{line}",
    "fin.deleteReversesMoney": "⚠️ Ortidagi tranzaksiya ham oʻchadi: <b>pul oʻsha hamyoningizga "
                               "qaytadi</b> va shu oydagi ajratilgan jami shuncha kamayadi.",
    "fin.deleted": "🗑 Yozuv oʻchirildi.",
    "fin.editTitle": "✏️ <b>{name}</b> — tahrirlash\nQaysi maydon?",
    "fin.editPrompt": "✏️ <b>{label}</b>\nHozir: {current}\n\nYangi qiymatni yuboring:",
    "fin.editPromptAmount": "✏️ <b>{label}</b>\nHozir: {current}\n\nYangi summani {currency} da yuboring:",
    "fin.editPromptInt": "✏️ <b>{label}</b>\nHozir: {current}\n\n{min} dan {max} gacha butun son yuboring:",
    "fin.editPromptDate": "✏️ <b>{label}</b>\nHozir: {current}\n\nSanani YYYY-MM-DD koʻrinishida "
                          "yuboring yoki Bugun tugmasini bosing:",
    "fin.editPromptChoice": "✏️ <b>{label}</b>\nHozir: {current}\n\nYangisini tanlang:",
    "fin.editClearBtn": "🚫 Boʻsh qoldirish",
    "fin.editConfirm": "<b>{label}</b> oʻzgartirilsinmi?\n\n{old} → <b>{new}</b>",
    "fin.edited": "✅ {label} yangilandi.",
    "fin.editWholeNumber": "Butun son yuboring.",
    "fin.editRange": "{min} dan {max} gacha butun son yuboring.",
    "fin.editTapButton": "Tanlash uchun yuqoridagi tugmalardan birini bosing.",
    "fin.dateFormat": "Sanani YYYY-MM-DD koʻrinishida yuboring (masalan, {example}).",
    "fin.verbRepayDebt": "Qarzni toʻlash —",
    "fin.verbRepayLoan": "Qarzni qaytarish —",
    "fin.verbMarkReturned": "Qaytarilganini belgilash —",
    "fin.verbPay": "Toʻlash —",
    "fin.verbContribute": "Hissa qoʻshish —",
    "fin.verbPayInstallment": "Oylik toʻlov —",
    "fin.recordGone": "Bu yozuv endi mavjud emas.",
    "fin.sendAmountPrompt": "{verb} <b>{name}</b>\nSummani {currency} da yuboring:",
    "fin.useSuggested": "{amount} dan foydalanish",
    "fin.staleButton": "Bu tugma boshqa yozuvga tegishli. Davom etish uchun oʻsha yozuvni "
                       "qaytadan oching.",
    "fin.flowExpired": "Bu ekran eskirgan.",
    "fin.flowExpiredBody": "⌛️ <b>Bu ekran endi faol emas.</b>\nBot qayta ishga tushgan yoki "
                           "ekran juda uzoq ochiq qolgan. <b>Hech narsa yozilmadi.</b> Davom "
                           "etish uchun yozuvni qaytadan oching.",
    "fin.alreadyPaidBtn": "✅ Allaqachon toʻlangan",
    "fin.markAlreadyPaid": "<b>{name}</b> ni toʻlangan deb belgilash.\nSummani {currency} da yuboring — "
                           "<i>tranzaksiya yozilmaydi</i>:",
    "fin.payFrom": "Qayerdan toʻlanadi ({currency}):",
    "fin.receiveInto": "Qayerga tushdi ({currency}):",
    "fin.noneRecordOnly": "🚫 Hech biri — faqat qayd etish (hamyonsiz)",
    # Yuklanmagan hamyon roʻyxati — boʻsh roʻyxat emas. Faqat "Naqd pul" ni koʻrsatish
    # "kartangiz yoʻq" degan maʼnoni beradi, karta toʻlovi esa naqd pulga yozilib ketadi.
    "fin.walletsLoadError": "❌ <b>Hamyonlaringizni yuklab boʻlmadi.</b>\nRoʻyxatda "
                            "kartalaringiz koʻrinmaydi, karta toʻlovini naqd pul deb yozib "
                            "qoʻyish esa ikkita hamyon balansini buzadi. Hech narsa yozilmadi — "
                            "qaytadan urinib koʻring.",
    "fin.datePrompt": "📅 <b>Bu qachon boʻlgan?</b>\nQaysi oyga hisoblanishi shunga bogʻliq. "
                      "Tugmani bosing yoki sanani YYYY-MM-DD koʻrinishida yuboring "
                      "(masalan, {example}):",
    "fin.markMonthPrompt": "📅 <b>Qaysi oy uchun toʻlangan?</b>\nBelgi oy boʻyicha saqlanadi, "
                           "yuborgan sanangiz oʻsha oyni tanlaydi. Tugmani bosing yoki sanani "
                           "YYYY-MM-DD koʻrinishida yuboring (masalan, {example}):",
    "fin.yesterdayBtn": "📅 Kecha",
    "fin.confirmHeader": "Tasdiqlang:\n\n{name}\nSumma: <b>{amount}</b>\n",
    "fin.fromNone": "Manba: Yoʻq — <i>faqat qayd, pul harakatlanmadi</i>",
    "fin.fromSource": "Manba: {source}",
    "fin.intoSource": "Qayerga: {source}",
    "fin.onDate": "\nSana: {date}",
    "fin.markConfirmHeader": "<b>Allaqachon toʻlangan</b> deb belgilash (tranzaksiya yoʻq, pul harakatlanmaydi):\n\n"
                             "{name}\nSumma: <b>{amount}</b>",
    "fin.markMonthLine": "\nQaysi oy uchun: <b>{month}</b>",
    "fin.markedPaid": "✅ Toʻlangan deb belgilandi: <b>{amount}</b> · {name}.",
    "fin.recorded": "✅ Qayd etildi: <b>{amount}</b> · {name}.",
    "fin.bankInstallmentDesc": "Oylik toʻlov: {bank} — {loan}",
    "fin.marksTitle": "🏷 <b>Toʻlangan deb belgilangan</b> · {month}\n",
    "fin.marksEmpty": "Bu oyda belgilangan hech narsa yoʻq.",
    "fin.marksNote": "<i>Tranzaksiyasiz toʻlangan deb hisoblangan — hamyondan pul chiqmagan.</i>",
    "fin.markLine": "{kind} · {name}: {amount}{note}",
    "fin.markKind.subscription": "Obuna",
    "fin.markKind.personalLoan": "Olingan qarz",
    "fin.markKind.debt": "Qarz",
    "fin.markKind.bank": "Bank krediti",
    # "Belgilangan" emas: bu qator tranzaksiyasiz eʼlon qilingan taqsimot ulushi, veb-ilovada
    # ham u "Ajratilgan" deb ataladi.
    "fin.markKind.bucket": "Ajratilgan",
    "fin.markBucket.donation": "Xayriya",
    "fin.markBucket.emergency": "Favqulodda jamgʻarma",
    "fin.markBucket.investments": "Investitsiyalar",
    "fin.markBucket.stocks": "Aksiyalar",
    "fin.markDelBtn": "🗑 {name}",
    "fin.markDelConfirm": "🗑 <b>Bu belgi olib tashlansinmi?</b>\n\nU bu oyda toʻlangan deb "
                          "hisoblanmay qoladi va Reja uni yana soʻraydi. Hech qanday "
                          "tranzaksiyaga tegilmaydi — belgi hech qachon pul koʻchirmagan. "
                          "Qarz yoki olingan qarz boʻlsa, summa qolgan qarzingizga qaytariladi.",
    "fin.markDeleted": "🗑 Belgi olib tashlandi. Endi u toʻlangan deb hisoblanmaydi.",
    "fin.markMonthClosed": "Oʻsha oy yopilgan, shuning uchun undagi belgilar ham qolgan hamma "
                           "narsa bilan birga qulflangan.",
    "fin.investmentType.realEstate": "Koʻchmas mulk",
    "fin.investmentType.bonds": "Obligatsiyalar",
    "fin.investmentType.mutualFund": "Investitsiya fondi",
    "fin.investmentType.gold": "Oltin",
    "fin.investmentType.other": "Boshqa",
    "fin.field.totalAmount": "Umumiy summa",
    "fin.field.description": "Tavsif",
    "fin.field.name": "Nomi",
    "fin.field.amount": "Summa",
    "fin.field.date": "Sana",
    "fin.field.type": "Turi",
    "fin.field.dueDate": "Muddati",
    "fin.field.paymentStartMonth": "Toʻlovlar boshlanadigan oy",
    "fin.field.plannedMonthly": "Rejalashtirilgan oylik toʻlov",
    "fin.create.sourceQ": "Bu pul qaysi hamyondan chiqadi?",
    "fin.create.debt.title": "Yangi qarz",
    "fin.create.debt.creditorName": "Kreditor (kimga qarzdorsiz)",
    "fin.create.debt.borrowedDate": "Olingan sana",
    "fin.create.debt.success": "Qarz yaratildi.",
    "fin.create.loanGiven.title": "Yangi berilgan qarz",
    "fin.create.loanGiven.debtorName": "Qarzdor (sizga qarzdor)",
    "fin.create.loanGiven.amountLent": "Berilgan summa",
    "fin.create.loanGiven.lentDate": "Berilgan sana",
    "fin.create.loanGiven.expectedReturnDate": "Kutilayotgan qaytarish sanasi",
    "fin.create.loanGiven.success": "Berilgan qarz yaratildi.",
    "fin.create.loanTaken.title": "Yangi olingan qarz",
    "fin.create.loanTaken.lenderName": "Qarz beruvchi",
    "fin.create.loanTaken.borrowedDate": "Olingan sana",
    "fin.create.loanTaken.success": "Olingan qarz yaratildi.",
    "fin.create.bankLoan.title": "Yangi bank krediti",
    "fin.create.bankLoan.bankName": "Bank nomi",
    "fin.create.bankLoan.loanNameType": "Kredit nomi / turi",
    "fin.create.bankLoan.monthlyPayment": "Oylik toʻlov",
    "fin.create.bankLoan.takenDate": "Olingan sana",
    "fin.create.bankLoan.endDate": "Tugash sanasi",
    "fin.create.bankLoan.success": "Bank krediti yaratildi.",
    "fin.create.monthly.title": "Yangi obuna",
    "fin.create.monthly.monthlyAmount": "Oylik summa",
    "fin.create.monthly.dueDay": "Oyning qaysi kunida",
    "fin.create.monthly.success": "Obuna yaratildi.",
    "fin.create.donation.title": "Yangi xayriya",
    "fin.create.donation.recipient": "Qabul qiluvchi",
    "fin.create.donation.success": "Xayriya yaratildi.",
    "fin.create.investment.title": "Yangi investitsiya",
    "fin.create.investment.amountInvested": "Kiritilgan summa",
    # Phrased the way the two answer buttons below it are phrased ("Allaqachon menda bor").
    # The old wording used a non-word verb and the wrong case on this one screen where the
    # answer decides whether cash leaves a wallet.
    "fin.create.investment.openingBalanceQ": "Bu narsa allaqachon sizdami? Boshlangʻich balans faqat sof boylik uchun "
                                            "hisobga olinadi — hamyoningizdan pul chiqmaydi va bu oy taqsimotiga kirmaydi.",
    "fin.create.investment.openingYes": "✅ Allaqachon menda bor (boshlangʻich balans)",
    "fin.create.investment.openingNo": "🆕 Yangi xarid",
    "fin.create.investment.broker": "Broker / platforma",
    "fin.create.investment.purchaseDate": "Xarid sanasi",
    "fin.create.investment.success": "Investitsiya yaratildi.",
    "fin.create.goal.title": "Yangi jamgʻarma maqsadi",
    "fin.create.goal.goalName": "Maqsad nomi (masalan, iPhone, Uy)",
    "fin.create.goal.amountSaved": "Hozirgacha jamgʻarilgan summa",
    "fin.create.goal.openingQ": "Bu summa kuzatilayotgan hamyonlaringizdan TASHQARIDA (bankada, boshqa hisobda) allaqachon "
                                "jamgʻarilganmi? Shunday boʻlsa, u faqat maqsad progressi uchun qayd etiladi — naqd pul "
                                "yechilmaydi va bu oy taqsimotiga kirmaydi.",
    "fin.create.goal.openingYes": "✅ Boshqa joyda allaqachon jamgʻarilgan (faqat qayd)",
    "fin.create.goal.openingNo": "💵 Hozir naqd pulimdan olyapman",
    "fin.create.goal.targetAmount": "Maqsad summasi",
    "fin.create.goal.currentValue": "Hozirgi qiymat (agar oshgan boʻlsa)",
    "fin.create.goal.startDate": "Boshlanish sanasi",
    "fin.create.goal.notes": "Izohlar",
    "fin.create.goal.success": "Jamgʻarma maqsadi yaratildi.",
    "fin.create.emergency.title": "Favqulodda jamgʻarmaga yangi ajratma",
    "fin.create.emergency.success": "Favqulodda jamgʻarmangizga qoʻshildi.",
    "fin.goalGone": "Bu maqsad endi mavjud emas.",
    "fin.updateValueHeader": "📈 <b>{name}</b> qiymatini yangilash\nHozirgi: {current}\n\n"
                             "Yangi hozirgi qiymatni {currency} da yuboring:",
    "fin.updatedValue": "✅ <b>{name}</b> qiymati {value} ga yangilandi.",
}
