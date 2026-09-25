"""
callforge/runtime/tools.py
==========================
Dynamic Tool Execution Engine for Voice Agents.
Integrates live Google Spreadsheets / Webhooks for real-time appointment booking,
calendar availability checking, and client detail capture during phone calls.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
import logging
import re
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

# Intent regexes for appointment queries & booking
_BOOKING_INTENT_PATTERNS = [
    r"\b(?:book|booking|schedule|reschedule|reserve)\s+(?:an?\s+)?(?:appointment|slot|session|meeting|call|consultation|doctor|therapist|counselor)\b",
    r"\b(?:book|booking|schedule|reschedule|reserve)\s+(?:for\s+)?(?:today|tomorrow|day after tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    r"\b(?:book|schedule|reserve)\s+(?:me\s+)?(?:a\s+)?(?:slot|time|appointment)\b",
    r"\b(?:available|open)\s+(?:slots?|timings?|times?)\b",
    r"\bfree\s+(?:slots?|timings?)\b",
    r"\b(?:slots?|timings?)\s+(?:available|open|free)\b",
    r"\b(?:slots?|timings?|times?)\s+(?:for|of)?\s*(?:booking|appointment)\b",
    r"\b(?:booking|appointment)\s+(?:slots?|timings?|times?|availability)\b",
    r"\b(?:check|see|know|get)\s+(?:the\s+)?(?:availability|available\s+slots?|open\s+slots?|free\s+slots?|timings?)\b",
    r"\b(?:any\s+)?(?:slots?|timings?)\s+(?:available|open|free)\b",
    r"\b(?:want|like|need)\s+to\s+(?:book|schedule|reserve|make\s+an?\s+appointment)\b",
    r"\b(?:can\s+i|could\s+i)\s+(?:book|schedule|get\s+an?\s+appointment)\b",
    r"\b(?:what\s+are\s+the|what\s+time|when\s+are\s+the|are\s+there\s+any)\s+(?:available|open|free)?\s*(?:slots?|timings?|times?)\b",
    r"\b(?:appointment|slot)\s+(?:availability|booking|timings?)\b",
    r"\b(?:अपॉइंटमेंट|स्लॉट)\s+(?:बुक|चाहिए|मिलेगा|खाली|उपलब्ध)\b",
    r"\b(?:बुक|बुकिंग)\s+(?:करना|करनी|कराना|कर दो|कर दीजिए)\b",
    r"\b(?:क्या\s+कोई\s+स्लॉट\s+खाली\s+है)\b",
]
_BOOKING_INTENT_RE = re.compile("|".join(_BOOKING_INTENT_PATTERNS), re.IGNORECASE)

_CANCEL_INTENT_PATTERNS = [
    r"\b(?:no|nope|cancel|stop|never\s*mind|don'?t\s+book|not\s+now|later|leave\s+it|forget\s+it|exit)\b",
    r"\b(?:नहीं|रहने\s*दो|मत\s*करो|कैंसिल|बाद\s*में)\b",
]
_CANCEL_INTENT_RE = re.compile("|".join(_CANCEL_INTENT_PATTERNS), re.IGNORECASE)

_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
    "सोमवार": 0, "मंगलवार": 1, "बुधवार": 2, "गुरुवार": 3,
    "शुक्रवार": 4, "शनिवार": 5, "रविवार": 6,
}


def parse_date_intent(text: str) -> str:
    """Extract a target date (YYYY-MM-DD) from conversational text."""
    now = datetime.now()
    clean = text.lower()

    if "day after tomorrow" in clean or "परसों" in clean:
        return (now + timedelta(days=2)).strftime("%Y-%m-%d")
    if "tomorrow" in clean or "कल" in clean:
        return (now + timedelta(days=1)).strftime("%Y-%m-%d")
    if "today" in clean or "आज" in clean:
        return now.strftime("%Y-%m-%d")

    # Check for weekday name (e.g. "on Friday")
    for day_name, day_idx in _WEEKDAYS.items():
        if day_name in clean:
            current_day = now.weekday()
            days_ahead = (day_idx - current_day) % 7
            if days_ahead == 0:
                days_ahead = 7  # Next week if today
            return (now + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

    # Check for explicit date like 2026-09-25 or 25th September
    iso_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    if iso_match:
        return iso_match.group(1)

    month_match = re.search(
        r"\b(\d{1,2})(?:st|nd|rd|th)?\s*(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b",
        clean,
    )
    if month_match:
        try:
            day = int(month_match.group(1))
            month_str = month_match.group(2)[:3]
            month_num = datetime.strptime(month_str, "%b").month
            year = now.year if (month_num >= now.month) else (now.year + 1)
            return f"{year}-{month_num:02d}-{day:02d}"
        except Exception:
            pass

    # Default to tomorrow if they asked to book without specifying a date
    return (now + timedelta(days=1)).strftime("%Y-%m-%d")


_TIME_SLOT_RE = re.compile(
    r"\b((?:1[0-2]|0?[1-9])(?::[0-5][0-9])?\s*(?:am|pm|a\.m\.|p\.m\.))\b|"
    r"\b((?:1[0-2]|0?[1-9])(?:[0-5][0-9])\s*(?:am|pm|a\.m\.|p\.m\.))\b|"
    r"\b([1-9]|1[0-2])\s*(?:o'clock|baje)\b|"
    r"\b((?:1[0-2]|0?[1-9]):[0-5][0-9])\b",
    re.IGNORECASE,
)

_HOUR_WORD_MAP = {
    "10": ["10", "1000", "10:00", "ten", "das", "dass", "दस"],
    "11": ["11", "1100", "11:00", "eleven", "gyarah", "ग्यारह"],
    "12": ["12", "1200", "12:00", "twelve", "barah", "बारह"],
    "1": ["1", "100", "1:00", "one", "ek", "एक"],
    "2": ["2", "200", "230", "2:00", "2:30", "2.30", "2 30", "two thirty", "two", "do", "dhai", "dhye", "ढाई", "दो"],
    "3": ["3", "300", "3:00", "three", "teen", "तीन"],
    "4": ["4", "400", "4:00", "four", "chaar", "char", "चार"],
    "5": ["5", "500", "5:00", "five", "paanch", "panch", "पांच"],
}

_WORD_TO_DIGIT = {
    "zero": "0", "oh": "0", "o": "0",
    "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "शून्य": "0", "एक": "1", "दो": "2", "तीन": "3", "चार": "4",
    "पाँच": "5", "पांच": "5", "छह": "6", "सात": "7", "आठ": "8", "नौ": "9",
}


def normalize_spoken_digits(text: str) -> str:
    """Convert spoken number words (including double/triple multipliers and Hindi words) to digits."""
    text = re.sub(r"\bdouble\s+([a-zA-Z\u0900-\u097F]+)\b", r"\1 \1", text, flags=re.IGNORECASE)
    text = re.sub(r"\btriple\s+([a-zA-Z\u0900-\u097F]+)\b", r"\1 \1 \1", text, flags=re.IGNORECASE)
    pattern = r"\b(" + "|".join(re.escape(k) for k in _WORD_TO_DIGIT.keys()) + r")\b"
    return re.sub(pattern, lambda m: _WORD_TO_DIGIT[m.group(0).lower()], text, flags=re.IGNORECASE)


def normalize_time_utterance(text: str) -> str:
    """Normalize conversational/STT time formats like '1100 AM', '11am', '10, 00 AM', '10.00 AM' to '10:00 AM'."""
    # 1. 4-digit military time with am/pm: '1100 AM' -> '11:00 AM'
    text = re.sub(
        r"\b(1[0-2]|0?[1-9])([0-5][0-9])\s*(am|pm|a\.m\.|p\.m\.)\b",
        r"\1:\2 \3",
        text,
        flags=re.IGNORECASE,
    )
    # 2. Spaced or punctuated numbers with am/pm: '10, 00 AM', '10.00 AM' -> '10:00 AM'
    text = re.sub(
        r"\b(1[0-2]|0?[1-9])[,.\s]+([0-5][0-9])\s*(am|pm|a\.m\.|p\.m\.)\b",
        r"\1:\2 \3",
        text,
        flags=re.IGNORECASE,
    )
    # 3. Time with attached am/pm: '11am', '12pm' -> '11 am', '12 pm'
    text = re.sub(
        r"\b((?:1[0-2]|0?[1-9])(?::[0-5][0-9])?)\s*(am|pm|a\.m\.|p\.m\.)\b",
        r"\1 \2",
        text,
        flags=re.IGNORECASE,
    )
    return text


_COMMON_NON_NAME_WORDS = {
    "my", "name", "is", "phone", "number", "and", "the", "call", "caller",
    "book", "slot", "please", "for", "yes", "sure", "ok", "okay", "hi", "hello",
    "slots", "available", "appointment", "free", "no", "not", "why", "what", "how",
    "who", "when", "where", "which", "can", "could", "would", "should", "will",
    "sleep", "overthink", "overthinking", "thinking", "stop", "cancel", "help",
    "thanks", "thank", "you", "welcome", "state", "good", "morning", "night",
    "fine", "bad", "great", "tell", "ask", "asked", "earlier", "much", "more",
    "cycle", "improve", "lot", "problem", "having", "trouble", "want", "need",
    "just", "like", "know", "see", "hear", "say", "said", "talk", "speaking",
}


def extract_name_phone(text: str, allow_standalone: bool = False) -> tuple[str, str, Optional[str]]:
    """
    Extract caller name, complete phone number, and any partial phone digits from conversational text.
    Returns:
        (name, full_phone, partial_phone)
    """
    clean = text.strip()
    norm_text = normalize_spoken_digits(clean)

    phone = ""
    partial_phone = None

    # Mask time-like patterns so hours/minutes (e.g. 10:00 AM) are not mistaken for phone numbers
    clean_for_phone = re.sub(r"\b(?:1[0-2]|0?[1-9]):[0-5][0-9]\s*(?:am|pm)?\b", " ", norm_text, flags=re.IGNORECASE)
    clean_for_phone = re.sub(r"\b(?:1[0-2]|0?[1-9])\s*(?:am|pm)\b", " ", clean_for_phone, flags=re.IGNORECASE)

    # Candidate phone sequences: digits separated by spaces, commas, hyphens, dots, parentheses
    phone_pattern = re.compile(r"(?:\+?\d(?:[\s,.\-()]*\d){5,14})")
    m = phone_pattern.search(clean_for_phone)
    matched_raw = ""
    if m:
        matched_raw = m.group(0)
        digits = re.sub(r"[^\d+]", "", matched_raw)
        pure_len = len(digits.replace("+", ""))
        if pure_len >= 10:
            phone = digits
        elif pure_len >= 6:
            partial_phone = digits

    # Remove matched phone or partial phone to isolate caller name
    if matched_raw:
        clean_no_phone = norm_text.replace(matched_raw, " ").strip()
    else:
        clean_no_phone = norm_text

    # Strip filler words relating to phone
    clean_no_phone = re.sub(
        r"\b(and\s+)?(my\s+)?(phone\s+)?(number|no|num|mob|mobile|contact)(\s+is)?\b", "", clean_no_phone, flags=re.I
    ).strip()

    name = ""
    name_patterns = [
        r"(?:my name is|i am|this is|name is|i\'m)\s+([a-zA-Z\u0900-\u097F]+(?:\s+[a-zA-Z\u0900-\u097F]+)?)",
        r"^(?:it\'s|its)\s+([a-zA-Z\u0900-\u097F]+(?:\s+[a-zA-Z\u0900-\u097F]+)?)",
    ]
    for p in name_patterns:
        m_name = re.search(p, clean_no_phone, re.I)
        if m_name:
            cand = m_name.group(1).strip()
            if cand.lower() not in _COMMON_NON_NAME_WORDS:
                name = cand
                break

    if not name and allow_standalone and clean_no_phone:
        words = [
            w for w in re.split(r"[,.\s]+", clean_no_phone)
            if w and w.lower() not in _COMMON_NON_NAME_WORDS
        ]
        if 1 <= len(words) <= 3 and all(w.isalpha() for w in words):
            name = " ".join(words).title()

    if name:
        name = re.sub(r"\b(and|is|my|the|number|phone)\b", "", name, flags=re.I).strip()

    return name, phone, partial_phone


def extract_time_slot(text: str, available_slots: Optional[list[str]] = None) -> Optional[str]:
    """
    Extract time slot from caller utterance (e.g. '11:00 AM', '1100 AM', '10 am', '4 o'clock', 'ten AM', 'first slot').
    If available_slots are provided, matches against known open slots with ordinal, digit, and word heuristics.
    """
    clean = normalize_time_utterance(text.lower().strip())
    clean_no_colon = clean.replace(":", "")

    # 1. If available_slots are known, perform smart matching against them
    if available_slots:
        for s in available_slots:
            s_low = s.lower()
            if s_low in clean or s_low.replace(":", "") in clean_no_colon:
                return s
            # Match '11 am' against '11:00 AM'
            s_no_min = re.sub(r":00\b", "", s_low)
            if re.search(r"\b" + re.escape(s_no_min) + r"\b", clean):
                return s
            # Match '11:00' against '11:00 AM'
            s_time_only = s_low.split()[0]
            if re.search(r"\b" + re.escape(s_time_only) + r"\b", clean):
                return s
            # Match '1100' against '11:00 AM'
            s_digits = re.sub(r"\D", "", s_time_only)
            if s_digits and re.search(r"\b" + re.escape(s_digits) + r"\b", clean_no_colon):
                return s

        # Ordinal choices: "first slot", "second slot", "last slot", "पहला", "दूसरा"
        if any(w in clean for w in ["first", "1st", "पहला"]):
            return available_slots[0]
        if len(available_slots) > 1 and any(w in clean for w in ["second", "2nd", "दूसरा"]):
            return available_slots[1]
        if len(available_slots) > 2 and any(w in clean for w in ["third", "3rd", "तीसरा"]):
            return available_slots[2]
        if any(w in clean for w in ["last", "आखिरी"]):
            return available_slots[-1]

        # Match by hour or number words against slots
        for s in available_slots:
            num = re.sub(r"[^0-9]", "", s.split(":")[0]).lstrip("0")
            for kw in _HOUR_WORD_MAP.get(num, []):
                if re.search(r"\b" + re.escape(kw) + r"\b", clean) or re.search(r"\b" + re.escape(kw) + r"\b", clean_no_colon):
                    return s

    # 2. General regex match
    m = _TIME_SLOT_RE.search(clean)
    if m:
        val = m.group(1) or m.group(2) or m.group(3)
        if val:
            val = val.strip().upper()
            if "O'CLOCK" in val or "BAJE" in val:
                num = re.sub(r"[^\d]", "", val)
                return f"{int(num):02d}:00 PM" if int(num) < 7 else f"{int(num):02d}:00 AM"
            if ":" in val and ("AM" in val or "PM" in val):
                parts = val.split(":")
                return f"{int(parts[0]):02d}:{parts[1]}"
            if ":" in val:
                parts = val.split(":")
                hr = int(parts[0])
                mn = parts[1]
                if hr < 7:
                    return f"{hr:02d}:{mn} PM"
                elif hr < 12:
                    return f"{hr:02d}:{mn} AM"
                elif hr == 12:
                    return f"12:{mn} PM"
                else:
                    return f"{(hr - 12):02d}:{mn} PM"
            m2 = re.match(r"^(\d{1,2})\s*(AM|PM)$", val)
            if m2:
                return f"{int(m2.group(1)):02d}:00 {m2.group(2)}"
            return val

    # 3. Check for standalone hour words like "ten am", "four pm", "two thirty"
    word_times = {
        "ten": "10:00 AM",
        "ten am": "10:00 AM",
        "eleven": "11:00 AM",
        "eleven am": "11:00 AM",
        "twelve": "12:00 PM",
        "twelve pm": "12:00 PM",
        "two thirty": "02:30 PM",
        "two thirty pm": "02:30 PM",
        "four": "04:00 PM",
        "four pm": "04:00 PM",
    }
    for phrase, mapped_slot in word_times.items():
        if re.search(r"\b" + re.escape(phrase) + r"\b", clean):
            return mapped_slot

    return None


# In-memory TTL cache for Google Sheet slots: key -> (timestamp, (display_slots, target_date, raw_slots_map))
_SLOTS_CACHE: dict[str, tuple[float, tuple[list[str], str, dict[str, str]]]] = {}
_SLOTS_CACHE_TTL = 90.0  # seconds

_TOOLS_HTTP_CLIENT: Optional[httpx.AsyncClient] = None


def _get_tools_http_client() -> httpx.AsyncClient:
    """Return a shared singleton HTTP client with keep-alive connection pooling."""
    global _TOOLS_HTTP_CLIENT
    if _TOOLS_HTTP_CLIENT is None or _TOOLS_HTTP_CLIENT.is_closed:
        _TOOLS_HTTP_CLIENT = httpx.AsyncClient(
            timeout=4.5,
            follow_redirects=True,
            limits=httpx.Limits(max_keepalive_connections=5, keepalive_expiry=60.0),
        )
    return _TOOLS_HTTP_CLIENT


def invalidate_slots_cache(webhook_url: Optional[str] = None) -> None:
    """Clear cached slots when a new booking is posted."""
    if webhook_url:
        keys_to_del = [k for k in _SLOTS_CACHE if k.startswith(webhook_url)]
        for k in keys_to_del:
            _SLOTS_CACHE.pop(k, None)
    else:
        _SLOTS_CACHE.clear()


async def check_sheet_availability(webhook_url: str, date: str) -> tuple[list[str], str, dict[str, str], dict[str, str]]:
    """
    Query Google Spreadsheet webhook for open slots with TTL in-memory caching.
    Returns:
        (display_slots, target_date, raw_slots_map, raw_dates_map)
    """
    if not webhook_url or not webhook_url.startswith("http"):
        logger.info("[Tools] No webhook URL configured, using default demo slots.")
        return ["10:00 AM", "02:30 PM", "04:00 PM"], date, {}, {}

    # Check cache first for sub-millisecond response time
    cache_key = f"{webhook_url}::{date}"
    try:
        loop = asyncio.get_running_loop()
        now_ts = loop.time()
    except Exception:
        now_ts = datetime.now().timestamp()

    if cache_key in _SLOTS_CACHE:
        cached_ts, cached_val = _SLOTS_CACHE[cache_key]
        if now_ts - cached_ts < _SLOTS_CACHE_TTL:
            logger.info("[Tools] Returning %d cached slot(s) for %s (age=%.1fs)", len(cached_val[0]), date, now_ts - cached_ts)
            return cached_val

    client = _get_tools_http_client()
    try:
        # Query get_slots first (Google Apps Script webhooks often return available_slots directly)
        resp = await client.get(webhook_url, params={"action": "get_slots"})
        data = resp.json() if resp.status_code == 200 else {}
        raw_items = data.get("available_slots") or data.get("slots") or data.get("data") or []

        if not raw_items:
            resp = await client.get(webhook_url, params={"date": date, "action": "check_availability"})
            if resp.status_code == 200:
                data = resp.json()
                raw_items = data.get("available_slots") or data.get("slots") or data.get("data") or []

        if isinstance(raw_items, list):
            if not raw_items and (data.get("status") == "success" or "available_slots" in data):
                logger.info("[Tools] Google Sheet connected and confirmed 0 open slots for %s", date)
                result = ([], date, {}, {})
                _SLOTS_CACHE[cache_key] = (now_ts, result)
                return result

            display_slots = []
            raw_slots_map = {}
            raw_dates_map = {}
            found_date = ""

            for item in raw_items:
                raw_slot = ""
                raw_date = ""
                if isinstance(item, dict):
                    raw_slot = str(item.get("slot") or item.get("time") or item.get("slot_time") or item.get("name") or "")
                    raw_date = str(item.get("date") or "")
                elif item:
                    raw_slot = str(item).strip()

                # Extract display time (e.g. 11:00 AM)
                m = re.search(r"(\d{1,2}):(\d{2})(?::\d{2})?", raw_slot)
                if m:
                    hr = int(m.group(1))
                    mn = m.group(2)
                    ampm = "AM" if hr < 12 else "PM"
                    display_hr = hr if (0 < hr <= 12) else (hr - 12 if hr > 12 else 12)
                    time_str = f"{display_hr:02d}:{mn} {ampm}"
                elif "AM" in raw_slot.upper() or "PM" in raw_slot.upper():
                    time_str = raw_slot.strip().upper()
                else:
                    time_str = raw_slot.strip()

                # Extract date in IST (UTC+5:30)
                if raw_date and not found_date:
                    try:
                        dt = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                        ist_dt = dt.astimezone(timezone(timedelta(hours=5, minutes=30)))
                        found_date = ist_dt.strftime("%Y-%m-%d")
                    except Exception:
                        found_date = raw_date.split("T")[0]

                if time_str and time_str not in display_slots:
                    display_slots.append(time_str)
                    raw_slots_map[time_str] = raw_slot
                    if raw_date:
                        raw_dates_map[time_str] = raw_date

            if display_slots:
                target_date = found_date or date
                logger.info("[Tools] Retrieved %d available slot(s) from sheet: %s (date=%s)", len(display_slots), display_slots, target_date)
                result = (display_slots, target_date, raw_slots_map, raw_dates_map)
                _SLOTS_CACHE[cache_key] = (now_ts, result)
                if target_date and target_date != date:
                    _SLOTS_CACHE[f"{webhook_url}::{target_date}"] = (now_ts, result)
                return result
    except Exception as exc:
        logger.warning("Error querying Google Sheet webhook (%s): %s", webhook_url, exc)

    return ["10:00 AM", "02:30 PM", "04:00 PM"], date, {}, {}


async def book_sheet_appointment(
    webhook_url: str,
    date: str,
    time: str,
    raw_slot: str,
    name: str,
    phone: str,
    notes: str = "",
    raw_date: str = "",
) -> dict[str, Any]:
    """Post new booking details to Google Spreadsheet webhook with date fallback tolerance."""
    payload = {
        "action": "book_appointment",
        "date": raw_date or date,
        "slot": raw_slot or time,
        "time": time,
        "name": name,
        "phone": phone,
        "notes": notes,
        "booked_at": datetime.now(timezone.utc).isoformat(),
    }

    if not webhook_url or not webhook_url.startswith("http"):
        logger.info("[Mock Tool] Booked appointment in sheet: %r", payload)
        return {"status": "success", "message": "Slot booked successfully", "booking": payload}

    client = _get_tools_http_client()
    try:
        # First attempt: send with date
        resp = await client.post(webhook_url, json=payload)
        if resp.status_code == 200:
            data = resp.json()
            logger.info("[Tools] Google Sheet primary booking response: %r", data)
            if data.get("status") in ("success", "confirmed"):
                invalidate_slots_cache(webhook_url)
                return data

            # If Apps Script failed due to date mismatch, retry without date constraint
            msg = str(data.get("message", "")).lower()
            if "unavailable" in msg or "not found" in msg or data.get("status") == "error":
                logger.info("[Tools] Primary booking rejected (%s). Retrying without date constraint...", data.get("message"))
                payload_fallback = {k: v for k, v in payload.items() if k != "date"}
                resp_fallback = await client.post(webhook_url, json=payload_fallback)
                if resp_fallback.status_code == 200:
                    fb_data = resp_fallback.json()
                    logger.info("[Tools] Fallback booking response: %r", fb_data)
                    if fb_data.get("status") in ("success", "confirmed"):
                        invalidate_slots_cache(webhook_url)
                        return fb_data
            return data
    except Exception as exc:
        logger.warning("Error posting booking to Google Sheet webhook (%s): %s", webhook_url, exc)

    return {"status": "error", "message": "Failed to connect to Google Sheet webhook"}


class BookingToolManager:
    """
    Manages live Google Sheet booking state across turns for a phone call:
    1. Offers available slots from live Google Sheet.
    2. Lets caller pick a slot.
    3. Solicits caller's Name and Phone Number.
    4. Posts confirmed booking with raw slot value to Google Sheet.
    5. Confirms booking and returns conversational floor to LLM for further caller questions.
    """

    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = webhook_url
        self.state = "idle"  # idle | slots_offered | awaiting_details | awaiting_phone | awaiting_name | booked
        self.target_date: Optional[str] = None
        self.available_slots: list[str] = []
        self.raw_slots_map: dict[str, str] = {}
        self.raw_dates_map: dict[str, str] = {}
        self.chosen_slot: Optional[str] = None
        self.booked_name: Optional[str] = None
        self.booked_phone: Optional[str] = None
        self.partial_phone: Optional[str] = None
        self._prefetch_task: Optional[asyncio.Task] = None

    async def prefetch_slots(self, date: Optional[str] = None) -> None:
        """Prefetch available slots in the background so turns don't block on Google Apps Script."""
        if not self.webhook_url or not self.webhook_url.startswith("http"):
            return
        if self.available_slots:
            return
        target_d = date or (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        try:
            slots, t_date, raw_map, raw_dates = await check_sheet_availability(self.webhook_url, target_d)
            if slots and not self.available_slots:
                self.available_slots = slots
                self.target_date = t_date or target_d
                self.raw_slots_map = raw_map
                self.raw_dates_map = raw_dates
                logger.info("[Tools] Background prefetch completed: %d slot(s) for %s", len(slots), self.target_date)
        except Exception as exc:
            logger.debug("[Tools] Background prefetch skipped/failed: %s", exc)

    def _match_available_slot(self, time_str: str) -> Optional[str]:
        """Match a time string against available_slots."""
        if not self.available_slots:
            return None
        norm_time = time_str.strip().upper()
        norm_time_no_colon = norm_time.replace(":", "")
        # 1. Exact or colon-normalized match
        for s in self.available_slots:
            s_upper = s.strip().upper()
            if s_upper == norm_time or s_upper.replace(":", "") == norm_time_no_colon:
                return s
        # 2. Relaxed matching (e.g. "11:00 AM" vs "11 AM" or "11:00")
        for s in self.available_slots:
            s_upper = s.strip().upper()
            if s_upper.replace(":00", "") == norm_time.replace(":00", ""):
                return s
            if s_upper.split()[0] == norm_time.split()[0]:
                return s
            # Match digits e.g. "1100" vs "11:00"
            s_digits = re.sub(r"\D", "", s_upper.split()[0])
            norm_digits = re.sub(r"\D", "", norm_time.split()[0])
            if s_digits and norm_digits and s_digits == norm_digits:
                return s
        return None

    async def evaluate_turn(
        self,
        user_text: str,
        dialogue_slots: Optional[dict[str, Any]] = None,
        language: str = "en",
    ) -> tuple[Optional[str], Optional[str], Optional[dict[str, Any]]]:
        """
        Evaluate user turn against booking tool state.
        Returns:
            (direct_reply, prompt_injection, event_data_for_ui)
        """
        dialogue_slots = dialogue_slots or {}
        if not self.booked_name:
            self.booked_name = dialogue_slots.get("name") or dialogue_slots.get("caller_name") or None
        if not self.booked_phone:
            self.booked_phone = dialogue_slots.get("phone") or dialogue_slots.get("phone_number") or None

        is_hindi = language == "hi" or any(ord(c) >= 0x0900 and ord(c) <= 0x097F for c in user_text) or "कल" in user_text
        extracted_time = extract_time_slot(user_text, self.available_slots)
        is_asking_slots = bool(_BOOKING_INTENT_RE.search(user_text))

        allow_name_standalone = self.state in ("awaiting_name", "awaiting_details")
        cand_name, cand_phone, cand_partial = extract_name_phone(user_text, allow_standalone=allow_name_standalone)

        # If already booked, allow caller to start a new booking or continue chatting with LLM
        if self.state == "booked":
            if is_asking_slots or extracted_time:
                logger.info("[Tools] Caller requested a new booking after previous booking. Resetting state.")
                self.state = "idle"
                self.chosen_slot = None
                self.booked_name = None
                self.booked_phone = None
            else:
                return None, None, None

        # Check cancellation / exit from booking flow
        if self.state in ("slots_offered", "awaiting_details", "awaiting_phone", "awaiting_name"):
            if bool(_CANCEL_INTENT_RE.search(user_text)):
                logger.info("[Tools] User cancelled/declined booking (state was %s): %r", self.state, user_text)
                self.state = "idle"
                self.chosen_slot = None
                return None, None, None

        # In slots_offered, if caller did not choose a slot and did not ask for slots/dates,
        # they have moved on to an unrelated question. Reset state to idle so conversation isn't hijacked!
        if self.state == "slots_offered" and not extracted_time and not is_asking_slots:
            logger.info("[Tools] Caller changed topic away from slots_offered: %r. Resetting booking state to idle.", user_text)
            self.state = "idle"
            self.chosen_slot = None
            return None, None, None

        # Check if caller in awaiting_phone is providing remaining digits for a partial phone
        if self.state == "awaiting_phone" and self.partial_phone and not cand_phone:
            norm_text = normalize_spoken_digits(user_text)
            rem_digits = "".join(re.findall(r"\d", norm_text))
            if rem_digits and len(self.partial_phone) + len(rem_digits) == 10:
                cand_phone = self.partial_phone + rem_digits
                self.partial_phone = None

        # Check if caller is switching or selecting a slot while already awaiting details/phone/name
        if extracted_time and self.state in ("awaiting_details", "awaiting_phone", "awaiting_name"):
            matched = self._match_available_slot(extracted_time)
            if matched:
                self.chosen_slot = matched
            elif self.available_slots:
                slot_str = ", ".join(self.available_slots)
                if is_hindi:
                    reply = f"माफ़ कीजिए, {extracted_time} का स्लॉट उपलब्ध नहीं है। {self.target_date} के लिए उपलब्ध स्लॉट {slot_str} हैं। आप कौन सा समय पसंद करेंगे?"
                else:
                    reply = f"I apologize, but {extracted_time} is not available. Available slots for {self.target_date} are {slot_str}. Which of these times works best for you?"
                return reply, None, None

        # 1. State: awaiting details / phone / name after choosing a slot
        if self.state in ("awaiting_details", "awaiting_phone", "awaiting_name"):
            if cand_name:
                self.booked_name = cand_name
            if cand_phone:
                self.booked_phone = cand_phone
                self.partial_phone = None
            elif cand_partial:
                self.partial_phone = cand_partial

            if self.booked_name and self.booked_phone:
                return await self._execute_booking(is_hindi)
            elif self.booked_name and not self.booked_phone:
                self.state = "awaiting_phone"
                if cand_name:
                    # Name was provided in this turn
                    if is_hindi:
                        reply = f"धन्यवाद {self.booked_name}! कृपया अपना फ़ोन नंबर भी बता दीजिए।"
                    else:
                        reply = f"Thank you {self.booked_name}. What is your phone number?"
                elif cand_partial or self.partial_phone:
                    p = cand_partial or self.partial_phone
                    p_spaced = " ".join(p)
                    if is_hindi:
                        reply = f"मुझे {len(p)} अंक ({p_spaced}) मिले हैं। कृपया अपना पूरा 10 अंकों का फ़ोन नंबर बता दीजिए।"
                    else:
                        reply = f"I heard {len(p)} digits: {p_spaced}. A complete phone number needs 10 digits. Could you please share your full 10-digit phone number?"
                else:
                    if is_hindi:
                        reply = f"कृपया अपना 10 अंकों का फ़ोन नंबर बता दीजिए ताकि मैं {self.chosen_slot} का स्लॉट बुक कर सकूँ।"
                    else:
                        reply = f"Could you please share your 10-digit phone number to confirm your booking for {self.chosen_slot}?"
                return reply, None, None
            elif self.booked_phone and not self.booked_name:
                self.state = "awaiting_name"
                if cand_phone:
                    if is_hindi:
                        reply = "फ़ोन नंबर नोट कर लिया गया है। कृपया अपना नाम भी बता दीजिए।"
                    else:
                        reply = "Got your phone number. May I also have your name please?"
                else:
                    if is_hindi:
                        reply = "कृपया अपना नाम बता दीजिए।"
                    else:
                        reply = "Could you please tell me your name?"
                return reply, None, None
            else:
                self.state = "awaiting_details"
                if cand_partial or self.partial_phone:
                    p = cand_partial or self.partial_phone
                    if is_hindi:
                        reply = f"मुझे फ़ोन के {len(p)} अंक मिले हैं। कृपया अपना नाम और पूरा 10 अंकों का फ़ोन नंबर बता दीजिए।"
                    else:
                        reply = f"I heard {len(p)} phone digits. Could you please share your name and full 10-digit phone number?"
                else:
                    if is_hindi:
                        reply = (
                            f"कृपया अपना नाम और फ़ोन नंबर बता दीजिए ताकि मैं {self.chosen_slot} का स्लॉट बुक कर सकूँ।"
                            if is_hindi
                            else f"Could you please share your name and phone number to book the {self.chosen_slot} slot?"
                        )
                return reply, None, None

        # 2. State: Caller selects / chooses a specific slot
        if extracted_time:
            # Query sheet if available_slots not yet loaded
            if not self.available_slots:
                date_str = parse_date_intent(user_text) or self.target_date or (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
                slots, t_date, raw_map, raw_dates = await check_sheet_availability(self.webhook_url, date_str)
                self.available_slots = slots
                self.target_date = t_date or date_str
                self.raw_slots_map = raw_map
                self.raw_dates_map = raw_dates

            matched = self._match_available_slot(extracted_time)
            if not matched and self.available_slots:
                slot_str = ", ".join(self.available_slots)
                self.state = "slots_offered"
                if is_hindi:
                    direct_reply = f"माफ़ कीजिए, {extracted_time} का स्लॉट उपलब्ध नहीं है। {self.target_date} के लिए उपलब्ध स्लॉट {slot_str} हैं। आप कौन सा समय पसंद करेंगे?"
                else:
                    direct_reply = f"I apologize, but {extracted_time} is not available. For {self.target_date}, we have available slots at {slot_str}. Which of these times works best for you?"
                return direct_reply, None, None

            self.chosen_slot = matched or extracted_time
            if not self.target_date:
                self.target_date = parse_date_intent(user_text) or (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

            if cand_name:
                self.booked_name = cand_name
            if cand_phone:
                self.booked_phone = cand_phone
                self.partial_phone = None
            elif cand_partial:
                self.partial_phone = cand_partial

            # Check if caller already provided both name and phone
            if self.booked_name and self.booked_phone:
                return await self._execute_booking(is_hindi)
            elif self.booked_name and not self.booked_phone:
                self.state = "awaiting_phone"
                if cand_partial or self.partial_phone:
                    p = cand_partial or self.partial_phone
                    if is_hindi:
                        reply = f"धन्यवाद {self.booked_name}! मुझे {len(p)} अंक मिले हैं। कृपया पूरा 10 अंकों का फ़ोन नंबर बता दीजिए।"
                    else:
                        reply = f"Thank you {self.booked_name}! I heard {len(p)} digits. Could you please share your full 10-digit phone number?"
                else:
                    if is_hindi:
                        reply = f"बिल्कुल {self.booked_name}, मैं {self.chosen_slot} का स्लॉट बुक कर रहा हूँ। कृपया अपना फ़ोन नंबर बता दीजिए।"
                    else:
                        reply = f"Great {self.booked_name}, I can book {self.chosen_slot} for you. Could you please share your phone number?"
                return reply, None, None
            elif self.booked_phone and not self.booked_name:
                self.state = "awaiting_name"
                if is_hindi:
                    reply = f"बिल्कुल, मैं {self.chosen_slot} का स्लॉट बुक कर रहा हूँ। कृपया अपना नाम बता दीजिए।"
                else:
                    reply = f"Great, I can book {self.chosen_slot} for you. May I have your name please?"
                return reply, None, None
            else:
                self.state = "awaiting_details"
                if is_hindi:
                    reply = f"बिल्कुल, मैं आपके लिए {self.chosen_slot} का स्लॉट बुक कर सकता हूँ। क्या आप अपना नाम और फ़ोन नंबर बता सकते हैं?"
                else:
                    reply = f"Great, I can book {self.chosen_slot} for you. Could you please tell me your name and phone number?"
                return reply, None, None

        # 3. State: Caller is inquiring about appointment or availability
        if is_asking_slots:
            date_str = parse_date_intent(user_text) or self.target_date or (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
            # If we already have pre-fetched or cached slots for this target date, reuse them directly for sub-millisecond response
            if self.available_slots and self.target_date == date_str:
                slots = self.available_slots
            else:
                logger.info("Querying Google Sheet availability for date=%s (webhook=%s)", date_str, self.webhook_url)
                slots, t_date, raw_map, raw_dates = await check_sheet_availability(self.webhook_url, date_str)
                self.available_slots = slots
                self.target_date = t_date or date_str
                self.raw_slots_map = raw_map
                self.raw_dates_map = raw_dates

            self.state = "slots_offered"

            slot_str = ", ".join(slots) if slots else "no open slots"
            event = {
                "type": "tool_call",
                "tool": "check_sheet_availability",
                "date": self.target_date,
                "slots": slots,
                "details": f"Available slots for {self.target_date}: {slot_str}",
                "summary": f"Checked Google Sheet: {len(slots)} slot(s) available on {self.target_date}: {slot_str}",
            }

            if slots:
                if is_hindi:
                    direct_reply = f"{self.target_date} के लिए हमारे पास {slot_str} के स्लॉट उपलब्ध हैं। आप कौन सा समय पसंद करेंगे?"
                else:
                    direct_reply = f"For {self.target_date}, we have available slots at {slot_str}. Which of these times works best for you?"
            else:
                if is_hindi:
                    direct_reply = f"माफ़ कीजिए, {self.target_date} के लिए कोई स्लॉट खाली नहीं है। क्या आप किसी अन्य दिन का समय देखना चाहेंगे?"
                else:
                    direct_reply = f"Sorry, there are no available slots for {self.target_date}. Would you like to check another date?"

            return direct_reply, None, event

        return None, None, None

    async def _execute_booking(self, is_hindi: bool) -> tuple[str, None, dict[str, Any]]:
        """Perform the actual appointment booking in the Google Sheet."""
        raw_slot = self.raw_slots_map.get(self.chosen_slot or "", "") or self.chosen_slot or ""
        raw_date = self.raw_dates_map.get(self.chosen_slot or "", "")
        final_name = self.booked_name or "Caller"
        final_phone = self.booked_phone or ""
        logger.info(
            "Booking appointment in Google Sheet: date=%s (raw_date=%r), time=%s (raw=%r), name=%s, phone=%s",
            self.target_date, raw_date, self.chosen_slot, raw_slot, final_name, final_phone
        )
        res = await book_sheet_appointment(
            webhook_url=self.webhook_url,
            date=self.target_date or "",
            time=self.chosen_slot or "",
            raw_slot=raw_slot,
            name=final_name,
            phone=final_phone,
            notes=f"Booked via Voice Agent on {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            raw_date=raw_date,
        )

        if res.get("status") in ("success", "confirmed"):
            self.state = "booked"
            # Remove booked slot from active manager memory immediately
            if self.chosen_slot in self.available_slots:
                self.available_slots.remove(self.chosen_slot)
            self.raw_slots_map.pop(self.chosen_slot, None)
            self.raw_dates_map.pop(self.chosen_slot, None)

            event = {
                "type": "tool_call",
                "tool": "book_appointment",
                "date": self.target_date,
                "time": self.chosen_slot,
                "name": final_name,
                "phone": final_phone,
                "status": "confirmed",
                "details": f"Booked {self.chosen_slot} on {self.target_date} for {final_name} ({final_phone})",
                "summary": f"Google Sheet Updated: Booked {self.chosen_slot} on {self.target_date} for {final_name} ({final_phone})",
            }
            if is_hindi:
                direct_reply = f"धन्यवाद {final_name}! {self.target_date} को {self.chosen_slot} बजे का आपका अपॉइंटमेंट कन्फर्म हो गया है। क्या मैं आपकी किसी और चीज़ में मदद कर सकता हूँ?"
            else:
                direct_reply = f"Thank you {final_name}! Your appointment for {self.chosen_slot} on {self.target_date} has been confirmed and booked in our schedule. Is there anything else I can help you with today?"
            return direct_reply, None, event
        else:
            logger.warning("[Tools] Booking failed: %r", res)
            # Refetch remaining available slots
            slots, t_date, raw_map, raw_dates = await check_sheet_availability(self.webhook_url, self.target_date or "")
            self.available_slots = slots
            self.raw_slots_map = raw_map
            self.raw_dates_map = raw_dates
            self.state = "slots_offered"
            slot_str = ", ".join(slots) if slots else "no open slots"
            if is_hindi:
                direct_reply = f"माफ़ कीजिए, {self.chosen_slot} का स्लॉट उपलब्ध नहीं है। हमारे पास {slot_str} उपलब्ध हैं। आप कौन सा चुनना चाहेंगे?"
            else:
                direct_reply = f"I apologize, but the {self.chosen_slot} slot is no longer available. We currently have {slot_str}. Which one would you prefer?"
            return direct_reply, None, None
