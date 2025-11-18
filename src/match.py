from datetime import date, datetime
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional


Attachment = Dict[str, Any]
Transaction = Dict[str, Any]

# Minimum score required for a non-reference-based match
THRESHOLD: float = 75.0

# Normalization
def _normalize_reference(ref: Optional[str]) -> str:
    """
    Normalize reference numbers: strip spaces, drop leading zeros, keep uppercases since RF references are standardised identifiers and should not be altered 
    """
    if not ref:
        return ""
    ref = ref.replace(" ", "").upper()
    if ref.isdigit():
        try:
            value = int(ref)
        except ValueError:
            return ref
        return str(value) if value != 0 else "0"
    return ref


def _parse_date(value: Optional[str]) -> Optional[date]:
    """ Parse the date string (YYYY-MM-DD) into a date object """
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _get_tx_amount(transaction: Transaction) -> Optional[float]:
    """
    Transactions store expenses as negative numbers and income as positive, since there are both types of transactions, we define the absolute value of the amount for matching with attachments
    """
    amount = transaction.get("amount")
    if amount is None:
        return None
    try:
        return abs(float(amount))
    except (TypeError, ValueError):
        return None


def _get_att_amount(attachment: Attachment) -> Optional[float]:
    """
    Attachments (invoices/receipts) store total_amount as a positive number. Hence, for consistency with transactions, we compare absolute values.
    """
    
    data = attachment.get("data", {})
    amount = data.get("total_amount")
    if amount is None:
        return None
    try:
        return abs(float(amount))
    except (TypeError, ValueError):
        return None


def _get_tx_date(transaction: Transaction) -> Optional[date]:
    return _parse_date(transaction.get("date"))


def _get_att_dates(attachment: Attachment) -> List[date]:
    """
    Attachments may have several relevant dates:
    - invoicing_date
    - due_date
    - receiving_date (for receipts)

    We return all present dates and the scoring logic will use the closest one
    """
    data = attachment.get("data", {})
    dates: List[date] = []
    for key in ("invoicing_date", "due_date", "receiving_date"):
        d = _parse_date(data.get(key))
        if d is not None:
            dates.append(d)
    return dates


def _date_distance_days(transaction: Transaction, attachment: Attachment) -> Optional[int]:
    """
    Return the smallest absolute difference in days between the transaction date and any relevant date on the attachment
    """
    tx_date = _get_tx_date(transaction)
    att_dates = _get_att_dates(attachment)
    if tx_date is None or not att_dates:
        return None
    return min(abs((tx_date - d).days) for d in att_dates)


def _get_tx_name(transaction: Transaction) -> str:
    """ Return the normalized contact name from the transaction """
    contact = transaction.get("contact") or ""
    return contact.strip().lower()


def _name_similarity(a: str, b: str) -> float:
    """
    Return a deterministic similarity score between two names using SequenceMatcher. The score is in [0, 1] and captures character-level similarity, 
    making it tolerant to minor typos, spacing differences, and suffix variations
    """
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _max_name_similarity(transaction: Transaction, attachment: Attachment) -> float:
    """
    Compute the maximum similarity between the transaction contact name and any candidate counterparty field on the attachment (recipient, issuer, supplier)
    This avoids assuming in advance whether we are looking at a sales invoice, a purchase invoice, or a receipt, and lets the data determine which party is the best match
    """
    tx_name = _get_tx_name(transaction)
    if not tx_name:
        return 0.0

    data = attachment.get("data", {})
    candidates: List[str] = []

    for key in ("recipient", "issuer", "supplier"):
        value = data.get(key)
        if value:
            candidates.append(str(value).strip().lower())

    if not candidates:
        return 0.0

    return max(_name_similarity(tx_name, cand) for cand in candidates)


