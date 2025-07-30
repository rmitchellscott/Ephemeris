from datetime import datetime, date, time
from tempfile import NamedTemporaryFile

import requests
import os
from icalendar import Calendar as iCal
from dateutil import tz as dateutil_tz
from loguru import logger

import ephemeris.settings as settings


def download_calendar(source: str) -> bytes:
    """
    Fetch an ICS calendar from a URL or file path.
    """
    if source.startswith("http"):
        resp = requests.get(source)
        resp.raise_for_status()
        return resp.content
    else:
        with open(source, "rb") as f:
            return f.read()


def parse_calendar(raw: bytes) -> iCal:
    """
    Parse raw ICS bytes into an icalendar.Calendar object.
    """
    return iCal.from_ical(raw)


def build_tz_factory(cal: iCal) -> dateutil_tz.tzical | None:
    """
    Extract VTIMEZONE blocks and build a tzical factory if present.
    """
    vtz_blocks = [comp for comp in cal.walk() if comp.name == "VTIMEZONE"]
    if not vtz_blocks:
        return None

    with NamedTemporaryFile(mode="wb", suffix=".ics", delete=False) as tf:
        for comp in vtz_blocks:
            # strip unsupported X- properties
            for prop in list(comp.keys()):
                if prop.upper().startswith("X-"):
                    comp.pop(prop, None)
            tf.write(comp.to_ical())
        tf.flush()
        return dateutil_tz.tzical(tf.name)


def extract_raw_events(cal: iCal, color: str, name: str) -> list[tuple]:
    """
    Walk VEVENTs, preserving timezone factory and metadata.
    Returns list of tuples: (component, color, tz_factory, name).
    """
    tz_factory = build_tz_factory(cal)
    events = []
    for comp in cal.walk():
        if comp.name != "VEVENT":
            continue
        events.append((comp, color, tz_factory, name))
    return events

def _dtstart_value(comp) -> datetime:
    """
    Convert a component's DTSTART to a timezone-aware datetime:
    - Date-only values become midnight local-time
    - Naive datetimes get local tzinfo attached
    """
    raw = comp.decoded("dtstart")
    # Date-only => combine to midnight
    if isinstance(raw, date) and not isinstance(raw, datetime):
        raw = datetime.combine(raw, time.min)
    # Attach local tzinfo if missing
    if raw.tzinfo is None:
        raw = raw.replace(tzinfo=settings.TZ_LOCAL)
    return raw

def load_raw_events(sources: list[dict]) -> list[tuple]:
    """
    High-level loader: for each calendar entry, download, parse,
    and extract VEVENTs with VTIMEZONE support.
    """
    all_events = []
    names = [entry.get("name", "<unknown>") for entry in sources]
    logger.debug("Loading {} calendars: {}", len(names), names)
    for entry in sources:
        name = entry.get("name")
        color = entry.get("color", "black")
        source = entry.get("source")
        if os.path.isdir(source):
            logger.debug("Source {} is a directory; scanning for .ics files...", source)
            for filename in os.listdir(source):
                if not filename.lower().endswith(".ics"):
                    continue
                file_path = os.path.join(source, filename)
                logger.debug("  Found ICS file: {}", file_path)
                raw = download_calendar(file_path)
                cal = parse_calendar(raw)
                all_events.extend(extract_raw_events(cal, color, name))
            continue
        logger.debug("Fetching calendar {} from {}...", name, source)
        raw = download_calendar(source)
        cal = parse_calendar(raw)
        all_events.extend(extract_raw_events(cal, color, name))


    # Sort by dtstart, normalized to timezone-aware datetimes
    return sorted(
        all_events,
        key=lambda x: _dtstart_value(x[0])
    )
