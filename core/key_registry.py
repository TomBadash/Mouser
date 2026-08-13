"""Platform-aware custom shortcut registry.

The registry keeps custom-shortcut parsing, labels, validation, and platform
key-code lookup on one canonical key namespace.  It intentionally uses US
physical-key semantics for punctuation so synthesis is predictable across the
platform APIs Mouser uses today.
"""

from __future__ import annotations

from dataclasses import dataclass


MODIFIER_ORDER = ("ctrl", "shift", "alt", "super")
MODIFIER_ALIASES = {
    "control": "ctrl",
    "option": "alt",
    "opt": "alt",
    "cmd": "super",
    "command": "super",
    "meta": "super",
    "win": "super",
    "windows": "super",
}
KEY_ALIASES = {
    "return": "enter",
    "escape": "esc",
    "del": "delete",
    "pgup": "pageup",
    "page up": "pageup",
    "pgdn": "pagedown",
    "page down": "pagedown",
    "ins": "insert",
    "print": "printscreen",
    "print screen": "printscreen",
    "prtsc": "printscreen",
    "prtscn": "printscreen",
    "sysrq": "printscreen",
    "leftarrow": "left",
    "rightarrow": "right",
    "uparrow": "up",
    "downarrow": "down",
    "semi": "semicolon",
    ";": "semicolon",
    "'": "quote",
    '"': "quote",
    "`": "grave",
    "-": "minus",
    "=": "equal",
    ",": "comma",
    ".": "period",
    "/": "slash",
    "\\": "backslash",
    "[": "leftbracket",
    "]": "rightbracket",
}

RESERVED_RISKY_SHORTCUTS = frozenset(
    {
        ("ctrl", "alt", "delete"),
        ("shift", "super", "s"),
        ("alt", "tab"),
        ("alt", "f4"),
        ("super", "space"),
        ("super", "tab"),
        ("shift", "super", "5"),
    }
)

SHIFTED_SYMBOLS = {
    "!": "1",
    "@": "2",
    "#": "3",
    "$": "4",
    "%": "5",
    "^": "6",
    "&": "7",
    "*": "8",
    "(": "9",
    ")": "0",
    "_": "minus",
    "+": "equal",
    "plus": "equal",
    "{": "leftbracket",
    "}": "rightbracket",
    "|": "backslash",
    ":": "semicolon",
    "~": "grave",
    "<": "comma",
    ">": "period",
    "?": "slash",
}


@dataclass(frozen=True)
class KeySpec:
    canonical: str
    label: str
    aliases: tuple[str, ...] = ()
    windows_vk: int | None = None
    macos_keycode: int | None = None
    linux_keycode: int | None = None

    def code_for(self, platform_name: str) -> int | None:
        if platform_name == "win32":
            return self.windows_vk
        if platform_name == "darwin":
            return self.macos_keycode
        if platform_name == "linux":
            return self.linux_keycode
        return None


def _letters():
    windows = {chr(ord("a") + i): 0x41 + i for i in range(26)}
    mac = {
        "a": 0x00, "s": 0x01, "d": 0x02, "f": 0x03, "h": 0x04,
        "g": 0x05, "z": 0x06, "x": 0x07, "c": 0x08, "v": 0x09,
        "b": 0x0B, "q": 0x0C, "w": 0x0D, "e": 0x0E, "r": 0x0F,
        "y": 0x10, "t": 0x11, "u": 0x20, "i": 0x22, "o": 0x1F,
        "p": 0x23, "l": 0x25, "j": 0x26, "k": 0x28, "n": 0x2D,
        "m": 0x2E,
    }
    linux = {
        "q": 16, "w": 17, "e": 18, "r": 19, "t": 20, "y": 21,
        "u": 22, "i": 23, "o": 24, "p": 25, "a": 30, "s": 31,
        "d": 32, "f": 33, "g": 34, "h": 35, "j": 36, "k": 37,
        "l": 38, "z": 44, "x": 45, "c": 46, "v": 47, "b": 48,
        "n": 49, "m": 50,
    }
    return [
        KeySpec(ch, ch.upper(), windows_vk=windows[ch], macos_keycode=mac[ch], linux_keycode=linux[ch])
        for ch in sorted(windows)
    ]


