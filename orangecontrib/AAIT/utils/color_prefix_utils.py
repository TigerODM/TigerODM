import re
from typing import Optional, Tuple

# -----------------------------
# Colors: %!color!% prefix (headers + cells)
# exmple %!yellow!%
#  ou bbien %!#RRGGBB!%
# -----------------------------

COLOR_MAP = {
    # neutres
    "blanc": "FFFFFF", "white": "FFFFFF",
    "gris": "E0E0E0", "gray": "E0E0E0", "grey": "E0E0E0",
    "gris_clair": "F2F2F2",

    # pastel lisibles
    "jaune": "FFF2CC", "yellow": "FFF2CC",
    "vert": "E2F0D9", "green": "E2F0D9",
    "rouge": "FCE4D6", "red": "FCE4D6",
    "bleu": "DDEBF7", "blue": "DDEBF7",
    "violet": "EDE7F6", "purple": "EDE7F6",
    "orange": "FBE5D6",
    "cyan": "E7F3F8", "turquoise": "E7F3F8",
    "rose": "FCE4EC", "pink": "FCE4EC",
}

# -----------------------------
# Font colors: teintes vives (à distinguer de COLOR_MAP, pensé pour les fonds)
# -----------------------------
FONT_COLOR_MAP = {
    "noir": "000000", "black": "000000",
    "blanc": "FFFFFF", "white": "FFFFFF",
    "gris": "808080", "gray": "808080", "grey": "808080",
    "rouge": "FF0000", "red": "FF0000",
    "vert": "008000", "green": "008000",
    "bleu": "0000FF", "blue": "0000FF",
    "orange": "FF8C00",
    "violet": "800080", "purple": "800080",
    "jaune": "FFC000", "yellow": "FFC000",
    "rose": "E91E63", "pink": "E91E63",
    "cyan": "00B0C0", "turquoise": "00B0C0",
}

def resolve_font_color(token: str) -> str:
    """Nom -> hex vif ; sinon #hex direct ; sinon noir (défaut visible)."""
    t = str(token or "").strip().lower()
    if t.startswith("#"):
        t = t[1:]
    if re.fullmatch(r"[0-9a-f]{6}", t):
        return t.upper()
    return FONT_COLOR_MAP.get(t, "000000")

def normalize_hex(color: str) -> str:
    if not color:
        return "FFFFFF"
    c = str(color).strip().lower()
    if c.startswith("#"):
        c = c[1:]
    if re.fullmatch(r"[0-9a-f]{6}", c):
        return c.upper()
    return COLOR_MAP.get(c, "FFFFFF")


def parse_color_prefix(value: str) -> Tuple[str, Optional[str]]:
    """
    Detect prefix %!color!% or %!#RRGGBB!%
    Returns (text_without_prefix, hex_color_or_None)
    """
    if value is None:
        return "", None

    s = str(value)
    m = re.match(r"^%!(.*?)!%", s)
    if not m:
        return s, None

    token = m.group(1).strip()
    text = s[m.end():]
    return text, normalize_hex(token)


def hex_rgb_to_excel_bgr(hex_rgb: str) -> int:
    hex_rgb = normalize_hex(hex_rgb)
    r = int(hex_rgb[0:2], 16)
    g = int(hex_rgb[2:4], 16)
    b = int(hex_rgb[4:6], 16)
    return r + (g << 8) + (b << 16)
