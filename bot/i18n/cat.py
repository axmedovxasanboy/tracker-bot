"""Categories: the two-level tree, creating a root or a sub, editing one, deleting one.

`cat.*`

Category NAMES are data, not UI text — they arrive from the API with an optional `nameUz`
and are resolved by `cat_name()` in `__init__`. Nothing here translates a category. The two
name fields are editable from the bot precisely because `cat_name` picks between them: a
seeded category renamed in English still shows its old Uzbek name on an Uzbek screen, so the
edit screen shows both values and lets the owner change either one.

`cat.deleteConfirm` is written against `CategoryService.delete`, which runs
`detachChildren` (children get `parent = NULL`) and `TransactionRepository.detachFromCategory`
(`category = NULL`) before removing the row. No transaction is deleted, and the copy says so
in those words rather than the vaguer "linked transactions keep their history".
"""

EN: dict[str, str] = {
    # ── the tree ────────────────────────────────────────────────────────────
    "cat.title": "🏷 <b>Categories</b>",
    "cat.noneYet": "No categories yet.",
    "cat.loadError": "❌ Couldn't load categories.",
    "cat.backToCategories": "⬅️ Categories",
    # Type is a three-value enum on every screen — the tree headers, the picker buttons and
    # the detail line all say it with the same three words.
    "cat.typeIncome": "📈 Income",
    "cat.typeExpense": "📉 Expense",
    "cat.typeBoth": "🔀 Both",
    # ── creating one ────────────────────────────────────────────────────────
    "cat.newCategory": "➕ <b>New category</b>\nRoot or sub-category?",
    "cat.rootCategory": "📁 Root category",
    "cat.subCategory": "📂 Sub-category",
    "cat.sendName": "Send the <b>category name</b>:",
    "cat.noRootsYet": "No root categories yet — create a root first.",
    "cat.pickParent": "Pick the <b>parent</b>:",
    "cat.pickType": "Pick the <b>type</b>:",
    "cat.parentHeader": "Parent: <b>{name}</b>\nSend the <b>sub-category name</b>:",
    "cat.parentGone": "That parent no longer exists.",
    "cat.bonusQuestion": "Counts as <b>bonus income</b>? (Bonus adds the tier % on top of that month's "
                         "allocation target — e.g. a holiday bonus or 13th salary.)",
    "cat.bonusYes": "Yes — bonus",
    "cat.bonusNo": "No",
    "cat.created": "✅ Category <b>{name}</b> created.",
    # ── picking one to work on ──────────────────────────────────────────────
    "cat.pickToEdit": "✏️ Pick a category to edit:",
    "cat.pickToDelete": "🗑 Pick a category to delete:",
    # ── one category ────────────────────────────────────────────────────────
    "cat.detailTitle": "🏷 <b>{name}</b>",
    "cat.labelName": "Name",
    "cat.labelNameUz": "Uzbek name",
    "cat.labelType": "Type",
    "cat.inside": "Parent: <b>{name}</b>",
    "cat.topLevel": "Top-level category",
    "cat.children": "Sub-categories: {n}",
    "cat.bonusOn": "🎁 Counts as bonus income",
    "cat.bonusOff": "Not counted as bonus income",
    "cat.bonusOnBtn": "🎁 Count as bonus",
    "cat.bonusOffBtn": "🚫 Stop counting as bonus",
    "cat.editNameBtn": "✏️ Name",
    "cat.editNameUzBtn": "🇺🇿 Uzbek name",
    "cat.editPrompt": "<b>{field}</b>\nNow: {current}\n\nSend the new value:",
    "cat.clearHint": "Send <code>-</code> to remove it.",
    "cat.emptyValue": "Send the new name as text.",
    "cat.saved": "✅ Category updated.",
    "cat.saveError": "❌ Couldn't save that change.",
    "cat.gone": "That category no longer exists.",
    "cat.expired": "That form is no longer open. Start again from Categories.",
    # ── deleting one ────────────────────────────────────────────────────────
    "cat.deleteConfirm": "Delete <b>{name}</b>?\n\nIts sub-categories become top-level categories, and "
                         "transactions filed under it keep their history but lose the category. "
                         "No transaction is deleted.",
    "cat.deleted": "🗑 Category deleted.",
    "cat.deleteError": "❌ Couldn't delete that category.",
}