# Scoring Function 
def _score_pair(transaction: Transaction, attachment: Attachment) -> float:
    """
    Compute a similarity score between a bank transaction and an attachment
    This function is used as a heuristic fallback when there is no unique reference-based match. It combines:
    - Amount proximity (absolute values, tolerance for cents)
    - Date proximity (closest between the transaction date and invoicing, due, or receiving dates)
    - Counterparty name similarity, using the maximum similarity between the transaction contact and any of recipient / issuer / supplier (Selecting the one with highest similarity)
    Reference numbers are handled separately in a "reference-first" pass, so they are not included here as a positive signal in the scoring function
    """
    score = 0.0

    # 1. Amount similarity
    tx_amount = _get_tx_amount(transaction)
    att_amount = _get_att_amount(attachment)
    if tx_amount is not None and att_amount is not None:
        diff = abs(tx_amount - att_amount)
        if diff <= 0.01:
            score += 40.0
        elif diff <= 1.0:
            score += 30.0
        elif diff <= 5.0:
            score += 10.0

    # 2. Date proximity
    days = _date_distance_days(transaction, attachment)
    if days is not None:
        if days == 0:
            score += 35.0
        elif days <= 3:
            score += 20.0
        elif days <= 7:
            score += 10.0

    # 3. Counterparty name similarity (max over recipient / issuer / supplier)
    ratio = _max_name_similarity(transaction, attachment)
    if ratio >= 0.90:
        score += 30.0
    elif ratio >= 0.80:
        score += 20.0
    elif ratio >= 0.70:
        score += 10.0

    return score

# Main functions
def find_attachment(
    transaction: Transaction,
    attachments: List[Attachment],
) -> Attachment | None:
    """
    To find the best matching attachment for a given transaction, the following strategy is implemented:
    1. Reference as priority:
       - If the transaction has a reference and exactly one attachment has the same normalized reference then return that attachment immediately
    2. Heuristic Scoring Fallback:
       - Otherwise, evaluate all attachments with _score_pair and return the
         highest-scoring one if its score exceeds the defined THRESHOLD
       - If no candidate passes the threshold, return None
    """
    # 1) Reference-based match (priority for 1:1 matches)
    tx_ref = _normalize_reference(transaction.get("reference"))
    if tx_ref:
        ref_matches: List[Attachment] = []
        for att in attachments:
            att_ref = _normalize_reference(att.get("data", {}).get("reference"))
            if att_ref and att_ref == tx_ref:
                ref_matches.append(att)

        if len(ref_matches) == 1:
            return ref_matches[0]
        
        # If there are 0 or >1 reference matches, fallback to heuristic scoring proposal

    # 2) Heuristic scoring
    best_attachment: Optional[Attachment] = None
    best_score: float = 0.0

    for attachment in attachments:
        score = _score_pair(transaction, attachment)
        if score > best_score:
            best_score = score
            best_attachment = attachment

    if best_score >= THRESHOLD:
        return best_attachment
    return None


def find_transaction(
    attachment: Attachment,
    transactions: List[Transaction],
) -> Transaction | None:
    """
    Find the best matching transaction for a given attachment, mirroring find_attachment strategy:
    1. Reference as priority:
       - If the attachment has a reference and exactly one transaction has the same normalized reference then return that transaction immediately
    2. Heuristic Scoring Fallback:
       - Otherwise, evaluate all transactions with _score_pair and return the
         highest-scoring one if its score exceeds the defined THRESHOLD
       - If no candidate passes the threshold, return None
    """
    # 1) Reference-based match
    att_ref = _normalize_reference(attachment.get("data", {}).get("reference"))
    if att_ref:
        ref_matches: List[Transaction] = []
        for tx in transactions:
            tx_ref = _normalize_reference(tx.get("reference"))
            if tx_ref and tx_ref == att_ref:
                ref_matches.append(tx)

        if len(ref_matches) == 1:
            return ref_matches[0]
        
        # If there are 0 or >1 reference matches, fallback to heuristic scoring proposal

    # 2) Heuristic scoring
    best_transaction: Optional[Transaction] = None
    best_score: float = 0.0

    for transaction in transactions:
        score = _score_pair(transaction, attachment)
        if score > best_score:
            best_score = score
            best_transaction = transaction

    if best_score >= THRESHOLD:
        return best_transaction
    return None

