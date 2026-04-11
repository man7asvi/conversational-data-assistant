# backend/parser.py
import re
from typing import Dict, Any

REGION_ALIASES = {
    "new york": "NY",
    "ny": "NY",
    "california": "CA",
    "ca": "CA",
    "texas": "TX",
    "tx": "TX",
}

MONTHS = {
    "january": "January",
    "february": "February",
    "march": "March",
    "april": "April",
    "may": "May",
    "june": "June",
    "july": "July",
    "august": "August",
    "september": "September",
    "october": "October",
    "november": "November",
    "december": "December",
}

AGGREGATE_KEYWORDS = {
    "total": "total",
    "sum": "sum",
    "average": "average",
    "avg": "average",
    "count": "count",
    "minimum": "min",
    "min": "min",
    "maximum": "max",
    "max": "max",
}

def parse(text: str) -> Dict[str, Any]:
    normalized = re.sub(r"\s+", " ", text.lower()).strip()

    entities = {
        "region": None,
        "product": None,
        "month": None,
        "aggregate": None,
    }

    intent = "unknown"

    # Intent detection
    if any(word in normalized for word in ["hi", "hello", "hey"]):
        intent = "greeting"
    elif any(word in normalized for word in ["show", "get", "list", "sales", "revenue", "total", "sum", "count", "average", "avg"]):
        intent = "query_db"

    # Region extraction
    for phrase, code in REGION_ALIASES.items():
        if re.search(rf"\b{re.escape(phrase)}\b", normalized):
            entities["region"] = code
            break

    # Month extraction
    for month_key, month_value in MONTHS.items():
        if re.search(rf"\b{month_key}\b", normalized):
            entities["month"] = month_value
            break

    # Aggregate extraction
    for keyword, agg_value in AGGREGATE_KEYWORDS.items():
        if re.search(rf"\b{re.escape(keyword)}\b", normalized):
            entities["aggregate"] = agg_value
            break

    # Product extraction (very basic)
    product_match = re.search(r"\bproduct\s+([a-z0-9_-]+(?:\s+[a-z0-9_-]+)*)", normalized)
    if product_match:
        entities["product"] = product_match.group(1).strip()

    return {
        "intent": intent,
        "entities": entities
    }