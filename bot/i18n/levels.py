"""📐 Levels and savings rules: Settings → Savings rules, the change flow, Level 5's road on Profile,
and the notice when Level 5 starts or ends.

`levels.*`

The words of LEVELS-ALLOCATION-SPEC.md §2.7. No codes ("1.2.1"), no "sub-level", no "scenario".
"""

EN: dict[str, str] = {
    # Settings → Savings rules
    "levels.title": "📐 <b>Savings rules</b>",
    "levels.btn.rules": "📐 Savings rules",
    "levels.level.under": "Level {n} · under {to} left after bills",
    "levels.level.band": "Level {n} · {start} – {to} left after bills",
    "levels.level.over": "Level {n} · {start} or more left after bills",
    "levels.level.five": ("Level 5 · after three months in a row with {amount} of pay or more on Level 4. "
                          "It stays until three months in a row under it."),
    "levels.thisMonth": "<b>This month:</b> {name} · {percents}",
    "levels.legend": "<i>Donation · Emergency · Investments</i>",
    "levels.row": "{mark} {name} · {percents}",
    "levels.changes": "Changes: {list}",
    "levels.changeFrom": "from {month}",
    "levels.elsewhere": "<i>Other levels and situations: on the website.</i>",
    "levels.btn.change": "✏️ Change this month's rule",
    "levels.noSituation": "Set your monthly income first — the rule in force depends on it.",

    # The seven situations
    "levels.s.noDebt": "No loans",
    "levels.s.bankMore": "Bank loan — {cutoff} or more left",
    "levels.s.bankUnder": "Bank loan — under {cutoff} left",
    "levels.s.peopleMore": "Loans from people — {cutoff} or more left",
    "levels.s.peopleUnder": "Loans from people — under {cutoff} left",
    "levels.s.both": "Bank loan and loans from people",
    "levels.s.heavy": "Heavy loans (over 70% of income)",

    # Change this month's rule
    "levels.ask.title": "📐 <b>Level {n} · {name}</b>",
    "levels.ask.now": "Now: {percents}",
    "levels.ask.numbers": "Send donation, emergency and investments in %, e.g. <code>5 2 8</code>. 0 means not asked.",
    "levels.ask.split": ("Where it splits can follow — now {cutoff} left after bills and loans: "
                         "<code>5 2 8 {example}</code>."),
    "levels.err.format": "Send three numbers, e.g. <code>5 2 8</code>.",
    "levels.err.each": "Up to 100% each, with one decimal at most.",
    "levels.err.sum": "Together at most 100%.",
    "levels.err.split": "Send where it splits as an amount, e.g. <code>5000000</code>.",
    "levels.splitAt": "Split at {amount} left after bills and loans",
    "levels.amounts": "At your income that is {amounts} a month.",
    "levels.fromAsk": "<b>From which month?</b>",
    "levels.saved": "✅ Saved: Level {n} from {month}.",

    # The notice
    "levels.up.title": "🎉 <b>You're on Level 5</b>",
    "levels.up.pay": "Your pay was {amount} or more three months in a row: {months}.",
    "levels.up.from": "From {month}, Level 5's savings rule applies.",
    "levels.situation": "Your situation: {name} · {percents}",
    "levels.down.title": "↩️ <b>Back to Level {n} from {month}</b>",
    "levels.down.body": ("Your pay was under {amount} three months in a row ({months}), so Level {n}'s savings "
                         "rule applies again: {percents}."),
    "levels.btn.ok": "👌 OK",
    "levels.btn.changeIt": "✏️ Change",

    # Profile
    "levels.road.toFive": "Level 5 after three months in a row with {amount} of pay or more",
    "levels.road.count": "so far {n} of {need}",
    "levels.road.none": "no months yet",
    "levels.road.thisMonth": "{month}: {amount} so far",
    "levels.five.since": ("Level 5 · since {month}. It stays while your pay is {amount} or more; three months "
                          "in a row under it and you go back to Level {base}."),
    "levels.five.under": "Under it so far: {n} of {need} ({months}).",
    "levels.ruleLine": "Level {n} · {name}",
    "levels.ruleFrom": "These percentages apply from {month}.",
    "levels.millions": "{amount} M",
}