def _digits():
    mac = {
        "0": 0x1D, "1": 0x12, "2": 0x13, "3": 0x14, "4": 0x15,
        "5": 0x17, "6": 0x16, "7": 0x1A, "8": 0x1C, "9": 0x19,
    }
    return [
        KeySpec(str(n), str(n), windows_vk=0x30 + n, macos_keycode=mac[str(n)], linux_keycode=1 + n if n else 11)
        for n in range(10)
    ]


def _function_keys():
    mac = {
        1: 0x7A, 2: 0x78, 3: 0x63, 4: 0x76, 5: 0x60, 6: 0x61,
        7: 0x62, 8: 0x64, 9: 0x65, 10: 0x6D, 11: 0x67, 12: 0x6F,
        13: 0x69, 14: 0x6B, 15: 0x71, 16: 0x6A, 17: 0x40,
        18: 0x4F, 19: 0x50, 20: 0x5A,
    }
    linux = {n: 58 + n for n in range(1, 11)}
    linux.update({11: 87, 12: 88})
    linux.update({n: 170 + n for n in range(13, 25)})
    return [
        KeySpec(
            f"f{n}",
            f"F{n}",
            windows_vk=0x6F + n,
            macos_keycode=mac.get(n),
            linux_keycode=linux.get(n),
        )
        for n in range(1, 25)
    ]


KEY_SPECS = (
    KeySpec("ctrl", "Ctrl", aliases=("control",), windows_vk=0x11, macos_keycode=0x3B, linux_keycode=29),
    KeySpec("shift", "Shift", windows_vk=0x10, macos_keycode=0x38, linux_keycode=42),
    KeySpec("alt", "Alt", aliases=("option", "opt"), windows_vk=0x12, macos_keycode=0x3A, linux_keycode=56),
    KeySpec("super", "Super", aliases=("cmd", "command", "meta", "win", "windows"), windows_vk=0x5B, macos_keycode=0x37, linux_keycode=125),
    KeySpec("tab", "Tab", windows_vk=0x09, macos_keycode=0x30, linux_keycode=15),
    KeySpec("space", "Space", windows_vk=0x20, macos_keycode=0x31, linux_keycode=57),
    KeySpec("enter", "Enter", aliases=("return",), windows_vk=0x0D, macos_keycode=0x24, linux_keycode=28),
    KeySpec("esc", "Esc", aliases=("escape",), windows_vk=0x1B, macos_keycode=0x35, linux_keycode=1),
    KeySpec("backspace", "Backspace", windows_vk=0x08, macos_keycode=0x33, linux_keycode=14),
    KeySpec("delete", "Delete", aliases=("del",), windows_vk=0x2E, macos_keycode=0x75, linux_keycode=111),
    KeySpec("insert", "Insert", aliases=("ins",), windows_vk=0x2D, macos_keycode=0x72, linux_keycode=110),
    KeySpec(
        "printscreen",
        "Print Screen",
        aliases=("print", "print screen", "prtsc", "prtscn", "sysrq"),
        windows_vk=0x2C,
        # macOS exposes the equivalent physical key through the F13 keycode.
        macos_keycode=0x69,
        linux_keycode=99,
    ),
    KeySpec("left", "Left", aliases=("leftarrow",), windows_vk=0x25, macos_keycode=0x7B, linux_keycode=105),
    KeySpec("right", "Right", aliases=("rightarrow",), windows_vk=0x27, macos_keycode=0x7C, linux_keycode=106),
    KeySpec("up", "Up", aliases=("uparrow",), windows_vk=0x26, macos_keycode=0x7E, linux_keycode=103),
    KeySpec("down", "Down", aliases=("downarrow",), windows_vk=0x28, macos_keycode=0x7D, linux_keycode=108),
    KeySpec("pageup", "Page Up", aliases=("pgup", "page up"), windows_vk=0x21, macos_keycode=0x74, linux_keycode=104),
    KeySpec("pagedown", "Page Down", aliases=("pgdn", "page down"), windows_vk=0x22, macos_keycode=0x79, linux_keycode=109),
    KeySpec("home", "Home", windows_vk=0x24, macos_keycode=0x73, linux_keycode=102),
    KeySpec("end", "End", windows_vk=0x23, macos_keycode=0x77, linux_keycode=107),
    KeySpec("grave", "`", aliases=("`",), windows_vk=0xC0, macos_keycode=0x32, linux_keycode=41),
    KeySpec("minus", "-", aliases=("-",), windows_vk=0xBD, macos_keycode=0x1B, linux_keycode=12),
    KeySpec("equal", "=", aliases=("=",), windows_vk=0xBB, macos_keycode=0x18, linux_keycode=13),
    KeySpec("leftbracket", "[", aliases=("[",), windows_vk=0xDB, macos_keycode=0x21, linux_keycode=26),
    KeySpec("rightbracket", "]", aliases=("]",), windows_vk=0xDD, macos_keycode=0x1E, linux_keycode=27),
    KeySpec("backslash", "\\", aliases=("\\",), windows_vk=0xDC, macos_keycode=0x2A, linux_keycode=43),
    KeySpec("semicolon", ";", aliases=(";", "semi"), windows_vk=0xBA, macos_keycode=0x29, linux_keycode=39),
    KeySpec("quote", "'", aliases=("'", '"'), windows_vk=0xDE, macos_keycode=0x27, linux_keycode=40),
    KeySpec("comma", ",", aliases=(",",), windows_vk=0xBC, macos_keycode=0x2B, linux_keycode=51),
    KeySpec("period", ".", aliases=(".",), windows_vk=0xBE, macos_keycode=0x2F, linux_keycode=52),
    KeySpec("slash", "/", aliases=("/",), windows_vk=0xBF, macos_keycode=0x2C, linux_keycode=53),
    KeySpec("volumeup", "Volume Up", windows_vk=0xAF, linux_keycode=115),
    KeySpec("volumedown", "Volume Down", windows_vk=0xAE, linux_keycode=114),
    KeySpec("mute", "Mute", windows_vk=0xAD, linux_keycode=113),
    KeySpec("playpause", "Play / Pause", windows_vk=0xB3, linux_keycode=164),
    KeySpec("nexttrack", "Next Track", windows_vk=0xB0, linux_keycode=163),
    KeySpec("prevtrack", "Previous Track", windows_vk=0xB1, linux_keycode=165),
    *_letters(),
    *_digits(),
    *_function_keys(),
)

