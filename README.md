# NOCFO Homework Assignment - AI Engineer 
Biaani Cabrera

## Requirements

1. Python 3.10+
2. Clone the repository
3. Run:
```py
python3 run.py
```
No external dependencies or additional setup tools are required.


## Architecture and Technical Approach

All matching logic is located in:
```py
src/match.py
```
The algorithm uses a two-stage deterministic strategy, combining strict rules with explainable heuristic scoring.

## 1. Reference-First Matching

If both sides contain a reference number:
- The reference is normalized (spaces removed, uppercase enforced, numeric zero-padding stripped).
- If exactly one attachment has the same normalized reference, it is returned immediately.

This follows the assignment: a reference match is always a 1:1 match

## 2. Heuristic Scoring Fallback 

If no unique reference match exists, each attachment receives a score based on three independent signals:
- **Amount similarity**: Absolute values comparison, tolerant to sign differences.
- **Date proximity**: Difference between `transaction date` and any attachment date: `invoicing_date`, `due_date`, or `receiving_date`.
- **Counterparty name similarity**: The transaction’s `contact` is compared against the attachment’s `recipient`, `issuer`, and `supplier` fields using deterministic character-level similarity.

A match is accepted if its score ≥ 75.
If no attachment reaches this confidence threshold, the function returns `None`, ensuring safe behavior under ambiguity.

*This fallback ensures accurate matching even when reference numbers are absent or unreliable.*


## Bidirectional Logic

The two required functions:
- `find_attachment(transaction, attachments)`
- `find_transaction(attachment, transactions)` 

Using the same two-stage logic in opposite directions to guarantee consistent and deterministic matching.


## Assumptions

The matching logic relies on several practical assumptions based on how real-world bank data and attachments behave:

**References**
Reference numbers are the strongest possible matching signal. If reference information is missing or inconsistent, heuristics decide the match.

**Amount Interpretation**
Transaction amounts may be negative (expenses) or positive (incoming payments), while attachment amounts are always positive. Because the sign does not reliably reflect document type, comparisons use absolute values.

**Payment Dates**
Payment dates often differ from due dates due to early payments, late payments, or bank processing delays.
Therefore, the algorithm evaluates date proximity, not equality between the `transaction date` and all relevant attachment dates (`invoicing_date`, `due_date`, or `receiving_date`), using the minimum distance to any attachment date.

**Counterparty Location Variation**
Depending on whether the attachment is a sales invoice, purchase invoice, or receipt, the counterparty name may appear under `recipient`, `issuer`, or `supplier`. 
To avoid false negatives, the algorithm evaluates all these fields and chooses the best name similarity score.

**Ambiguity Fallback**
If neither reference matching nor heuristic scoring yields a confident match, the function returns `None` instead of making an unsafe guess.


## Demonstration Correctness
`run.py` validates the solution by comparing all produced matches against the expected results.
