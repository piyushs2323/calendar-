from datetime import date, timedelta
from sqlalchemy import create_engine, Column, Integer, String, Date, String as Str
from sqlalchemy.orm import declarative_base, sessionmaker
import config

engine = create_engine(config.DATABASE_URL, future=True)
Session = sessionmaker(bind=engine, future=True)
Base = declarative_base()


class BuyerAccount(Base):
    __tablename__ = "buyer_accounts"

    id = Column(Integer, primary_key=True)
    buyer_name = Column(String, nullable=False)
    email = Column(String, nullable=False)
    date_given = Column(Date, nullable=False)
    expiry_date = Column(Date, nullable=False)
    status = Column(String, default="active")  # active | pending_action | renewed | revoked
    notes = Column(Str, default="")

    def days_left(self):
        return (self.expiry_date - date.today()).days


def init_db():
    Base.metadata.create_all(engine)


def add_account(buyer_name, email, date_given, plan_days=None):
    plan_days = plan_days or config.DEFAULT_PLAN_DAYS
    expiry = date_given + timedelta(days=plan_days)
    session = Session()
    acc = BuyerAccount(
        buyer_name=buyer_name,
        email=email,
        date_given=date_given,
        expiry_date=expiry,
        status="active",
    )
    session.add(acc)
    session.commit()
    session.refresh(acc)
    session.close()
    return acc


def get_account(account_id):
    session = Session()
    acc = session.get(BuyerAccount, account_id)
    session.close()
    return acc


def list_active():
    session = Session()
    accs = session.query(BuyerAccount).filter(BuyerAccount.status.in_(["active", "pending_action"])).order_by(BuyerAccount.expiry_date).all()
    session.close()
    return accs


def list_due(today=None):
    today = today or date.today()
    session = Session()
    accs = session.query(BuyerAccount).filter(
        BuyerAccount.status == "active",
        BuyerAccount.expiry_date <= today,
    ).all()
    session.close()
    return accs


def set_status(account_id, status):
    session = Session()
    acc = session.get(BuyerAccount, account_id)
    if acc:
        acc.status = status
        session.commit()
    session.close()


def renew_account(account_id, plan_days=None):
    plan_days = plan_days or config.DEFAULT_PLAN_DAYS
    session = Session()
    acc = session.get(BuyerAccount, account_id)
    if acc:
        acc.expiry_date = acc.expiry_date + timedelta(days=plan_days)
        acc.status = "active"
        session.commit()
        session.refresh(acc)
    session.close()
    return acc


def delete_account(account_id):
    session = Session()
    acc = session.get(BuyerAccount, account_id)
    if acc:
        session.delete(acc)
        session.commit()
    session.close()