KEYS_BY_NAME = {spec.canonical: spec for spec in KEY_SPECS}
ALIASES = {}
for spec in KEY_SPECS:
    ALIASES[spec.canonical] = spec.canonical
    for alias in spec.aliases:
        ALIASES[alias.casefold()] = spec.canonical
for alias, canonical in {**MODIFIER_ALIASES, **KEY_ALIASES}.items():
    ALIASES[alias.casefold()] = canonical


class ShortcutParseError(ValueError):
    def __init__(self, message: str, *, code: str = "invalid", detail: str = ""):
        super().__init__(message)
        self.code = code
        self.detail = detail


def _normalize_token(token: str) -> tuple[tuple[str, ...], str]:
    raw = (token or "").strip()
    lowered = raw.casefold()
    if not lowered:
        raise ShortcutParseError("Empty key segment", code="empty_segment")
    if lowered in SHIFTED_SYMBOLS:
        return ("shift",), SHIFTED_SYMBOLS[lowered]
    canonical = ALIASES.get(lowered, lowered)
    if canonical not in KEYS_BY_NAME:
        raise ShortcutParseError(f"Unknown key: {raw}", code="unknown_key", detail=raw)
    return (), canonical


def parse_shortcut_text(text: str, *, allow_modifier_only: bool = False) -> tuple[str, ...]:
    parts = [part.strip() for part in (text or "").split("+")]
    if not parts or all(not part for part in parts):
        raise ShortcutParseError("Shortcut is empty", code="empty")

    modifiers: list[str] = []
    key_name = ""
    for part in parts:
        added_modifiers, canonical = _normalize_token(part)
        for modifier in added_modifiers:
            if modifier not in modifiers:
                modifiers.append(modifier)
        if canonical in MODIFIER_ORDER:
            if canonical in modifiers:
                raise ShortcutParseError(
                    f"Duplicate key: {canonical}",
                    code="duplicate_key",
                    detail=canonical,
                )
            modifiers.append(canonical)
            continue
        if key_name:
            raise ShortcutParseError(
                "Use exactly one non-modifier key",
                code="multiple_main_keys",
            )
        key_name = canonical

    if not key_name and not allow_modifier_only:
        raise ShortcutParseError("Need at least one non-modifier key", code="missing_main_key")

    ordered_modifiers = [name for name in MODIFIER_ORDER if name in modifiers]
    if key_name:
        return tuple([*ordered_modifiers, key_name])
    return tuple(ordered_modifiers)


