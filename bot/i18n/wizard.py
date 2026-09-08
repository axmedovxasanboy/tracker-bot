"""The generic create-flow stepper.

`wizard.*`

Field LABELS do not live here: a wizard spec carries i18n keys owned by the section it
creates for (`fin.create.*`, `cards.new.*`), and the stepper drops them into `{label}`.
That is why every prompt below is a frame with a hole in it rather than a finished sentence.

The same rule is what makes the review screen possible at all. A spec is a list of
(label key, kind) pairs, so the stepper can print back what it collected using the very
words it asked with — the owner reads "Creditor name — Aziz" in the language they answered
in, and the stepper never has to know that a creditor is a person or that a bank loan has a
bank in it.
"""

EN: dict[str, str] = {
    "wizard.stepHeader": "➕ <b>{title}</b> · step {index}/{total}",
    "wizard.amountPrompt": "Send <b>{label}</b> in {currency}:",
    "wizard.numberPrompt": "Send <b>{label}</b> in {currency} (0 or more):",
    # The parser takes every shape money is written in here, and nothing on screen said so.
    "wizard.amountHint": "<i>250000 · 250 ming · 50k · 1.5m all work.</i>",
    "wizard.intPrompt": "Send <b>{label}</b> (a number):",
    "wizard.datePrompt": "Send <b>{label}</b> as YYYY-MM-DD:",
    "wizard.monthPrompt": "Send <b>{label}</b> as YYYY-MM:",
    "wizard.choicePrompt": "Pick <b>{label}</b>:",
    "wizard.textPrompt": "Send <b>{label}</b>:",
    "wizard.boolPrompt": "<b>{label}</b>",
    # Shown when a step is revisited — from Back, or from a line on the review screen.
    "wizard.currently": "Currently: <b>{value}</b>",
    "wizard.yesDefault": "✅ Yes",
    "wizard.noDefault": "❌ No",
    "wizard.wholeNumber": "Send a whole number.",
    "wizard.numberRange": "Enter a number between {min} and {max}.",
    "wizard.numberMin": "Enter {min} or more.",
    "wizard.numberMax": "Enter {max} or less.",
    "wizard.dateFormat": "Use the format YYYY-MM-DD.",
    "wizard.monthFormat": "Use the format YYYY-MM.",
    "wizard.invalidFormat": "Invalid format.",
    "wizard.tapButton": "Please tap one of the buttons.",
    "wizard.textOnly": "I can only read written text — a voice note, photo or sticker tells me "
                       "nothing. Please type <b>{label}</b>.",
    "wizard.required": "<b>{label}</b> is needed before this can be saved.",
    # A callback-answer toast, so it has to stand alone with no screen around it.
    "wizard.stepMoved": "That step is already answered — use the newest message.",
    "wizard.expired": "This form is no longer open. Nothing was saved.",
    "wizard.reviewTitle": "🧾 <b>{title}</b> — check it before saving",
    "wizard.reviewHint": "<i>Tap a line to change it. Nothing is saved until you tap Save.</i>",
    "wizard.reviewLine": "{index}. <b>{label}</b> — {value}",
    "wizard.notSet": "not set",
    "wizard.fieldBtn": "{index}. {label}",
    "wizard.saveBtn": "✅ Save",
    "wizard.savedDefault": "Saved.",
}

UZ: dict[str, str] = {
    "wizard.stepHeader": "➕ <b>{title}</b> · {index}/{total}-qadam",
    "wizard.amountPrompt": "<b>{label}</b> summasini {currency} da yuboring:",
    "wizard.numberPrompt": "<b>{label}</b> qiymatini {currency} da yuboring (0 yoki koʻproq):",
    "wizard.amountHint": "<i>250000 · 250 ming · 50k · 1,5 mln — hammasi boʻladi.</i>",
    "wizard.intPrompt": "<b>{label}</b> yuboring (son):",
    "wizard.datePrompt": "<b>{label}</b> ni YYYY-MM-DD shaklida yuboring:",
    "wizard.monthPrompt": "<b>{label}</b> ni YYYY-MM shaklida yuboring:",
    "wizard.choicePrompt": "<b>{label}</b> ni tanlang:",
    "wizard.textPrompt": "<b>{label}</b> yuboring:",
    "wizard.boolPrompt": "<b>{label}</b>",
    "wizard.currently": "Hozir: <b>{value}</b>",
    "wizard.yesDefault": "✅ Ha",
    "wizard.noDefault": "❌ Yoʻq",
    "wizard.wholeNumber": "Butun son yuboring.",
    "wizard.numberRange": "{min} va {max} oraligʻida son kiriting.",
    "wizard.numberMin": "{min} yoki undan katta son kiriting.",
    "wizard.numberMax": "{max} yoki undan kichik son kiriting.",
    "wizard.dateFormat": "YYYY-MM-DD shaklidan foydalaning.",
    "wizard.monthFormat": "YYYY-MM shaklidan foydalaning.",
    "wizard.invalidFormat": "Notoʻgʻri format.",
    "wizard.tapButton": "Iltimos, tugmalardan birini bosing.",
    "wizard.textOnly": "Men faqat yozma matnni oʻqiy olaman — ovozli xabar, rasm yoki stikerdan "
                       "hech narsa tushunmayman. <b>{label}</b> ni yozib yuboring.",
    "wizard.required": "Saqlashdan oldin <b>{label}</b> toʻldirilishi kerak.",
    "wizard.stepMoved": "Bu qadamga javob berilgan — eng oxirgi xabardan foydalaning.",
    "wizard.expired": "Bu shakl endi ochiq emas. Hech narsa saqlanmadi.",
    "wizard.reviewTitle": "🧾 <b>{title}</b> — saqlashdan oldin tekshiring",
    "wizard.reviewHint": "<i>Oʻzgartirish uchun qatorni bosing. «Saqlash» bosilmaguncha hech "
                         "narsa yozilmaydi.</i>",
    "wizard.reviewLine": "{index}. <b>{label}</b> — {value}",
    "wizard.notSet": "kiritilmagan",
    "wizard.fieldBtn": "{index}. {label}",
    "wizard.saveBtn": "✅ Saqlash",
    "wizard.savedDefault": "Saqlandi.",
}