UZ: dict[str, str] = {
    "cat.title": "🏷 <b>Kategoriyalar</b>",
    "cat.noneYet": "Hozircha kategoriyalar yoʻq.",
    "cat.loadError": "❌ Kategoriyalarni yuklab boʻlmadi.",
    "cat.backToCategories": "⬅️ Kategoriyalar",
    "cat.typeIncome": "📈 Daromad",
    "cat.typeExpense": "📉 Xarajat",
    "cat.typeBoth": "🔀 Ikkalasi",
    "cat.newCategory": "➕ <b>Yangi kategoriya</b>\nAsosiymi yoki ichkimi?",
    "cat.rootCategory": "📁 Asosiy kategoriya",
    "cat.subCategory": "📂 Ichki kategoriya",
    "cat.sendName": "<b>Kategoriya nomini</b> yuboring:",
    "cat.noRootsYet": "Hozircha asosiy kategoriyalar yoʻq — avval asosiysini yarating.",
    "cat.pickParent": "<b>Ota kategoriyani</b> tanlang:",
    "cat.pickType": "<b>Turini</b> tanlang:",
    "cat.parentHeader": "Ota kategoriya: <b>{name}</b>\n<b>Ichki kategoriya nomini</b> yuboring:",
    "cat.parentGone": "Bu ota kategoriya endi mavjud emas.",
    "cat.bonusQuestion": "<b>Bonus daromad</b> hisoblansinmi? (Bonus shu oyning taqsimot maqsadiga ustama % "
                         "qoʻshadi — masalan, bayram bonusi yoki 13-oylik.)",
    "cat.bonusYes": "Ha — bonus",
    "cat.bonusNo": "Yoʻq",
    "cat.created": "✅ <b>{name}</b> kategoriyasi yaratildi.",
    "cat.pickToEdit": "✏️ Tahrirlash uchun kategoriyani tanlang:",
    "cat.pickToDelete": "🗑 Oʻchirish uchun kategoriyani tanlang:",
    "cat.detailTitle": "🏷 <b>{name}</b>",
    "cat.labelName": "Nomi",
    "cat.labelNameUz": "Oʻzbekcha nomi",
    "cat.labelType": "Turi",
    "cat.inside": "Ota kategoriya: <b>{name}</b>",
    "cat.topLevel": "Asosiy kategoriya",
    "cat.children": "Ichki kategoriyalari: {n}",
    "cat.bonusOn": "🎁 Bonus daromad hisoblanadi",
    "cat.bonusOff": "Bonus daromad hisoblanmaydi",
    "cat.bonusOnBtn": "🎁 Bonus deb belgilash",
    "cat.bonusOffBtn": "🚫 Bonusdan chiqarish",
    "cat.editNameBtn": "✏️ Nomi",
    "cat.editNameUzBtn": "🇺🇿 Oʻzbekcha nomi",
    "cat.editPrompt": "<b>{field}</b>\nHozir: {current}\n\nYangi qiymatni yuboring:",
    "cat.clearHint": "Oʻchirish uchun <code>-</code> yuboring.",
    "cat.emptyValue": "Yangi nomni matn koʻrinishida yuboring.",
    "cat.saved": "✅ Kategoriya yangilandi.",
    "cat.saveError": "❌ Oʻzgarishni saqlab boʻlmadi.",
    "cat.gone": "Bu kategoriya endi mavjud emas.",
    "cat.expired": "Bu shakl endi ochiq emas. Kategoriyalardan qaytadan boshlang.",
    "cat.deleteConfirm": "<b>{name}</b> oʻchirilsinmi?\n\nUning ichki kategoriyalari asosiy kategoriyaga "
                         "aylanadi, unga yozilgan tranzaksiyalar esa tarixda qoladi, faqat kategoriyasi "
                         "boʻshab qoladi. Hech qaysi tranzaksiya oʻchmaydi.",
    "cat.deleted": "🗑 Kategoriya oʻchirildi.",
    "cat.deleteError": "❌ Kategoriyani oʻchirib boʻlmadi.",
}