def validate_shortcut_supported(parts, platform_name: str) -> tuple[str, ...]:
    """Return canonical parts if every key can be synthesized on platform_name."""
    canonical_parts = tuple(parts)
    for name in canonical_parts:
        spec = KEYS_BY_NAME.get(name)
        if spec is None:
            raise ShortcutParseError(f"Unknown key: {name}", code="unknown_key", detail=name)
        if spec.code_for(platform_name) is None:
            raise ShortcutParseError(
                f"Key is not supported on this platform: {spec.label}",
                code="unsupported_key",
                detail=spec.label,
            )
    return canonical_parts


def canonical_shortcut_text(
    text: str,
    *,
    allow_modifier_only: bool = False,
    platform_name: str | None = None,
) -> str:
    parts = parse_shortcut_text(text, allow_modifier_only=allow_modifier_only)
    if platform_name:
        parts = validate_shortcut_supported(parts, platform_name)
    return "+".join(parts)


def is_reserved_risky_shortcut(
    text: str,
    *,
    allow_modifier_only: bool = False,
) -> bool:
    return (
        parse_shortcut_text(text, allow_modifier_only=allow_modifier_only)
        in RESERVED_RISKY_SHORTCUTS
    )


def normalize_shortcut_parts(modifier_names, key_name="", *, platform_name=None) -> str:
    platform_name = platform_name or ""

    def normalize_capture_name(name):
        lowered = (name or "").strip().casefold()
        if platform_name == "darwin":
            if lowered == "ctrl":
                lowered = "super"
            elif lowered == "super":
                lowered = "ctrl"
        return lowered

    tokens = []
    for name in modifier_names:
        normalized = normalize_capture_name(name)
        if normalized and normalized not in tokens:
            tokens.append(normalized)
    if key_name:
        normalized_key = normalize_capture_name(key_name)
        if normalized_key and normalized_key not in tokens:
            tokens.append(normalized_key)
    return canonical_shortcut_text("+".join(tokens), allow_modifier_only=True)


def pretty_key_name(name: str, *, platform_name=None) -> str:
    platform_name = platform_name or ""
    _, canonical = _normalize_token(name)
    if canonical == "super":
        if platform_name == "darwin":
            return "Cmd"
        if platform_name == "win32":
            return "Win"
        return "Super"
    if canonical == "alt" and platform_name == "darwin":
        return "Opt"
    return KEYS_BY_NAME[canonical].label


def valid_key_names(platform_name: str) -> list[str]:
    names = set()
    for spec in KEY_SPECS:
        if spec.code_for(platform_name) is None:
            continue
        names.add(spec.canonical)
        names.update(alias.casefold() for alias in spec.aliases)
    names.update(MODIFIER_ALIASES)
    names.update(KEY_ALIASES)
    for symbol, canonical in SHIFTED_SYMBOLS.items():
        spec = KEYS_BY_NAME.get(canonical)
        if spec is not None and spec.code_for(platform_name) is not None:
            names.add(symbol)
    return sorted(names)


def build_key_name_to_code_map(base_map=None, platform_name: str = "") -> dict[str, int]:
    key_map = {}
    for spec in KEY_SPECS:
        code = spec.code_for(platform_name)
        if code is None:
            continue
        key_map[spec.canonical] = code
        for alias in spec.aliases:
            key_map[alias.casefold()] = code
    for alias, canonical in {**MODIFIER_ALIASES, **KEY_ALIASES}.items():
        if canonical in key_map:
            key_map[alias.casefold()] = key_map[canonical]
    if base_map:
        key_map.update(base_map)
        for alias, canonical in {**MODIFIER_ALIASES, **KEY_ALIASES}.items():
            if canonical in base_map:
                key_map[alias.casefold()] = base_map[canonical]
    return key_map
