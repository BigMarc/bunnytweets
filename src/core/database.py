from datetime import datetime, date
from pathlib import Path

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    DateTime,
    Text,
    func,
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session

Base = declarative_base()


class ProcessedFile(Base):
    __tablename__ = "processed_files"

    id = Column(Integer, primary_key=True)
    account_name = Column(String, index=True, nullable=False)
    file_id = Column(String, unique=True, nullable=False)
    file_name = Column(String)
    processed_at = Column(DateTime, default=datetime.utcnow)
    tweet_id = Column(String)
    status = Column(String, default="pending")  # success | failed | pending


class Retweet(Base):
    __tablename__ = "retweets"

    id = Column(Integer, primary_key=True)
    account_name = Column(String, index=True, nullable=False)
    target_username = Column(String, nullable=False)
    tweet_id = Column(String, unique=True, nullable=False)
    retweeted_at = Column(DateTime, default=datetime.utcnow)


class AccountStatus(Base):
    __tablename__ = "account_status"

    account_name = Column(String, primary_key=True)
    last_post = Column(DateTime)
    last_retweet = Column(DateTime)
    retweets_today = Column(Integer, default=0)
    retweets_date = Column(String)  # YYYY-MM-DD – used to reset counter daily
    status = Column(String, default="idle")  # idle | running | paused | error
    error_message = Column(Text)


class Database:
    """Thin wrapper around SQLAlchemy for state tracking."""

    def __init__(self, db_path: str = "data/database/automation.db"):
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{path}", echo=False)
        Base.metadata.create_all(self.engine)
        self._Session = sessionmaker(bind=self.engine)

    def session(self) -> Session:
        return self._Session()

    # ----- Processed files -----
    def is_file_processed(self, file_id: str) -> bool:
        with self.session() as s:
            return s.query(ProcessedFile).filter_by(file_id=file_id).first() is not None

    def mark_file_processed(
        self, account_name: str, file_id: str, file_name: str, tweet_id: str | None = None, status: str = "success"
    ) -> None:
        with self.session() as s:
            entry = ProcessedFile(
                account_name=account_name,
                file_id=file_id,
                file_name=file_name,
                tweet_id=tweet_id,
                status=status,
            )
            s.merge(entry)
            s.commit()

    # ----- Retweets -----
    def is_already_retweeted(self, tweet_id: str) -> bool:
        with self.session() as s:
            return s.query(Retweet).filter_by(tweet_id=tweet_id).first() is not None

    def record_retweet(self, account_name: str, target_username: str, tweet_id: str) -> None:
        with self.session() as s:
            entry = Retweet(
                account_name=account_name,
                target_username=target_username,
                tweet_id=tweet_id,
            )
            s.add(entry)
            s.commit()

    # ----- Account status -----
    def get_account_status(self, account_name: str) -> AccountStatus | None:
        with self.session() as s:
            return s.query(AccountStatus).filter_by(account_name=account_name).first()

    def update_account_status(self, account_name: str, **kwargs) -> None:
        with self.session() as s:
            status = s.query(AccountStatus).filter_by(account_name=account_name).first()
            if not status:
                status = AccountStatus(account_name=account_name)
                s.add(status)
            for k, v in kwargs.items():
                setattr(status, k, v)
            s.commit()

    def get_retweets_today(self, account_name: str) -> int:
        """Return count of retweets for today, resetting counter on new day."""
        today = date.today().isoformat()
        with self.session() as s:
            status = s.query(AccountStatus).filter_by(account_name=account_name).first()
            if not status:
                return 0
            if status.retweets_date != today:
                status.retweets_today = 0
                status.retweets_date = today
                s.commit()
                return 0
            return status.retweets_today or 0

    def increment_retweets_today(self, account_name: str) -> None:
        today = date.today().isoformat()
        with self.session() as s:
            status = s.query(AccountStatus).filter_by(account_name=account_name).first()
            if not status:
                status = AccountStatus(
                    account_name=account_name,
                    retweets_today=1,
                    retweets_date=today,
                )
                s.add(status)
            else:
                if status.retweets_date != today:
                    status.retweets_today = 1
                    status.retweets_date = today
                else:
                    status.retweets_today = (status.retweets_today or 0) + 1
            s.commit()

    def get_pending_files(self, account_name: str) -> list[ProcessedFile]:
        with self.session() as s:
            return (
                s.query(ProcessedFile)
                .filter_by(account_name=account_name, status="pending")
                .all()
            )
