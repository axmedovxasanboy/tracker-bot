"""Per-chat UZ/EN language for the bot.

Deliberately independent of the web app: the web keeps its choice in browser localStorage,
which the bot cannot read, so each chat carries its own preference here. It lives in memory,
except the owner's, which bot/storage.py keeps across restarts with their login.

Category names are DATA, not UI text — they come from the API with an optional `nameUz`,
resolved by `cat_name` below.

The strings themselves live one module per area (`home.py`, `record.py`, …), each exporting a
plain `EN` and `UZ` dict, merged flat here at import. The merge is where the invariants are
enforced rather than assumed: same keys in both languages, same placeholders in both
languages, one namespace per module, no key defined twice. A violation is an ImportError naming the module
and the keys — the bot refuses to start rather than shipping a screen that renders a raw
key, or an Uzbek confirmation that has silently lost its {amount}.
"""
import re
from types import ModuleType

from . import auth, common, home, pay, record, system, wallet

EN = "en"
UZ = "uz"

# Each module and the key prefixes it owns. Ownership is per-namespace, not per-file, so
# that adding a key can never quietly overwrite another agent's screen: pick a prefix from
# your own row, or the merge below refuses the import.
_AREAS: tuple[tuple[ModuleType, tuple[str, ...]], ...] = (
    (common, ("common.", "guard.", "lang.", "settings.")),
    (auth, ("auth.",)),
    (system, ("system.",)),
    (home, ("home.",)),
    (pay, ("pay.",)),
    (record, ("record.",)),
    (wallet, ("wallet.",)),
)

# `{name}` — the only templating the strings use. Deliberately \w+ so that stray braces in
# prose (there are none today, but Uzbek quotes and HTML entities travel through here) are
# left alone rather than treated as a hole to fill.
_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _holes(text: str) -> set[str]:
    return set(_PLACEHOLDER.findall(text))


def _merge() -> tuple[dict[str, str], dict[str, str]]:
    en: dict[str, str] = {}
    uz: dict[str, str] = {}
    owner: dict[str, str] = {}  # key -> the area that defined it, for the collision message
    for module, prefixes in _AREAS:
        area = module.__name__.rpartition(".")[2]
        m_en: dict[str, str] = module.EN
        m_uz: dict[str, str] = module.UZ

        no_uz = sorted(m_en.keys() - m_uz.keys())
        no_en = sorted(m_uz.keys() - m_en.keys())
        if no_uz or no_en:
            raise ImportError(
                f"bot/i18n/{area}.py: EN and UZ must define the same keys. "
                f"Missing from UZ: {no_uz or 'none'}. Missing from EN: {no_en or 'none'}."
            )

        stray = sorted(k for k in m_en if not k.startswith(prefixes))
        if stray:
            raise ImportError(
                f"bot/i18n/{area}.py may only define keys starting with {' or '.join(prefixes)} — "
                f"these belong to another module's namespace: {stray}."
            )

        taken = sorted(k for k in m_en if k in owner)
        if taken:
            raise ImportError(
                "bot/i18n/{}.py redefines keys another module already owns: {}.".format(
                    area, ", ".join(f"{k} (from {owner[k]}.py)" for k in taken)
                )
            )

        # A translation that drops or renames a placeholder is the failure that reaches the
        # owner as a confirmation screen with no amount on it, so it is fatal too.
        skewed = sorted(k for k in m_en if _holes(m_en[k]) != _holes(m_uz[k]))
        if skewed:
            raise ImportError(
                "bot/i18n/{}.py: EN and UZ disagree on placeholders — {}.".format(
                    area,
                    "; ".join(
                        f"{k}: EN {sorted(_holes(m_en[k]))} vs UZ {sorted(_holes(m_uz[k]))}"
                        for k in skewed
                    ),
                )
            )

        en.update(m_en)
        uz.update(m_uz)
        owner.update(dict.fromkeys(m_en, area))
    return en, uz


_EN, _UZ = _merge()

_lang: dict[int, str] = {}


def _restore_owner_lang() -> None:
    """The owner's language survives a restart (bot/storage.py); other chats' do not."""
    from .. import storage
    owner = storage.owner()
    saved = storage.get("lang")
    if owner is not None and saved in (EN, UZ):
        _lang[owner] = saved


_restore_owner_lang()


def get_lang(chat_id: int | None) -> str:
    return _lang.get(chat_id, EN)


def set_lang(chat_id: int, lang: str) -> None:
    _lang[chat_id] = lang if lang in (EN, UZ) else EN
    from .. import storage
    if chat_id == storage.owner():
        storage.put("lang", _lang[chat_id])


def t(chat_id: int | None, key: str, **vars) -> str:
    """Translate a key for this chat. Falls back to English, then to the key itself.

    Substitution is ONE pass driven by the template, so a value can never be rescanned:
    a creditor named "{amount}" is printed as those eight characters instead of rewriting
    the money figure on the payment confirmation the owner is about to approve. An unknown
    placeholder is left standing — a visible `{amount}` on screen is a bug report, whereas
    a KeyError here would abort the handler and leave a spinning button.
    """
    table = _UZ if get_lang(chat_id) == UZ else _EN
    raw = table.get(key) or _EN.get(key) or key
    if not vars:
        return raw
    return _PLACEHOLDER.sub(
        lambda m: str(vars[m.group(1)]) if m.group(1) in vars else m.group(0), raw)


def cat_name(chat_id: int | None, category) -> str:
    """A category's name in the chat's language, falling back to the English name."""
    if not category:
        return "—"
    if get_lang(chat_id) == UZ:
        uz = (category.get("nameUz") or "").strip()
        if uz:
            return uz
    return category.get("name") or "—"


__all__ = ["EN", "UZ", "cat_name", "get_lang", "set_lang", "t"]
