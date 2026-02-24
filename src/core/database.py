from __future__ import annotations

import random
from datetime import datetime, date, timedelta
from pathlib import Path

from sqlalchemy import (
    create_engine,
    inspect,
    text as sa_text,
    Column,
    Integer,
    String,
    DateTime,
    Text,
    ForeignKey,
    func,
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship

Base = declarative_base()

# Default title categories seeded on first run
DEFAULT_CATEGORIES = ["Global", "Pick-me", "BBW", "ALT", "BDSM", "Petite", "GND"]


class ProcessedFile(Base):
    __tablename__ = "processed_files"

    id = Column(Integer, primary_key=True)
    account_name = Column(String, index=True, nullable=False)
    file_id = Column(String, nullable=False)
    file_name = Column(String)
    processed_at = Column(DateTime, default=datetime.utcnow)
    tweet_id = Column(String)
    status = Column(String, default="pending")  # success | failed | pending
    use_count = Column(Integer, default=0)


class TitleCategory(Base):
    __tablename__ = "title_categories"

    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    titles = relationship("Title", back_populates="category", cascade="all, delete-orphan")


class Title(Base):
    __tablename__ = "titles"

    id = Column(Integer, primary_key=True)
    text = Column(Text, nullable=False)
    category_id = Column(Integer, ForeignKey("title_categories.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    category = relationship("TitleCategory", back_populates="titles")


class CtaText(Base):
    """Call-to-action texts that the bot comments on its own posts after a delay."""
    __tablename__ = "cta_texts"

    id = Column(Integer, primary_key=True)
    account_name = Column(String, index=True, nullable=False)
    text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Retweet(Base):
    __tablename__ = "retweets"

    id = Column(Integer, primary_key=True)
    account_name = Column(String, index=True, nullable=False)
    target_username = Column(String, nullable=False)
    tweet_id = Column(String, index=True, nullable=False)
    retweeted_at = Column(DateTime, default=datetime.utcnow)


class AccountStatus(Base):
    __tablename__ = "account_status"

    account_name = Column(String, primary_key=True)
    last_post = Column(DateTime)
    last_retweet = Column(DateTime)
    retweets_today = Column(Integer, default=0)
    retweets_date = Column(String)  # YYYY-MM-DD – used to reset counter daily
    status = Column(String, default="idle")  # idle | running | browsing | paused | error
    error_message = Column(Text)
    # Human simulation tracking
    sim_date = Column(String)          # YYYY-MM-DD – reset daily
    sim_sessions_today = Column(Integer, default=0)
    sim_likes_today = Column(Integer, default=0)
    # CTA self-comment tracking
    cta_pending = Column(Integer, default=0)  # 1 = needs CTA comment
    last_cta = Column(DateTime)


class TaskLog(Base):
    """Log of every task execution for analytics."""
    __tablename__ = "task_logs"

    id = Column(Integer, primary_key=True)
    account_name = Column(String, index=True, nullable=False)
    task_type = Column(String, nullable=False)
    executed_at = Column(DateTime, default=datetime.utcnow, index=True)
    status = Column(String, nullable=False)  # success | failed
    error_message = Column(Text)
    duration_seconds = Column(Integer, default=0)


class ReplyTracker(Base):
    """Tracks which tweet replies have already been answered."""
    __tablename__ = "reply_tracker"

    id = Column(Integer, primary_key=True)
    account_name = Column(String, index=True, nullable=False)
    original_tweet_id = Column(String, nullable=False)
    reply_tweet_id = Column(String, index=True, nullable=False)
    replied_at = Column(DateTime, default=datetime.utcnow)


class ReplyTemplate(Base):
    """Per-account reply templates for auto-replies."""
    __tablename__ = "reply_templates"

    id = Column(Integer, primary_key=True)
    account_name = Column(String, index=True, nullable=False)
    text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class GlobalTarget(Base):
    """Global retweet pool — accounts retweet posts from matching targets.

    ``content_rating`` ("sfw" or "nsfw") controls visibility: an SFW account
    only sees SFW targets; an NSFW account only sees NSFW targets.
    """
    __tablename__ = "global_targets"

    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    content_rating = Column(String, default="sfw")   # "sfw" | "nsfw"
    added_at = Column(DateTime, default=datetime.utcnow)


class TitleUsage(Base):
    """Per-account title usage tracking for fair rotation.

    Mirrors the ProcessedFile rotation pattern: titles with the lowest
    use_count are preferred so every title gets equal airtime.
    """
    __tablename__ = "title_usage"

    id = Column(Integer, primary_key=True)
    account_name = Column(String, index=True, nullable=False)
    title_id = Column(Integer, ForeignKey("titles.id", ondelete="CASCADE"), nullable=False)
    use_count = Column(Integer, default=0)


class Database:
    """Thin wrapper around SQLAlchemy for state tracking."""

    def __init__(self, db_path: str = "data/database/automation.db"):
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(
            f"sqlite:///{path}",
            echo=False,
            connect_args={"timeout": 30},
        )
        # Enable WAL mode for better concurrent read/write performance
        from sqlalchemy import event

        @event.listens_for(self.engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()
        self._migrate_retweets_table()
        Base.metadata.create_all(self.engine)
        self._migrate_add_columns()
        self._Session = sessionmaker(bind=self.engine)
        self._seed_categories()

    def _migrate_retweets_table(self) -> None:
        """Drop the old retweets table if it has a unique constraint on tweet_id."""
        insp = inspect(self.engine)
        if "retweets" not in insp.get_table_names():
            return
        for uq in insp.get_unique_constraints("retweets"):
            if "tweet_id" in uq.get("column_names", []):
                Retweet.__table__.drop(self.engine)
                return

    def _migrate_add_columns(self) -> None:
        """Add new columns to existing tables if they're missing (SQLite)."""
        insp = inspect(self.engine)
        migrations = {
            "account_status": {
                "sim_date": "VARCHAR",
                "sim_sessions_today": "INTEGER DEFAULT 0",
                "sim_likes_today": "INTEGER DEFAULT 0",
                "cta_pending": "INTEGER DEFAULT 0",
                "last_cta": "DATETIME",
            },
            "processed_files": {
                "use_count": "INTEGER DEFAULT 0",
            },
            "global_targets": {
                "content_rating": "VARCHAR DEFAULT 'sfw'",
            },
        }
        with self.engine.connect() as conn:
            for table, cols in migrations.items():
                if table not in insp.get_table_names():
                    continue
                existing = {c["name"] for c in insp.get_columns(table)}
                for col_name, col_type in cols.items():
                    if col_name not in existing:
                        conn.execute(
                            sa_text(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}")
                        )
                        conn.commit()

        # Drop unique constraint on processed_files.file_id if it exists
        # (rotation requires the same file_id for different accounts)
        if "processed_files" in insp.get_table_names():
            for uq in insp.get_unique_constraints("processed_files"):
                if "file_id" in uq.get("column_names", []):
                    ProcessedFile.__table__.drop(self.engine)
                    Base.metadata.create_all(self.engine)
                    return

    def _seed_categories(self) -> None:
        """Ensure default title categories exist."""
        with self.session() as s:
            for name in DEFAULT_CATEGORIES:
                existing = s.query(TitleCategory).filter_by(name=name).first()
                if not existing:
                    s.add(TitleCategory(name=name))
            s.commit()

    def session(self) -> Session:
        return self._Session()

    # ----- Processed files / Content rotation -----
    def is_file_processed(self, file_id: str) -> bool:
        """Legacy check: returns True if the file has been used at least once."""
        with self.session() as s:
            row = s.query(ProcessedFile).filter_by(file_id=file_id).first()
            return row is not None and (row.use_count or 0) > 0

    def get_file_use_count(self, account_name: str, file_id: str) -> int:
        """Return how many times a file has been used by an account."""
        with self.session() as s:
            row = (
                s.query(ProcessedFile)
                .filter_by(account_name=account_name, file_id=file_id)
                .first()
            )
            if not row:
                return 0
            return row.use_count or 0

    def get_least_used_file(self, account_name: str, file_ids: list[str]) -> str | None:
        """Pick the file_id with the lowest use_count for this account.

        Files never used before (use_count=0) are preferred.
        Among equally-used files, one is picked at random.
        """
        if not file_ids:
            return None

        with self.session() as s:
            # Build dict of file_id -> use_count
            counts: dict[str, int] = {}
            for fid in file_ids:
                row = (
                    s.query(ProcessedFile)
                    .filter_by(account_name=account_name, file_id=fid)
                    .first()
                )
                counts[fid] = (row.use_count or 0) if row else 0

        min_count = min(counts.values())
        candidates = [fid for fid, c in counts.items() if c == min_count]
        return random.choice(candidates)

    def increment_file_use(
        self, account_name: str, file_id: str, file_name: str,
        tweet_id: str | None = None, status: str = "success",
    ) -> None:
        """Record a file usage: create or increment use_count."""
        with self.session() as s:
            row = (
                s.query(ProcessedFile)
                .filter_by(account_name=account_name, file_id=file_id)
                .first()
            )
            if row:
                row.use_count = (row.use_count or 0) + 1
                row.processed_at = datetime.utcnow()
                row.tweet_id = tweet_id
                row.status = status
            else:
                s.add(ProcessedFile(
                    account_name=account_name,
                    file_id=file_id,
                    file_name=file_name,
                    tweet_id=tweet_id,
                    status=status,
                    use_count=1,
                ))
            s.commit()

    def mark_file_processed(
        self, account_name: str, file_id: str, file_name: str,
        tweet_id: str | None = None, status: str = "success",
    ) -> None:
        """Legacy wrapper — now delegates to increment_file_use."""
        self.increment_file_use(account_name, file_id, file_name, tweet_id, status)

    # ----- Title categories -----
    def get_all_categories(self) -> list[TitleCategory]:
        with self.session() as s:
            return s.query(TitleCategory).order_by(TitleCategory.name).all()

    def get_category(self, category_id: int) -> TitleCategory | None:
        with self.session() as s:
            return s.query(TitleCategory).get(category_id)

    def get_category_by_name(self, name: str) -> TitleCategory | None:
        with self.session() as s:
            return s.query(TitleCategory).filter_by(name=name).first()

    def add_category(self, name: str) -> TitleCategory:
        with self.session() as s:
            cat = TitleCategory(name=name)
            s.add(cat)
            s.commit()
            s.refresh(cat)
            return cat

    def delete_category(self, category_id: int) -> bool:
        with self.session() as s:
            cat = s.query(TitleCategory).get(category_id)
            if not cat:
                return False
            s.delete(cat)
            s.commit()
            return True

    # ----- Titles -----
    def get_titles_by_category(self, category_id: int) -> list[Title]:
        with self.session() as s:
            return (
                s.query(Title)
                .filter_by(category_id=category_id)
                .order_by(Title.created_at.desc())
                .all()
            )

    def get_titles_by_category_names(self, category_names: list[str]) -> list[Title]:
        """Get all titles belonging to the named categories."""
        with self.session() as s:
            cats = (
                s.query(TitleCategory)
                .filter(TitleCategory.name.in_(category_names))
                .all()
            )
            cat_ids = [c.id for c in cats]
            if not cat_ids:
                return []
            return (
                s.query(Title)
                .filter(Title.category_id.in_(cat_ids))
                .all()
            )

    def get_random_title(self, category_names: list[str], account_name: str | None = None) -> str | None:
        """Pick the least-used title from the given categories for this account.

        Uses the same rotation strategy as content files: titles with the
        lowest use_count are preferred so every title gets airtime before
        any repeats.  Falls back to pure random when no account is given.

        Always includes "Global" category.
        """
        names = list(set(category_names) | {"Global"})
        titles = self.get_titles_by_category_names(names)
        if not titles:
            return None

        if not account_name:
            return random.choice(titles).text

        # Least-used-first rotation per account
        with self.session() as s:
            counts: dict[int, int] = {}
            for t in titles:
                usage = (
                    s.query(TitleUsage)
                    .filter_by(account_name=account_name, title_id=t.id)
                    .first()
                )
                counts[t.id] = (usage.use_count or 0) if usage else 0

        min_count = min(counts.values())
        candidates = [t for t in titles if counts[t.id] == min_count]
        return random.choice(candidates).text

    def increment_title_use(self, account_name: str, title_text: str, category_names: list[str]) -> None:
        """Increment usage counter for a title after it's been posted."""
        names = list(set(category_names) | {"Global"})
        with self.session() as s:
            # Find the title by text in the relevant categories
            cats = s.query(TitleCategory).filter(TitleCategory.name.in_(names)).all()
            cat_ids = [c.id for c in cats]
            if not cat_ids:
                return
            title = (
                s.query(Title)
                .filter(Title.category_id.in_(cat_ids), Title.text == title_text)
                .first()
            )
            if not title:
                return
            usage = (
                s.query(TitleUsage)
                .filter_by(account_name=account_name, title_id=title.id)
                .first()
            )
            if usage:
                usage.use_count = (usage.use_count or 0) + 1
            else:
                s.add(TitleUsage(account_name=account_name, title_id=title.id, use_count=1))
            s.commit()

    def add_title(self, text: str, category_id: int) -> Title:
        with self.session() as s:
            title = Title(text=text, category_id=category_id)
            s.add(title)
            s.commit()
            s.refresh(title)
            return title

    def bulk_add_titles(self, texts: list[str], category_id: int) -> int:
        """Add multiple titles to a category. Returns count of titles added."""
        added = 0
        with self.session() as s:
            for text in texts:
                text = text.strip()
                if not text:
                    continue
                s.add(Title(text=text, category_id=category_id))
                added += 1
            s.commit()
        return added

    def delete_title(self, title_id: int) -> bool:
        with self.session() as s:
            title = s.query(Title).get(title_id)
            if not title:
                return False
            s.delete(title)
            s.commit()
            return True

    def get_all_titles(self) -> list[Title]:
        with self.session() as s:
            return s.query(Title).order_by(Title.category_id, Title.created_at.desc()).all()

    # ----- CTA texts -----
    def get_cta_texts(self, account_name: str) -> list[CtaText]:
        with self.session() as s:
            return (
                s.query(CtaText)
                .filter_by(account_name=account_name)
                .order_by(CtaText.created_at.desc())
                .all()
            )

    def get_random_cta(self, account_name: str) -> str | None:
        """Pick a random CTA text for an account."""
        ctas = self.get_cta_texts(account_name)
        if not ctas:
            return None
        return random.choice(ctas).text

    def add_cta_text(self, account_name: str, text: str) -> CtaText:
        with self.session() as s:
            cta = CtaText(account_name=account_name, text=text)
            s.add(cta)
            s.commit()
            s.refresh(cta)
            return cta

    def delete_cta_text(self, cta_id: int) -> bool:
        with self.session() as s:
            cta = s.query(CtaText).get(cta_id)
            if not cta:
                return False
            s.delete(cta)
            s.commit()
            return True

    # ----- Retweets -----
    def is_already_retweeted(self, account_name: str, tweet_id: str) -> bool:
        with self.session() as s:
            return (
                s.query(Retweet)
                .filter_by(account_name=account_name, tweet_id=tweet_id)
                .first()
                is not None
            )

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

    # ----- Task logging (analytics) -----
    def log_task(
        self,
        account_name: str,
        task_type: str,
        status: str,
        error_message: str | None = None,
        duration_seconds: int = 0,
    ) -> None:
        with self.session() as s:
            s.add(TaskLog(
                account_name=account_name,
                task_type=task_type,
                status=status,
                error_message=error_message,
                duration_seconds=duration_seconds,
            ))
            s.commit()

    def get_daily_activity(self, days: int = 30) -> list[dict]:
        """Return daily task counts for the last N days."""
        cutoff = datetime.utcnow() - timedelta(days=days)
        with self.session() as s:
            rows = (
                s.query(
                    func.date(TaskLog.executed_at).label("day"),
                    TaskLog.status,
                    func.count().label("cnt"),
                )
                .filter(TaskLog.executed_at >= cutoff)
                .group_by("day", TaskLog.status)
                .order_by("day")
                .all()
            )
            return [{"day": str(r.day), "status": r.status, "count": r.cnt} for r in rows]

    def get_success_failure_counts(self, days: int = 30) -> dict:
        """Return total success vs failure counts."""
        cutoff = datetime.utcnow() - timedelta(days=days)
        with self.session() as s:
            rows = (
                s.query(TaskLog.status, func.count().label("cnt"))
                .filter(TaskLog.executed_at >= cutoff)
                .group_by(TaskLog.status)
                .all()
            )
            return {r.status: r.cnt for r in rows}

    def get_per_account_stats(self, days: int = 30) -> list[dict]:
        """Return per-account task statistics."""
        cutoff = datetime.utcnow() - timedelta(days=days)
        with self.session() as s:
            rows = (
                s.query(
                    TaskLog.account_name,
                    TaskLog.task_type,
                    TaskLog.status,
                    func.count().label("cnt"),
                )
                .filter(TaskLog.executed_at >= cutoff)
                .group_by(TaskLog.account_name, TaskLog.task_type, TaskLog.status)
                .all()
            )
            return [
                {"account": r.account_name, "task_type": r.task_type,
                 "status": r.status, "count": r.cnt}
                for r in rows
            ]

    def get_file_use_distribution(self) -> list[dict]:
        """Return content rotation stats: use_count distribution per account."""
        with self.session() as s:
            rows = (
                s.query(
                    ProcessedFile.account_name,
                    ProcessedFile.use_count,
                    func.count().label("cnt"),
                )
                .group_by(ProcessedFile.account_name, ProcessedFile.use_count)
                .order_by(ProcessedFile.account_name, ProcessedFile.use_count)
                .all()
            )
            return [
                {"account": r.account_name, "use_count": r.use_count or 0, "files": r.cnt}
                for r in rows
            ]

    # ----- Reply tracking -----
    def is_reply_tracked(self, account_name: str, reply_tweet_id: str) -> bool:
        """Check if we've already replied to this tweet."""
        with self.session() as s:
            return (
                s.query(ReplyTracker)
                .filter_by(account_name=account_name, reply_tweet_id=reply_tweet_id)
                .first()
                is not None
            )

    def record_reply(
        self, account_name: str, original_tweet_id: str, reply_tweet_id: str,
    ) -> None:
        with self.session() as s:
            s.add(ReplyTracker(
                account_name=account_name,
                original_tweet_id=original_tweet_id,
                reply_tweet_id=reply_tweet_id,
            ))
            s.commit()

    def get_replies_today(self, account_name: str) -> int:
        """Count replies made today."""
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        with self.session() as s:
            return (
                s.query(ReplyTracker)
                .filter(
                    ReplyTracker.account_name == account_name,
                    ReplyTracker.replied_at >= today_start,
                )
                .count()
            )

    # ----- Reply templates -----
    def get_reply_templates(self, account_name: str) -> list[ReplyTemplate]:
        with self.session() as s:
            return (
                s.query(ReplyTemplate)
                .filter_by(account_name=account_name)
                .order_by(ReplyTemplate.created_at.desc())
                .all()
            )

    def get_random_reply_template(self, account_name: str) -> str | None:
        templates = self.get_reply_templates(account_name)
        if not templates:
            return None
        return random.choice(templates).text

    def add_reply_template(self, account_name: str, text: str) -> ReplyTemplate:
        with self.session() as s:
            tpl = ReplyTemplate(account_name=account_name, text=text)
            s.add(tpl)
            s.commit()
            s.refresh(tpl)
            return tpl

    def delete_reply_template(self, template_id: int) -> bool:
        with self.session() as s:
            tpl = s.query(ReplyTemplate).get(template_id)
            if not tpl:
                return False
            s.delete(tpl)
            s.commit()
            return True

    # ----- Global targets (shared retweet pool) -----
    def get_global_targets(self) -> list[GlobalTarget]:
        with self.session() as s:
            return s.query(GlobalTarget).order_by(GlobalTarget.added_at.desc()).all()

    def get_global_target_usernames(self, content_rating: str | None = None) -> list[str]:
        """Return usernames, optionally filtered by content_rating ("sfw"/"nsfw")."""
        with self.session() as s:
            q = s.query(GlobalTarget)
            if content_rating:
                q = q.filter_by(content_rating=content_rating)
            return [t.username for t in q.all()]

    def add_global_target(
        self, username: str, content_rating: str = "sfw",
    ) -> GlobalTarget | None:
        """Add a username to the global pool. Returns None if it already exists."""
        clean = username.strip().lstrip("@")
        if not clean:
            return None
        handle = f"@{clean}"
        rating = content_rating if content_rating in ("sfw", "nsfw") else "sfw"
        with self.session() as s:
            existing = s.query(GlobalTarget).filter_by(username=handle).first()
            if existing:
                return existing
            target = GlobalTarget(username=handle, content_rating=rating)
            s.add(target)
            s.commit()
            s.refresh(target)
            return target

    def update_global_target(self, old_username: str, new_username: str) -> None:
        """Rename a global target (e.g. when an account's twitter handle changes)."""
        old_handle = f"@{old_username.strip().lstrip('@')}"
        new_handle = f"@{new_username.strip().lstrip('@')}"
        if old_handle == new_handle:
            return
        with self.session() as s:
            target = s.query(GlobalTarget).filter_by(username=old_handle).first()
            if target:
                # Check if new handle already exists
                dup = s.query(GlobalTarget).filter_by(username=new_handle).first()
                if dup:
                    # New handle already in pool — just remove the old one
                    s.delete(target)
                else:
                    target.username = new_handle
                s.commit()

    def update_global_target_rating(self, target_id: int, content_rating: str) -> bool:
        """Update the content_rating of a global target."""
        if content_rating not in ("sfw", "nsfw"):
            return False
        with self.session() as s:
            target = s.query(GlobalTarget).get(target_id)
            if not target:
                return False
            target.content_rating = content_rating
            s.commit()
            return True

    def delete_global_target(self, target_id: int) -> bool:
        with self.session() as s:
            target = s.query(GlobalTarget).get(target_id)
            if not target:
                return False
            s.delete(target)
            s.commit()
            return True
