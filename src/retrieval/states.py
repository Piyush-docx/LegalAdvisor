"""Does a question name an Indian state or union territory? Used to decide whether central Acts should be
preferred over state Acts (a question that names no state is usually about the central law)."""

import re

_NAMES = [
    "andhra pradesh", "arunachal pradesh", "assam", "bihar", "chhattisgarh", "goa", "gujarat", "haryana",
    "himachal pradesh", "jharkhand", "karnataka", "kerala", "madhya pradesh", "maharashtra", "manipur",
    "meghalaya", "mizoram", "nagaland", "odisha", "orissa", "punjab", "rajasthan", "sikkim", "tamil nadu",
    "tamilnadu", "telangana", "tripura", "uttar pradesh", "uttarakhand", "west bengal", "delhi",
    "jammu", "kashmir", "ladakh", "chandigarh", "puducherry", "pondicherry", "andaman", "lakshadweep",
    "mumbai", "bengaluru", "bangalore", "chennai", "kolkata", "hyderabad",
]
_PATTERN = re.compile(r"\b(" + "|".join(re.escape(n) for n in _NAMES) + r")\b", re.IGNORECASE)


def mentions_state(text: str | None) -> bool:
    return bool(text and _PATTERN.search(text))
