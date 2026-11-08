"""Per-language text normalization so that TTS engines read text naturally.

Converts numbers, decimals, percentages, currency, dates, times, units and
common abbreviations into words (vi, en); cleans URLs, emoji and whitespace for
all languages. Korean and Chinese keep their digits (engines read them well).
Newlines are preserved because the segmenter uses them for pauses.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Callable

from giongdoc.core import Language

# ---------------------------------------------------------------------------
# Vietnamese number reading
# ---------------------------------------------------------------------------
_VI_DIGITS = ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]


def _vi_triple(n: int, full: bool) -> list[str]:
    """Read 0..999. `full` forces 'không trăm' / 'linh' (non-leading groups)."""
    h, t, u = n // 100, n // 10 % 10, n % 10
    out: list[str] = []
    if h or full:
        out += [_VI_DIGITS[h], "trăm"]
    if t == 0:
        if u:
            if h or full:
                out.append("linh")
            out.append(_VI_DIGITS[u])
    elif t == 1:
        out.append("mười")
        if u == 5:
            out.append("lăm")
        elif u:
            out.append(_VI_DIGITS[u])
    else:
        out += [_VI_DIGITS[t], "mươi"]
        out.append({0: "", 1: "mốt", 4: "tư", 5: "lăm"}.get(u, _VI_DIGITS[u]))
    return [w for w in out if w]


def _vi_scale(pos: int) -> str:
    """Name of the 10^(3*pos) group: '', nghìn, triệu, tỷ, nghìn tỷ, ..."""
    return " ".join(w for w in [["", "nghìn", "triệu"][pos % 3]] + ["tỷ"] * (pos // 3) if w)


def vi_number(n: int) -> str:
    """Read an integer in Vietnamese: 21 -> 'hai mươi mốt', 105 -> 'một trăm linh năm'."""
    if n < 0:
        return "âm " + vi_number(-n)
    if n == 0:
        return "không"
    groups = []
    while n:
        groups.append(n % 1000)
        n //= 1000
    words: list[str] = []
    first = True
    for pos in range(len(groups) - 1, -1, -1):
        g = groups[pos]
        if g == 0:
            continue
        words += _vi_triple(g, full=not first)
        scale = _vi_scale(pos)
        if scale:
            words.append(scale)
        first = False
    return " ".join(words)


def _vi_digits(s: str) -> str:
    return " ".join(_VI_DIGITS[int(c)] for c in s)


def _vi_int_str(s: str) -> str:
    """Integer string -> words; codes / phone numbers are read digit by digit."""
    if (len(s) >= 4 and s.startswith("0")) or len(s) > 15:
        return _vi_digits(s)
    return vi_number(int(s))


def _vi_fraction(s: str) -> str:
    zeros = len(s) - len(s.lstrip("0"))
    rest = s[zeros:]
    parts = ["không"] * zeros
    if rest:
        parts.append(vi_number(int(rest)) if len(rest) <= 3 else _vi_digits(rest))
    return " ".join(parts)


def vi_numstr(s: str) -> str:
    """Read a Vietnamese-formatted number: '1.500.000', '3,5', '0,05'."""
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", s):
        int_part, _, frac = s.replace(".", "").partition(",")
    else:
        m = re.fullmatch(r"(\d+)(?:[.,](\d+))?", s)
        if not m:
            return s
        int_part, frac = m.group(1), m.group(2) or ""
    words = _vi_int_str(int_part)
    if frac:
        words += " phẩy " + _vi_fraction(frac)
    return words


# ---------------------------------------------------------------------------
# English number reading
# ---------------------------------------------------------------------------
_EN_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
            "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
            "seventeen", "eighteen", "nineteen"]
_EN_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
_EN_SCALES = ["", "thousand", "million", "billion", "trillion", "quadrillion"]


def _en_below_1000(n: int) -> str:
    out = []
    if n >= 100:
        out.append(_EN_ONES[n // 100] + " hundred")
        n %= 100
    if n >= 20:
        out.append(_EN_TENS[n // 10] + ("-" + _EN_ONES[n % 10] if n % 10 else ""))
    elif n:
        out.append(_EN_ONES[n])
    return " ".join(out)


def en_number(n: int) -> str:
    """Read an integer in English: 1500 -> 'one thousand five hundred'."""
    if n < 0:
        return "minus " + en_number(-n)
    if n < 20:
        return _EN_ONES[n]
    words = []
    pos = 0
    while n:
        g = n % 1000
        if g:
            if pos >= len(_EN_SCALES):
                return " ".join(_EN_ONES[int(c)] for c in str(n))
            words.insert(0, (_en_below_1000(g) + " " + _EN_SCALES[pos]).strip())
        n //= 1000
        pos += 1
    return " ".join(words)


def en_year(n: int) -> str:
    """Read a year: 1999 -> 'nineteen ninety-nine', 2026 -> 'twenty twenty-six'."""
    if 2000 <= n <= 2009 or n % 1000 == 0 or not 1000 <= n <= 9999:
        return en_number(n)
    hi, lo = divmod(n, 100)
    if lo == 0:
        return en_number(hi) + " hundred"
    return en_number(hi) + " " + ("oh " + _EN_ONES[lo] if lo < 10 else en_number(lo))


_EN_ORD_IRREGULAR = {"one": "first", "two": "second", "three": "third", "five": "fifth",
                     "eight": "eighth", "nine": "ninth", "twelve": "twelfth"}


def en_ordinal(n: int) -> str:
    """1 -> 'first', 21 -> 'twenty-first', 40 -> 'fortieth'."""
    words = en_number(n)
    m = re.search(r"([a-z]+)$", words)
    last = m.group(1)
    if last in _EN_ORD_IRREGULAR:
        new = _EN_ORD_IRREGULAR[last]
    elif last.endswith("y"):
        new = last[:-1] + "ieth"
    else:
        new = last + "th"
    return words[: m.start()] + new


def _en_digits(s: str) -> str:
    return " ".join(_EN_ONES[int(c)] for c in s)


def en_numstr(s: str) -> str:
    """Read an English-formatted number: '1,500,000', '3.14'."""
    m = re.fullmatch(r"(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?", s)
    if not m:
        return s
    int_part = m.group(1).replace(",", "")
    if (len(int_part) >= 4 and int_part.startswith("0")) or len(int_part) > 15:
        words = _en_digits(int_part)
    else:
        words = en_number(int(int_part))
    if m.group(2):
        words += " point " + _en_digits(m.group(2))
    return words


def number_to_words(n: int | str, language: Language) -> str:
    """Public helper: number (int or formatted string) to words for vi/en."""
    s = str(n)
    neg = s.startswith("-")
    s = s.lstrip("-")
    if language == Language.VI:
        w = vi_numstr(s)
        return ("âm " + w) if neg else w
    if language == Language.EN:
        w = en_numstr(s)
        return ("minus " + w) if neg else w
    return str(n)


# ---------------------------------------------------------------------------
# Generic cleanup (all languages)
# ---------------------------------------------------------------------------
_URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>\"']+", re.I)
_EMAIL_RE = re.compile(r"(?<![\w.+-])([\w.+-]+)@([\w-]+(?:\.[\w-]+)+)")
_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF☀-➿⬀-⯿\U0001F1E6-\U0001F1FF"
    "︎️⃣\U000E0020-\U000E007F]|‍")
_ZERO_WIDTH_RE = re.compile("[​‌⁠﻿­]")
_SPACES_RE = re.compile("[ \t  -   　\f\v]+")
_BULLET_RE = re.compile(r"^[ \t]*[-•*+·▪►‣◦]\s+", re.M)
_FULLWIDTH = {cp: cp - 0xFEE0 for r in ((0xFF10, 0xFF19), (0xFF21, 0xFF3A), (0xFF41, 0xFF5A))
              for cp in range(r[0], r[1] + 1)}


def clean_text(text: str) -> str:
    """NFC, strip emoji/zero-width/URLs/bullets, normalize whitespace (keeps newlines)."""
    text = unicodedata.normalize("NFC", text or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n").translate(_FULLWIDTH)
    text = _ZERO_WIDTH_RE.sub("", text)
    text = _EMOJI_RE.sub(" ", text)

    def _url(m: re.Match) -> str:
        url = m.group(0)
        trail = len(url) - len(url.rstrip(".,;:!?)]}"))
        return " " + url[len(url) - trail:] if trail else " "

    text = _URL_RE.sub(_url, text)
    text = _BULLET_RE.sub("", text)
    return _tidy(text)


def _tidy(text: str) -> str:
    text = _SPACES_RE.sub(" ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"(?<=\w) +([,.;:!?…)\]}”’»])", r"\1", text)  # "word ," -> "word,"
    text = re.sub(r"([(\[{“‘«]) +", r"\1", text)
    return text.strip(" ")


def _sub_padded(pattern: re.Pattern, func: Callable[[re.Match], str], text: str) -> str:
    """re.sub that adds a space if the replacement would glue onto a letter/digit."""
    out, last = [], 0
    for m in pattern.finditer(text):
        rep = func(m)
        if rep is None:
            continue
        out.append(text[last:m.start()])
        prev = text[m.start() - 1:m.start()]
        if prev and prev.isalnum() and rep[:1].isalnum():
            rep = " " + rep
        nxt = text[m.end():m.end() + 1]
        if nxt and nxt.isalnum() and rep[-1:].isalnum():
            rep += " "
        out.append(rep)
        last = m.end()
    out.append(text[last:])
    return "".join(out)


def _abbrev(text: str, table: list[tuple[str, str, bool]]) -> str:
    """Apply (regex, replacement, terminal) abbreviations.

    A terminal abbreviation ending with '.' keeps a period when it closes a
    sentence (followed by end of line or a capitalized word).
    """
    for pat, rep, terminal in table:
        def _f(m: re.Match, rep=rep, terminal=terminal) -> str:
            if terminal and m.group(0).endswith("."):
                rest = m.string[m.end():]
                nxt = rest.lstrip(" ")
                if not nxt or nxt[0] == "\n" or (nxt[0].isupper() and rest[:1] == " "):
                    return rep + "."
            return rep
        text = re.sub(pat, _f, text)
    return text


# ---------------------------------------------------------------------------
# Vietnamese
# ---------------------------------------------------------------------------
_NUM_VI = r"\d{1,3}(?:\.\d{3})+(?!\d)(?:,\d+)?|\d+(?:[.,]\d+)?"
_NUM_EN = r"\d{1,3}(?:,\d{3})+(?!\d)(?:\.\d+)?|\d+(?:\.\d+)?"
_NB = r"(?<![\w.,])"  # number may not be glued to a preceding letter/number
_TIME_RANGE_VI = r"(?<![\d.,:])(\d{1,2}(?:[:hH]\d{2}|[hH]))\s?[-–]\s?(\d{1,2}(?:[:hH]\d{2}|[hH](?!\w)))(?![\d:])"
_TIME_RANGE_EN = r"(?<![\d.,:])(\d{1,2}:\d{2})\s?[-–]\s?(\d{1,2}:\d{2})(?![\d:])"

_VI_ABBREV: list[tuple[str, str, bool]] = [
    (r"(?<!\w)T[Pp]\.? ?HCM(?!\w)", "thành phố Hồ Chí Minh", False),
    (r"(?<!\w)T[Pp]\. ?(?=[A-ZĐÀ-Ỹ])", "thành phố ", False),
    (r"(?<!\w)HCM(?!\w)", "Hồ Chí Minh", False),
    (r"(?<!\w)v\.v\.(?:\.\.)?|(?<!\w)vv\.", "vân vân", True),
    (r"(?<!\w)PGS\. ?", "phó giáo sư ", False),
    (r"(?<!\w)GS\. ?", "giáo sư ", False),
    (r"(?<!\w)ThS\. ?", "thạc sĩ ", False),
    (r"(?<!\w)TS\. ?", "tiến sĩ ", False),
    (r"(?<!\w)BS\. ?", "bác sĩ ", False),
    (r"(?<!\w)KS\. ?", "kỹ sư ", False),
    (r"(?<!\w)UBND(?!\w)", "ủy ban nhân dân", False),
    (r"(?<!\w)HĐND(?!\w)", "hội đồng nhân dân", False),
    (r"(?<!\w)THPT(?!\w)", "trung học phổ thông", False),
    (r"(?<!\w)THCS(?!\w)", "trung học cơ sở", False),
    (r"(?<!\w)ĐH(?!\w)", "đại học", False),
    (r"(?<!\w)CLB(?!\w)", "câu lạc bộ", False),
    (r"(?<!\w)HLV(?!\w)", "huấn luyện viên", False),
    (r"(?<!\w)SĐT(?!\w)", "số điện thoại", False),
    (r"(?<!\w)TNHH(?!\w)", "trách nhiệm hữu hạn", False),
    (r"(?<!\w)NXB(?!\w)", "nhà xuất bản", False),
    (r"(?<!\w)LHQ(?!\w)", "Liên Hợp Quốc", False),
    (r"(?<!\w)VN(?!\w)", "Việt Nam", False),
    (r"(?<!\w)[Cc]ty(?!\w)", "công ty", False),
    (r"(?<!\w)[Kk]o(?!\w)", "không", False),
    (r"(?<!\w)[Đđ]c(?!\w)", "được", False),
    (r"(?<!\w)[Tt]rc(?!\w)", "trước", False),
]

_VI_UNITS = {
    "km/h": "ki lô mét trên giờ", "m/s": "mét trên giây", "km²": "ki lô mét vuông",
    "km2": "ki lô mét vuông", "m²": "mét vuông", "m2": "mét vuông", "m³": "mét khối",
    "m3": "mét khối", "cm²": "xen ti mét vuông", "km": "ki lô mét", "cm": "xen ti mét",
    "mm": "mi li mét", "m": "mét", "kg": "ki lô gam", "mg": "mi li gam", "g": "gam",
    "ml": "mi li lít", "l": "lít", "ha": "héc ta", "°C": "độ C", "°F": "độ F", "°": "độ",
    "kWh": "ki lô oát giờ", "kW": "ki lô oát", "W": "oát", "GB": "gi ga bai",
    "MB": "mê ga bai", "TB": "tê ra bai", "KB": "ki lô bai", "GHz": "gi ga héc",
    "MHz": "mê ga héc", "Hz": "héc", "mAh": "mi li am pe giờ",
}
_VI_CURRENCY_AFTER = [
    (r"đ|₫|VNĐ|VND|vnđ|vnd|đồng", "đồng"), (r"\$|USD|usd", "đô la"), (r"€|EUR|euro", "ơ rô"),
    (r"£|GBP", "bảng Anh"), (r"₩|KRW|won", "uôn"), (r"¥|JPY|yên", "yên"),
    (r"元|CNY|RMB|tệ", "nhân dân tệ"),
]
_VI_CURRENCY_BEFORE = [("$", "đô la"), ("€", "ơ rô"), ("£", "bảng Anh"), ("₩", "uôn"), ("¥", "yên")]


def _vi_month(m: int) -> str:
    return "tư" if m == 4 else vi_number(m)


def _preceded_by(text: str, pos: int, words: str) -> bool:
    return re.search(r"(?i)(?:^|[^\w])(?:" + words + r")\s*$", text[:pos]) is not None


def _vi_date(day: int, month: int, year: int | None, text: str, pos: int) -> str:
    parts = []
    if not _preceded_by(text, pos, "ngày|mùng|mồng|hôm"):
        parts.append("ngày")
    parts += [vi_number(day), "tháng", _vi_month(month)]
    if year is not None:
        parts += ["năm", vi_number(year)]
    return " ".join(parts)


def _valid_date(d: int, m: int) -> bool:
    return 1 <= d <= 31 and 1 <= m <= 12


def _normalize_vi(text: str) -> str:
    text = _EMAIL_RE.sub(lambda m: f"{m.group(1).replace('.', ' chấm ')} a còng {m.group(2).replace('.', ' chấm ')}", text)
    text = _abbrev(text, _VI_ABBREV)
    text = re.sub(_TIME_RANGE_VI, r"\1 đến \2", text)  # 8h-9h30, 10:00-11:30
    text = re.sub(r"(?<=[^\W\d_])-(?=\d)", " ", text)  # COVID-19 -> COVID 19

    # Dates: dd/mm/yyyy (also '-' or '.'), ISO yyyy-mm-dd, mm/yyyy, dd/mm.
    def full_date(m: re.Match):
        d, mo, y = int(m.group(1)), int(m.group(3)), int(m.group(4))
        return _vi_date(d, mo, y, m.string, m.start()) if _valid_date(d, mo) else None
    text = _sub_padded(re.compile(r"(?<![\d.,/])(\d{1,2})([/.-])(\d{1,2})\2(\d{4})(?![\d/])"),
                       full_date, text)

    def iso_date(m: re.Match):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return _vi_date(d, mo, y, m.string, m.start()) if _valid_date(d, mo) else None
    text = _sub_padded(re.compile(r"(?<![\d.,/-])(\d{4})-(\d{2})-(\d{2})(?![\d-])"), iso_date, text)

    def month_year(m: re.Match):
        mo, y = int(m.group(1)), int(m.group(2))
        if not 1 <= mo <= 12:
            return None
        lead = "" if _preceded_by(m.string, m.start(), "tháng") else "tháng "
        return f"{lead}{_vi_month(mo)} năm {vi_number(y)}"
    text = _sub_padded(re.compile(r"(?<![\d.,/])(\d{1,2})/(\d{4})(?![\d/])"), month_year, text)

    def day_month(m: re.Match):
        a, b = int(m.group(1)), int(m.group(2))
        keyword = _preceded_by(m.string, m.start(), "ngày|mùng|mồng|hôm|sáng|trưa|chiều|tối|đêm|từ|đến|tới|vào")
        if not keyword and 0 < a < b <= 4:
            return f"{vi_number(a)} phần {vi_number(b)}"
        if _valid_date(a, b):
            return _vi_date(a, b, None, m.string, m.start())
        return f"{vi_number(a)} trên {vi_number(b)}"
    text = _sub_padded(re.compile(r"(?<![\d.,/])(\d{1,2})/(\d{1,2})(?![\d/])"), day_month, text)

    # Times: 14:30, 14h30, 14:30:15, 8h (time ranges first: 10:00-11:30)
    def clock(m: re.Match):
        h, mi = int(m.group(1)), int(m.group(2))
        if h > 24 or mi > 59:
            return None
        out = f"{vi_number(h)} giờ"
        if mi:
            out += f" {vi_number(mi)} phút"
        if m.group(3) and int(m.group(3)) < 60:
            out += f" {vi_number(int(m.group(3)))} giây"
        return out
    text = _sub_padded(re.compile(r"(?<![\d.,:])(\d{1,2})[:hH](\d{2})(?::(\d{2}))?(?![\d:])"), clock, text)
    text = _sub_padded(re.compile(r"(?<![\w.,:])(\d{1,2})[hH](?!\w)"),
                       lambda m: f"{vi_number(int(m.group(1)))} giờ" if int(m.group(1)) <= 24 else None, text)

    # Ordinals and ranges
    text = re.sub(r"(?i)\b(thứ|hạng|lần thứ)\s+1(?!\d)", lambda m: m.group(1) + " nhất", text)
    text = re.sub(r"(?i)\b(thứ)\s+4(?!\d)", lambda m: m.group(1) + " tư", text)
    text = re.sub(r"(?<![\w.,/:-])([1-9]\d{0,3})\s?[-–]\s?([1-9]\d{0,3})(?!\d|[.,/:-]\d)",
                  r"\1 đến \2", text)

    # Shorthand: 50k -> 50 nghìn, 5tr -> 5 triệu
    text = re.sub(_NB + r"(\d+(?:[.,]\d+)?) ?k(?!\w)", r"\1 nghìn", text)
    text = re.sub(_NB + r"(\d+(?:[.,]\d+)?) ?tr(?!\w)", r"\1 triệu", text)

    # Currency, percent, units (keep digits; the general number rule reads them)
    for sym, word in _VI_CURRENCY_BEFORE:
        text = re.sub(re.escape(sym) + r" ?(" + _NUM_VI + ")", r"\1 " + word, text)
    for pat, word in _VI_CURRENCY_AFTER:
        text = re.sub(_NB + "(" + _NUM_VI + r") ?(?:" + pat + r")(?!\w)", r"\1 " + word, text)
    text = re.sub(_NB + "(" + _NUM_VI + r") ?%", r"\1 phần trăm", text)
    text = text.replace("%", " phần trăm")
    units = "|".join(re.escape(u) for u in sorted(_VI_UNITS, key=len, reverse=True))
    text = re.sub(_NB + "(" + _NUM_VI + r") ?(" + units + r")(?![\w/²³])",
                  lambda m: f"{m.group(1)} {_VI_UNITS[m.group(2)]}", text)

    # Negative numbers, then every remaining number
    text = re.sub(r"(?<![\w)\]])-(?=\d)", "âm ", text)
    text = _sub_padded(re.compile(r"(?<![^\W\d_])(?<![\d.,])(" + _NUM_VI + r")"),
                       lambda m: vi_numstr(m.group(1)), text)

    # "đồng/tháng", "km/giờ" -> "trên"
    text = re.sub(r"\b(đồng|la|nghìn|triệu|tỷ|mét|gam|lít|tấn|giờ|uôn|yên|tệ|trăm|rô) ?/ ?(?=\w)",
                  r"\1 trên ", text)

    # Symbols
    text = re.sub(r" ?& ?", " và ", text)
    text = re.sub(r"[~≈] ?(?=\w)", "khoảng ", text)
    text = re.sub(r"#(?=\s?\w)", "số ", text)
    text = text.replace("@", " a còng ")
    return text


# ---------------------------------------------------------------------------
# English
# ---------------------------------------------------------------------------
_EN_ABBREV: list[tuple[str, str, bool]] = [
    (r"\bMr\.", "Mister", False), (r"\bMrs\.", "Missus", False), (r"\bMs\.", "Miss", False),
    (r"\bDr\.", "Doctor", False), (r"\bProf\.", "Professor", False),
    (r"\bvs\.", "versus", False), (r"\be\.g\.", "for example", False),
    (r"\bi\.e\.", "that is", False), (r"\betc\.", "et cetera", True),
    (r"\bapprox\.", "approximately", False), (r"\bNo\. ?(?=\d)", "number ", False),
]
_EN_UNITS = {
    "km/h": "kilometers per hour", "mph": "miles per hour", "m/s": "meters per second",
    "km²": "square kilometers", "m²": "square meters", "km": "kilometers", "cm": "centimeters",
    "mm": "millimeters", "m": "meters", "kg": "kilograms", "mg": "milligrams", "g": "grams",
    "ml": "milliliters", "l": "liters", "lbs": "pounds", "lb": "pounds", "oz": "ounces",
    "ft": "feet", "°C": "degrees Celsius", "°F": "degrees Fahrenheit", "°": "degrees",
    "kWh": "kilowatt hours", "kW": "kilowatts", "GB": "gigabytes", "MB": "megabytes",
    "TB": "terabytes", "KB": "kilobytes", "GHz": "gigahertz", "MHz": "megahertz", "Hz": "hertz",
}
_EN_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
              "September", "October", "November", "December"]
_EN_CURRENCY = {"$": ("dollar", "dollars", "cent", "cents"), "€": ("euro", "euros", "cent", "cents"),
                "£": ("pound", "pounds", "penny", "pence"), "¥": ("yen", "yen", "", ""),
                "₩": ("won", "won", "", ""), "₫": ("dong", "dong", "", "")}


def _singular(unit: str) -> str:
    if unit == "feet":
        return "foot"
    if unit.startswith("degrees"):
        return "degree" + unit[7:]
    words = unit.split(" ")
    if words[0].endswith("s") and len(words) > 1 and words[1] == "per":
        words[0] = words[0][:-1]
    elif words[-1].endswith("s") and not words[-1].endswith("ss"):
        words[-1] = words[-1][:-1]
    return " ".join(words)


def _en_date(mo: int, d: int, y: int | None) -> str:
    out = f"{_EN_MONTHS[mo - 1]} {en_ordinal(d)}"
    return out + (f", {en_year(y)}" if y is not None else "")


def _en_money(sym: str, num: str) -> str:
    one, many, sub1, subn = _EN_CURRENCY[sym]
    int_part, _, frac = num.replace(",", "").partition(".")
    n = int(int_part)
    out = f"{en_number(n)} {one if n == 1 else many}"
    if frac and sub1 and len(frac) <= 2:
        c = int(frac.ljust(2, "0"))
        if c:
            out += f" and {en_number(c)} {sub1 if c == 1 else subn}"
    elif frac:
        out = f"{en_numstr(num.replace(',', ''))} {many}"
    return out


def _normalize_en(text: str) -> str:
    text = _EMAIL_RE.sub(lambda m: f"{m.group(1).replace('.', ' dot ')} at {m.group(2).replace('.', ' dot ')}", text)
    text = _abbrev(text, _EN_ABBREV)
    text = re.sub(_TIME_RANGE_EN, r"\1 to \2", text)
    text = re.sub(r"(?<=[^\W\d_])-(?=\d)", " ", text)

    def us_date(m: re.Match):
        a, b, y = int(m.group(1)), int(m.group(3)), int(m.group(4))
        mo, d = (b, a) if a > 12 else (a, b)
        return _en_date(mo, d, y) if _valid_date(d, mo) else None
    text = _sub_padded(re.compile(r"(?<![\d.,/])(\d{1,2})([/.-])(\d{1,2})\2(\d{4})(?![\d/])"), us_date, text)

    def iso(m: re.Match):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return _en_date(mo, d, y) if _valid_date(d, mo) else None
    text = _sub_padded(re.compile(r"(?<![\d.,/-])(\d{4})-(\d{2})-(\d{2})(?![\d-])"), iso, text)

    def clock(m: re.Match):
        h, mi = int(m.group(1)), int(m.group(2))
        if h > 24 or mi > 59:
            return None
        if mi == 0:
            out = en_number(h) + (" o'clock" if not m.group(3) else "")
        elif mi < 10:
            out = f"{en_number(h)} oh {en_number(mi)}"
        else:
            out = f"{en_number(h)} {en_number(mi)}"
        if m.group(3):
            out += " " + ("a m" if m.group(3)[0].lower() == "a" else "p m")
        return out
    ampm = r"(?:\s?([AaPp]\.?[Mm]\.?)(?!\w))?"
    text = _sub_padded(re.compile(r"(?<![\d.,:])(\d{1,2}):(\d{2})" + ampm + r"(?![\d:])"), clock, text)
    text = _sub_padded(re.compile(r"(?<![\w.,:])(\d{1,2})\s?([AaPp]\.?[Mm]\.?)(?!\w)"),
                       lambda m: f"{en_number(int(m.group(1)))} {'a m' if m.group(2)[0] in 'Aa' else 'p m'}",
                       text)

    text = re.sub(r"(?i)\b(in|since|by|from|until|till|year|of|before|after|circa)\s+(\d{4})s?\b",
                  lambda m: f"{m.group(1)} {en_year(int(m.group(2)))}"
                  + ("s" if m.group(0).endswith("s") and not m.group(0).lower().endswith("ys") else ""),
                  text)
    text = re.sub(r"(?<![\w.,/:-])([1-9]\d{0,3})\s?[-–]\s?([1-9]\d{0,3})(?!\d|[.,/:-]\d)", r"\1 to \2", text)
    text = _sub_padded(re.compile(r"(?<![\w.,])(\d+)(?:st|nd|rd|th)(?!\w)"),
                       lambda m: en_ordinal(int(m.group(1))), text)

    for sym in _EN_CURRENCY:
        text = _sub_padded(re.compile(re.escape(sym) + r" ?(" + _NUM_EN + r")"),
                           lambda m, s=sym: _en_money(s, m.group(1)), text)
    text = re.sub(_NB + "(" + _NUM_EN + r") ?(?:USD)(?!\w)", r"\1 dollars", text)
    text = re.sub(_NB + "(" + _NUM_EN + r") ?(?:VND|VNĐ|đ)(?!\w)", r"\1 dong", text)
    text = re.sub(_NB + "(" + _NUM_EN + r") ?%", r"\1 percent", text)
    text = text.replace("%", " percent")
    units = "|".join(re.escape(u) for u in sorted(_EN_UNITS, key=len, reverse=True))
    text = re.sub(_NB + "(" + _NUM_EN + r") ?(" + units + r")(?![\w/²³])",
                  lambda m: f"{m.group(1)} " + (_singular(_EN_UNITS[m.group(2)]) if m.group(1) == "1"
                                                else _EN_UNITS[m.group(2)]), text)

    text = re.sub(r"(?<![\w)\]])-(?=\d)", "minus ", text)
    text = _sub_padded(re.compile(r"(?<![^\W\d_])(?<![\d.,])(" + _NUM_EN + r")"),
                       lambda m: en_numstr(m.group(1)), text)
    text = re.sub(r"\b(dollars?|cents?|euros?|pounds?|meters?|kilometers?|kilograms?|grams?|liters?|miles?)"
                  r" ?/ ?(?=[a-z])", r"\1 per ", text)
    text = re.sub(r" ?& ?", " and ", text)
    text = re.sub(r"[~≈] ?(?=\w)", "about ", text)
    text = re.sub(r"#(?=\s?\d)", "number ", text)
    text = text.replace("@", " at ")
    return text


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def normalize(text: str, language: Language) -> str:
    """Normalize `text` for reading aloud in `language`."""
    text = clean_text(text)
    if language == Language.VI:
        text = _normalize_vi(text)
        text = re.sub(r"[*_]{1,3}", " ", text)
    elif language == Language.EN:
        text = _normalize_en(text)
        text = re.sub(r"[*_]{1,3}", " ", text)
    return _tidy(text)
