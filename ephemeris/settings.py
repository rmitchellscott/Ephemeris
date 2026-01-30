import os
import re
from dateutil import tz
from datetime import datetime, date
from pathlib import Path
from loguru import logger

# Date/time  helpers
def today_date():
    return date.today()

def default_date_range():
    return [today_date()]

def _parse_hour(raw: str, use_24h: bool) -> int:
    """
    Parse a human–friendly hour string into 0–23.
      - If it ends with AM/PM, A/P, or with dots (e.g. “6 a.m.”), parse as 12-hour.
      - Otherwise, if use_24h, parse as a bare integer hour.
      - Otherwise (12-hour mode with no suffix) raise an error.
    """
    s = raw.strip()
    # normalize: remove dots and spaces around suffix
    s_norm = re.sub(r'\.', '', s).replace(' ', '')
    # look for a/p or am/pm at very end
    m = re.search(r'(?i)([ap](?:m)?)$', s_norm)
    if m:
        suffix = m.group(1).lower()
        # turn “a” → “am”, “p” → “pm”
        if suffix in ('a', 'p'):
            suffix += 'm'
        base = s_norm[:m.start(1)]
        candidate = (base + suffix).upper()
        # try H PM then H:MM PM
        for fmt in ("%I%p", "%I:%M%p"):
            try:
                return datetime.strptime(candidate, fmt).hour
            except ValueError:
                continue
        logger.error("Cannot parse 12h time from '{}'.", raw)
        raise ValueError(f"Cannot parse 12h time from '{raw}'")
    # no a/p or am/pm suffix
    try:
        hour = int(s)
    except ValueError:
        logger.error("Non-integer hour when parsing 24-hour input: {!r}", raw)
        raise ValueError(f"Invalid hour format: '{raw}'")
    if not (0 <= hour < 24):
        logger.error("24-hour hour out of range [0–23]: {!r}", raw)
        raise ValueError(f"24-h hour out of range: '{raw}'")
    return hour


# Project root
BASE_DIR = Path(__file__).resolve().parent.parent

# File paths
CONFIG_PATH  = Path(os.getenv("APP_CONFIG_PATH", str(BASE_DIR / "config.yaml")))
META_FILE    = Path(os.getenv("APP_META_FILE_PATH", str(BASE_DIR / "feeds_meta.yaml")))
OUTPUT_PDF   = os.getenv("APP_OUTPUT_PDF_PATH", "output/ephemeris.pdf")
OUTPUT_PNG   = os.getenv("APP_OUTPUT_PNG_DIR", "output/png")
OUTPUT_PNG_BG   = os.getenv("APP_OUTPUT_BG_PNG_DIR", "output/png_background")
OUTPUT_PNG_TEXT = os.getenv("APP_OUTPUT_TEXT_PNG_DIR", "output/png_text")
SEPARATE_TEXT   = os.getenv("DOC_SEPARATE_TEXT", "false").lower() in ("1", "true", "yes")
DEFAULT_COVER = os.getenv("DOC_COVER_SVG_PATH", str(BASE_DIR / "assets/cover.svg"))
FONTS_DIR = BASE_DIR / "fonts"

TIMEZONE = os.getenv("TZ", os.getenv("TIME_ZONE", "UTC"))
DATE_RANGE = os.getenv("TIME_DATE_RANGE", "today")
TIME_FORMAT    = os.getenv("TIME_FORMAT", "24")
USE_24H        = TIME_FORMAT == "24"

_raw_start = os.getenv("TIME_DISPLAY_START", "6")
_raw_end   = os.getenv("TIME_DISPLAY_END",   "21")
_raw_exclude_before = os.getenv("TIME_FILTER_MIN_HOUR", "0")


TZ_LOCAL = tz.gettz(TIMEZONE) or tz.tzutc()
START_HOUR = _parse_hour(_raw_start, USE_24H)
END_HOUR   = _parse_hour(_raw_end,   USE_24H)
EXCLUDE_BEFORE = _parse_hour(_raw_exclude_before, USE_24H)

FORMAT       = os.getenv("APP_OUTPUT_FORMAT", "pdf").lower()
COVER_PAGE   = os.getenv("DOC_COVER_ENABLED", "true").lower() not in ("0","false","no")
CONVERT_OFFGRID_TO_ALLDAY = os.getenv("DOC_OVERFLOW_TO_ALLDAY", "true").lower() not in ("0","false","no")
CREATE_LINKS = os.getenv("DOC_MINICAL_LINKS", "true").lower() not in ("0","false","no")
INDICATE_DAYS = os.getenv("DOC_MINICAL_INDICATE_RANGE", "true").lower() not in ("0","false","no")

