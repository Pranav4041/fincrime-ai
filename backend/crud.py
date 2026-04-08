from sqlalchemy.orm import Session
from models import Transaction


# 1. Store transaction
def create_transaction(db: Session, txn_data):
    new_txn = Transaction(
        user_id=txn_data.user_id,
        amount=txn_data.amount,
        time=txn_data.time,
        state=txn_data.state,
        is_new_device=txn_data.is_new_device,
        ip_address=txn_data.ip_address
    )
    db.add(new_txn)
    db.commit()
    db.refresh(new_txn)
    return new_txn


# 2. Get last N transactions for a user
def get_user_history(db: Session, user_id: str, limit: int = 5):
    return (
        db.query(Transaction)
        .filter(Transaction.user_id == user_id)
        .order_by(Transaction.timestamp.desc())
        .limit(limit)
        .all()
    )


# 3. (Optional but powerful) Get avg amount
def get_avg_amount(history):
    if not history:
        return 0
    return sum(txn.amount for txn in history) / len(history)