UZ: dict[str, str] = {
    "levels.title": "📐 <b>Jamgʻarma qoidalari</b>",
    "levels.btn.rules": "📐 Jamgʻarma qoidalari",
    "levels.level.under": "{n}-daraja · toʻlovlardan keyin {to} dan kam",
    "levels.level.band": "{n}-daraja · toʻlovlardan keyin {start} – {to}",
    "levels.level.over": "{n}-daraja · toʻlovlardan keyin {start} yoki koʻproq",
    "levels.level.five": ("5-daraja · 4-darajada ketma-ket uch oy {amount} yoki undan koʻp maoshdan keyin. "
                          "Ketma-ket uch oy undan kam boʻlguncha saqlanadi."),
    "levels.thisMonth": "<b>Shu oy:</b> {name} · {percents}",
    "levels.legend": "<i>Xayriya · Favqulodda · Investitsiyalar</i>",
    "levels.row": "{mark} {name} · {percents}",
    "levels.changes": "Oʻzgarishlar: {list}",
    "levels.changeFrom": "{month} dan",
    "levels.elsewhere": "<i>Boshqa darajalar va holatlar: veb-saytda.</i>",
    "levels.btn.change": "✏️ Shu oy qoidasini oʻzgartirish",
    "levels.noSituation": "Avval oylik daromadingizni kiriting — amaldagi qoida unga bogʻliq.",

    "levels.s.noDebt": "Qarzsiz",
    "levels.s.bankMore": "Bank krediti — {cutoff} yoki koʻproq qoladi",
    "levels.s.bankUnder": "Bank krediti — {cutoff} dan kam qoladi",
    "levels.s.peopleMore": "Odamlardan qarz — {cutoff} yoki koʻproq qoladi",
    "levels.s.peopleUnder": "Odamlardan qarz — {cutoff} dan kam qoladi",
    "levels.s.both": "Bank krediti va odamlardan qarz",
    "levels.s.heavy": "Ogʻir qarz (daromadning 70% idan koʻp)",

    "levels.ask.title": "📐 <b>{n}-daraja · {name}</b>",
    "levels.ask.now": "Hozir: {percents}",
    "levels.ask.numbers": ("Xayriya, favqulodda va investitsiyalarni % da yuboring, masalan <code>5 2 8</code>. "
                           "0 — soʻralmaydi."),
    "levels.ask.split": ("Chegarani ham yozish mumkin — hozir toʻlovlar va qarzlardan keyin {cutoff}: "
                         "<code>5 2 8 {example}</code>."),
    "levels.err.format": "Uchta son yuboring, masalan <code>5 2 8</code>.",
    "levels.err.each": "Har biri 100% gacha, koʻpi bilan bitta kasr raqam bilan.",
    "levels.err.sum": "Hammasi birga 100% dan oshmasin.",
    "levels.err.split": "Chegarani summa qilib yuboring, masalan <code>5000000</code>.",
    "levels.splitAt": "Chegara: toʻlovlar va qarzlardan keyin {amount}",
    "levels.amounts": "Daromadingizda bu oyiga {amounts}.",
    "levels.fromAsk": "<b>Qaysi oydan boshlab?</b>",
    "levels.saved": "✅ Saqlandi: {n}-daraja, {month} dan.",

    "levels.up.title": "🎉 <b>Siz 5-darajadasiz</b>",
    "levels.up.pay": "Maoshingiz ketma-ket uch oy {amount} yoki undan koʻp boʻldi: {months}.",
    "levels.up.from": "{month} dan 5-daraja jamgʻarma qoidasi amal qiladi.",
    "levels.situation": "Sizning holatingiz: {name} · {percents}",
    "levels.down.title": "↩️ <b>{month} dan yana {n}-daraja</b>",
    "levels.down.body": ("Maoshingiz ketma-ket uch oy {amount} dan kam boʻldi ({months}), shuning uchun yana "
                         "{n}-daraja jamgʻarma qoidasi amal qiladi: {percents}."),
    "levels.btn.ok": "👌 OK",
    "levels.btn.changeIt": "✏️ Oʻzgartirish",

    "levels.road.toFive": "Ketma-ket uch oy {amount} yoki undan koʻp maosh — 5-daraja",
    "levels.road.count": "hozircha {need} tadan {n}",
    "levels.road.none": "hali oy yoʻq",
    "levels.road.thisMonth": "{month}: hozircha {amount}",
    "levels.five.since": ("5-daraja · {month} dan beri. Maoshingiz {amount} yoki undan koʻp ekan, saqlanadi; "
                          "ketma-ket uch oy undan kam boʻlsa, {base}-darajaga qaytasiz."),
    "levels.five.under": "Hozircha undan kam: {need} tadan {n} ({months}).",
    "levels.ruleLine": "{n}-daraja · {name}",
    "levels.ruleFrom": "Bu foizlar {month} dan amal qiladi.",
    "levels.millions": "{amount} mln",
}