ALLDAY_MODE = os.getenv("DOC_ALLDAY_MODE", "band").lower()
DRAW_ALL_DAY_BAND  = ALLDAY_MODE == "band"
ALLDAY_IN_GRID     = ALLDAY_MODE == "in-grid"
DRAW_ALL_DAY       = ALLDAY_MODE in ("band", "in-grid")

SHOW_TIME = os.getenv("DOC_SHOW_TIME", "true").lower() in ("1", "true", "yes")
SHOW_LOCATION = os.getenv("DOC_SHOW_LOCATION", "false").lower() in ("1", "true", "yes")
FIRST_LINE = os.getenv("DOC_FIRST_LINE", "time").lower()

# Color defaults
MONOCHROME      = os.getenv("DOC_MONOCHROME", "false").lower() in ("1", "true", "yes")
ANTIALIAS       = os.getenv("DOC_ANTIALIAS", "true").lower() in ("1", "true", "yes")
EVENT_FILL      = os.getenv("DOC_EVENT_FILL_COLOR", "gray14")
EVENT_STROKE    = os.getenv("DOC_EVENT_BORDER_COLOR", "gray(20%)")
GRIDLINE_COLOR  = os.getenv("DOC_GRID_LINE_COLOR", "gray(20%)")
FOOTER_COLOR    = os.getenv("DOC_FOOTER_COLOR", "gray(60%)")

# Page layout
PDF_MARGIN_LEFT   = float(os.getenv("DOC_MARGIN_LEFT", 6))
PDF_MARGIN_RIGHT  = float(os.getenv("DOC_MARGIN_RIGHT", 6))
PDF_MARGIN_TOP    = float(os.getenv("DOC_MARGIN_TOP", 9))
PDF_MARGIN_BOTTOM = float(os.getenv("DOC_MARGIN_BOTTOM", 6))
MINICAL_ALIGN = os.getenv("DOC_MINICAL_ALIGN", "right").lower()
MINICAL_HEIGHT   = float(os.getenv("DOC_MINICAL_HEIGHT", 60))
MINICAL_GAP = float(os.getenv("DOC_MINICAL_SPACING", 10))
ALLDAY_FROM   = os.getenv("DOC_ALLDAY_BOUNDARY",   "grid").lower()
MINICAL_TEXT_PADDING= float(os.getenv("DOC_MINICAL_TEXT_PADDING", 5))
MINICAL_OFFSET = float(os.getenv("DOC_MINICAL_POSITION_OFFSET", 0))
PDF_GRID_BOTTOM_BUFFER = float(os.getenv("DOC_GRID_BOTTOM_PADDING", 9))
minical_mode = os.getenv("DOC_MINICAL_MODE", "full").strip().lower()
DRAW_MINICALS = minical_mode not in ("false", "0", "no", "disabled", "disable")
PDF_PAGE_SIZE= os.getenv("DOC_PAGE_DIMENSIONS", "1404x1872")  # Default to reMarkable 2
PDF_DPI = float(os.getenv("DOC_PAGE_DPI", "226")) 
FOOTER = os.getenv("DOC_FOOTER_TEXT", "E P H E M E R I S")

# Behavior
_raw_blocked_words = os.getenv("APP_FILTER_LIST", "cancelled,canceled")
FILTER_BLOCKED_WORDS = tuple(w.strip().lower() for w in _raw_blocked_words.split(","))
FORCE_REFRESH = os.getenv("APP_FORCE_REFRESH", "false").lower() in ("1", "true", "yes")
POST_HOOK = os.getenv("APP_POST_HOOK")
_raw_filter_declined_emails = os.getenv("APP_FILTER_DECLINED_EMAILS", "")
FILTER_DECLINED_EMAILS = tuple(e.strip().lower() for e in _raw_filter_declined_emails.split(",") if e.strip())

# Cover
COVER_WIDTH_FRAC = float(os.getenv("DOC_COVER_WIDTH_SCALE", 0.75))
COVER_VERT_FRAC = float(os.getenv("DOC_COVER_VERTICAL_POSITION", 0.25))
