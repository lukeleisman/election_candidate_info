"""Shared name normalization for matching candidate names across sources.

Used by:
  scripts/compare_candidate_lists.py   CBOE list vs unofficial lists
  scripts/build_ballot_status.py       CBOE list vs Electoral Board cases
  (planned) scripts/match_endorsements.py

Changing a step here changes every match above; each script records which
steps were on in its output.
"""

import re
import unicodedata

# Name normalization, applied in this order. Set any to False to switch it off;
# the output records which steps were on.
NAME_NORMALIZATION_STEPS = {
    # 'Rodríguez' -> 'Rodriguez'
    "strip_accents": True,
    "uppercase": True,
    # 'Timothy "Tim" Thomas' -> 'Timothy Thomas'  (straight and curly quotes)
    "drop_quoted_nicknames": True,
    # 'Dennis (DJ) Doran' -> 'Dennis Doran'
    "drop_parenthesized_nicknames": True,
    # 'Jones AKA Jaye Jones' -> 'Jones'  (everything from AKA onward)
    "drop_aka_and_after": True,
    # 'Thomas Jr.' -> 'Thomas'; also SR, II, III, IV
    "drop_suffixes": True,
    # 'William E Hall' / 'George A. Cardenas' -> drop one-letter words
    "drop_single_letter_words": True,
    # remove remaining punctuation except hyphens and spaces, collapse spaces
    "strip_punctuation": True,
}

NAME_SUFFIXES = {"JR", "SR", "II", "III", "IV"}

# First names treated as the same name (nickname <-> formal name). Two first names
# are equivalent when both appear in one group. A name can be in several groups
# ("CHRIS" is Christopher or Christine; "NATE" is Nathan or Nathaniel). Written
# uppercase, accent-free, as normalize_name produces them. Hand-made list (added
# 2026-11-04 at the user's request): common English nicknames plus the ones seen
# in the 2027 review sheet. Equivalence never accepts a match by itself; see
# NICKNAME_EFFECT in scripts/apply_isbe_record_rule.py.
NICKNAME_GROUPS = [
    {"ROBERT", "BOB", "BOBBY", "ROB", "ROBBIE", "BERT"},
    {"WILLIAM", "BILL", "BILLY", "WILL", "WILLIE", "LIAM"},
    {"JAMES", "JIM", "JIMMY", "JAMIE"},
    {"JOHN", "JACK", "JOHNNY"},
    {"JOSEPH", "JOE", "JOEY"},
    {"MICHAEL", "MIKE", "MIKEY", "MICK"},
    {"THOMAS", "TOM", "TOMMY"},
    {"TIMOTHY", "TIM", "TIMMY"},
    {"CHRISTOPHER", "CHRIS"},
    {"CHRISTINE", "CHRISTINA", "CHRIS", "CHRISSY", "TINA"},
    {"MATTHEW", "MATT"},
    {"NATHANIEL", "NATE", "NAT"},
    {"NATHAN", "NATE"},
    {"DANIEL", "DAN", "DANNY"},
    {"DAVID", "DAVE"},
    {"RICHARD", "RICK", "RICKY", "RICH", "DICK"},
    {"EDWARD", "ED", "EDDIE", "TED"},
    {"THEODORE", "TED", "TEDDY"},
    {"ANTHONY", "TONY"},
    {"CHARLES", "CHARLIE", "CHUCK"},
    {"STEPHEN", "STEVEN", "STEVE"},
    {"GREGORY", "GREG"},
    {"PATRICK", "PAT"},
    {"PATRICIA", "PAT", "PATTY", "TRISH"},
    {"KATHERINE", "CATHERINE", "KATHLEEN", "KATE", "KATIE", "KATHY", "CATHY"},
    {"ELIZABETH", "LIZ", "BETH", "BETSY"},
    {"JENNIFER", "JEN", "JENNY"},
    {"JESSICA", "JESS", "JESSIE"},
    {"DEBORAH", "DEBRA", "DEB", "DEBBIE"},
    {"SAMANTHA", "SAM"},
    {"SAMUEL", "SAM"},
    {"ALEXANDER", "ALEX"},
    {"ALEXANDRA", "ALEX"},
    {"GILBERT", "GIL"},
    {"RAYMOND", "RAY"},
    {"KENNETH", "KEN"},
    {"RONALD", "RON"},
    {"DONALD", "DON"},
    {"GERALD", "GERRY", "JERRY"},
    {"ANDREW", "ANDY", "DREW"},
    {"BENJAMIN", "BEN"},
    {"SUSAN", "SUE", "SUSIE"},
    {"MARGARET", "PEGGY", "MAGGIE", "MEG"},
    {"NICHOLAS", "NICK"},
]


def first_names_equivalent(first, second):
    """True if two first names (already normalized) are equal or share a NICKNAME_GROUPS group."""
    if first == second:
        return True
    return any(first in group and second in group for group in NICKNAME_GROUPS)


def quoted_nicknames(name):
    """Words inside quotes in a raw name: 'WILLIAM "BILL" MORTON' -> ['BILL'].

    normalize_name drops these (drop_quoted_nicknames), so read them from the raw name.
    """
    quoted = re.findall(r'["“”]([^"“”]*)["“”]', name)
    return [normalize_name(text) for text in quoted if normalize_name(text)]


def normalization_steps_on():
    """Comma-separated names of the steps currently switched on (for output files)."""
    return ",".join(step for step, on in NAME_NORMALIZATION_STEPS.items() if on)


def name_suffixes(name):
    """Set of generational suffixes (JR, SR, II, III, IV) written in a raw name.

    normalize_name drops these, so a father and son (e.g. Walter Burnett, Jr and
    Walter "Red" Burnett) normalize the same; compare suffixes separately.
    """
    words = re.sub(r"[^A-Za-z\s]", " ", name).upper().split()
    return {word for word in words if word in NAME_SUFFIXES}


def normalize_name(name):
    """Apply NAME_NORMALIZATION_STEPS to one name."""
    text = name
    steps = NAME_NORMALIZATION_STEPS
    if steps["strip_accents"]:
        text = "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))
    if steps["uppercase"]:
        text = text.upper()
    if steps["drop_quoted_nicknames"]:
        text = re.sub(r'["“”][^"“”]*["“”]', " ", text)
    if steps["drop_parenthesized_nicknames"]:
        text = re.sub(r"\([^)]*\)", " ", text)
    if steps["drop_aka_and_after"]:
        text = re.sub(r"\bAKA\b.*$", " ", text, flags=re.IGNORECASE)
    words = text.replace(",", " ").split()
    if steps["drop_suffixes"]:
        words = [word for word in words if word.rstrip(".").upper() not in NAME_SUFFIXES]
    if steps["drop_single_letter_words"]:
        words = [word for word in words if len(word.rstrip(".")) > 1]
    text = " ".join(words)
    if steps["strip_punctuation"]:
        text = re.sub(r"[^\w\s-]", "", text)
        text = re.sub(r"\s+", " ", text).strip()
    return text


def edit_distance(first, second):
    """Levenshtein distance (insert / delete / substitute, each cost 1)."""
    previous_row = list(range(len(second) + 1))
    for i, first_char in enumerate(first, start=1):
        current_row = [i]
        for j, second_char in enumerate(second, start=1):
            current_row.append(min(
                previous_row[j] + 1,
                current_row[j - 1] + 1,
                previous_row[j - 1] + (first_char != second_char),
            ))
        previous_row = current_row
    return previous_row[-1]
