import math
import threading
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.services.fraudster_ai import FraudsterAI
from app.services.test_runner import process_test_data, results_store, progress
from app.services.analyzer import analyze_transaction
from schemas.transaction import TransactionRequest, FraudDetectionResponse
from app.services.fraud_detection import predict_transaction
from database import SessionLocal, engine, Base
from crud import create_transaction, get_user_history
from fastapi import Depends
from sqlalchemy.orm import Session
import json
from dotenv import load_dotenv
import os

load_dotenv()  # will pick from root if run correctly

api_key = os.getenv("GROQ_API_KEY")


app = FastAPI(
    title="PS-FIN-01: AI Fraud Detection API",
    description=(
        "Dual-layer fraud detection system:\n"
        "1. Fast ML + Rules scoring\n"
        "2. Deep AI analysis with context + compliance + LLM"
    ),
    version="1.0.0",
)
Base.metadata.create_all(bind=engine)

# ── CORS ────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── NaN sanitizer (fixes: ValueError: Out of range float values) ─────────
def _safe_json(obj):
    if isinstance(obj, dict):
        return {k: _safe_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_safe_json(v) for v in obj]
    elif isinstance(obj, float):
        return 0.0 if (math.isnan(obj) or math.isinf(obj)) else obj
    try:
        import numpy as np
        if isinstance(obj, (np.floating, np.integer)):
            val = float(obj)
            return 0.0 if (math.isnan(val) or math.isinf(val)) else val
    except ImportError:
        pass
    return obj

# ── Health ──────────────────────────────────────────────────────────────
@app.get("/", tags=["Health"])
def root():
    return {"status": "ok", "service": "Fraud Detection API v2.0"}


@app.get("/health", tags=["Health"])
def health():
    return {"status": "healthy"}


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

        
# ── SIMPLE PIPELINE (ML + RULES) ─────────────────────────────────────────
@app.post("/api/v1/predict")
def predict_simple(request: TransactionRequest):
    try:
        return predict_transaction(request)
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Model artifacts not found. ({e})",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── ADVANCED PIPELINE (FULL AI SYSTEM) ───────────────────────────────────


@app.post("/api/v1/analyze", response_model=FraudDetectionResponse)
def analyze(request: TransactionRequest, db: Session = Depends(get_db)):
    

    try:
        # 1. Fetch user history
        history = get_user_history(db, request.user_id)

        # 2. Pass history into analyzer
        result = analyze_transaction(request, history)

        # 3. Store current transaction
        create_transaction(db, request)

        return JSONResponse(content=_safe_json(result))  # ← fixed

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        db.close()


# ── SAMPLE PAYLOAD ──────────────────────────────────────────────────────
@app.get("/api/v1/sample", tags=["Fraud Detection"])
def sample_payload():
    return {
        "sample": {
    "user_id": "U001",
    "amount": 25000.0,
    "time": "02:15",
    "state": "Maharashtra",
    "is_new_device": True,
    "ip_address": "192.168.1.1"
}
    }


# ── TEST DATA RUNNER ────────────────────────────────────────────────────
@app.post("/run-test-data")
def run_test():
    thread = threading.Thread(target=process_test_data, daemon=True)
    thread.start()
    return {"message": "Processing started"}


@app.get("/results")
def get_results():
    response = {
        "count": len(results_store),
        "results": results_store[:100]
    }
    return JSONResponse(content=_safe_json(response))  # ← fixed


@app.get("/progress")
def get_progress():
    return {
        "total": progress["total"],
        "processed": progress["processed"],
        "status": progress["status"],
    }

fraud_ai = FraudsterAI()
@app.get("/fraud-stress-test")
def stress_test():
    result = fraud_ai.run_all_attacks()
    return {
        "status": "success",
        "data": result
    }