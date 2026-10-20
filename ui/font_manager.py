"""Choose UI fonts that match the active locale's CJK glyph forms."""

_PLATFORM_DEFAULTS = {
    "darwin": ".AppleSystemUIFont",
    "win32": "Segoe UI",
    "linux": "Noto Sans",
}

_CJK_FONT_CANDIDATES = {
    "win32": {
        "zh_CN": (
            "Microsoft YaHei UI",
            "Microsoft YaHei",
            "DengXian",
            "Noto Sans CJK SC",
            "Noto Sans SC",
            "SimSun",
        ),
        "zh_TW": (
            "Microsoft JhengHei UI",
            "Microsoft JhengHei",
            "Noto Sans CJK TC",
            "Noto Sans TC",
            "PMingLiU",
            "MingLiU",
        ),
    },
    "darwin": {
        "zh_CN": ("PingFang SC", "Heiti SC", "Songti SC"),
        "zh_TW": ("PingFang TC", "Heiti TC", "Songti TC"),
    },
    "linux": {
        "zh_CN": (
            "Noto Sans CJK SC",
            "Noto Sans SC",
            "Source Han Sans SC",
            "WenQuanYi Micro Hei",
        ),
        "zh_TW": (
            "Noto Sans CJK TC",
            "Noto Sans TC",
            "Source Han Sans TC",
            "WenQuanYi Micro Hei",
        ),
    },
}


def preferred_ui_font_family(
    platform_name: str,
    language: str,
    available_families: list[str] | tuple[str, ...],
    system_family: str,
) -> str:
    """Return an installed, locale-appropriate UI font family.

    Explicitly selecting a Chinese UI font prevents an English system locale
    from making Qt choose an arbitrary CJK fallback with the wrong regional
    glyph forms. The original system family remains the final fallback.
    """
    fallback = system_family
    if fallback in {"", "Sans Serif"}:
        fallback = _PLATFORM_DEFAULTS.get(platform_name, "Noto Sans")

    candidates = _CJK_FONT_CANDIDATES.get(platform_name, {}).get(language, ())
    installed = {family.casefold(): family for family in available_families}
    for candidate in candidates:
        matched = installed.get(candidate.casefold())
        if matched:
            return matched
    return fallback
