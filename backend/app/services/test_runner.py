# ── Fix 1: test_runner.py ─────────────────────────────────────────────────────
# The problem: analyze_transaction() returns dicts with NaN floats from numpy.
# results_store stores them raw, then main.py tries json.dumps() → crash.
# Fix: clean each result BEFORE appending to results_store.

# In test_runner.py, change the process loop to this:

import os
import math
import pandas as pd
from .analyzer import analyze_transaction

BASE_DIR  = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
FILE_PATH = r"C:\pranav\fintech\data\test_transaction.csv"

results_store = []
progress      = {"total": 0, "processed": 0, "status": "idle"}
SAMPLE_SIZE   = 500


def _clean_nan(obj):
    """Recursively replace NaN/Inf floats with 0.0 so JSON serialization never fails."""
    if isinstance(obj, dict):
        return {k: _clean_nan(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_clean_nan(v) for v in obj]
    elif isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return 0.0
        return obj
    # numpy floats — catch them too
    try:
        import numpy as np
        if isinstance(obj, (np.floating, np.integer)):
            val = float(obj)
            return 0.0 if (math.isnan(val) or math.isinf(val)) else val
        if isinstance(obj, np.ndarray):
            return obj.tolist()
    except ImportError:
        pass
    return obj


def load_test_data(n=SAMPLE_SIZE):
    if not os.path.exists(FILE_PATH):
        raise FileNotFoundError(f"Test data not found at: {FILE_PATH}")
    df = pd.read_csv(FILE_PATH, nrows=n)
    print(f"✅ Loaded {len(df)} rows from {FILE_PATH}")
    return df.to_dict(orient="records")


def process_test_data():
    global results_store, progress

    results_store.clear()
    progress["processed"] = 0
    progress["total"]     = 0
    progress["status"]    = "running"

    try:
        test_data = load_test_data()
    except FileNotFoundError as e:
        print(f"❌ {e}")
        progress["status"] = f"error: {e}"
        return

    progress["total"] = len(test_data)

    for i, row in enumerate(test_data):
        try:
            result = analyze_transaction(row)
            # ✅ FIX: clean NaN BEFORE storing
            result = _clean_nan(result)
            results_store.append(result)
        except Exception as e:
            results_store.append({
                "error":       str(e),
                "transaction": {k: str(v) for k, v in row.items()}  # stringify row too
            })

        progress["processed"] = i + 1

        if (i + 1) % 50 == 0:
            print(f"   ...{i+1}/{progress['total']} done")

    progress["status"] = "complete"
    print(f"✅ Done. Processed {progress['processed']} transactions.")