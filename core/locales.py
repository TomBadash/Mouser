"""Language preference helpers shared by config and UI code."""

SYSTEM_LANGUAGE = "system"
APP_LANGUAGES = ("en", "zh_CN", "zh_TW")
LANGUAGE_PREFERENCES = (SYSTEM_LANGUAGE, *APP_LANGUAGES)

_TRADITIONAL_CHINESE_REGIONS = frozenset({"HK", "MO", "TW"})


def normalize_language_preference(value: object) -> str:
    """Return a supported persisted preference, falling back to the system."""
    if isinstance(value, str) and value in LANGUAGE_PREFERENCES:
        return value
    return SYSTEM_LANGUAGE


def language_for_system_locale(locale_name: str | None) -> str:
    """Map a system locale name to one of Mouser's translated languages."""
    normalized = str(locale_name or "").replace("-", "_")
    parts = [part for part in normalized.split("_") if part]
    if not parts or parts[0].casefold() != "zh":
        return "en"

    subtags = {part.upper() for part in parts[1:]}
    if "HANT" in subtags or subtags & _TRADITIONAL_CHINESE_REGIONS:
        return "zh_TW"
    return "zh_CN"


def resolve_language_preference(
    preference: object,
    system_locale_name: str | None,
) -> str:
    """Resolve a persisted preference to the translation catalog to display."""
    normalized = normalize_language_preference(preference)
    if normalized == SYSTEM_LANGUAGE:
        return language_for_system_locale(system_locale_name)
    return normalized
