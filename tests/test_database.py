"""Tests for the Database state-tracking layer."""

import tempfile
import os
from datetime import date

import pytest

from src.core.database import Database


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    return Database(db_path)


class TestProcessedFiles:
    def test_mark_and_check(self, db):
        assert not db.is_file_processed("file_001")
        db.mark_file_processed("acct1", "file_001", "photo.jpg", status="success")
        assert db.is_file_processed("file_001")

    def test_duplicate_file_id(self, db):
        db.mark_file_processed("acct1", "file_001", "a.jpg", status="success")
        # merge should not raise on duplicate
        db.mark_file_processed("acct1", "file_001", "a.jpg", tweet_id="t123", status="success")
        assert db.is_file_processed("file_001")

    def test_pending_files(self, db):
        db.mark_file_processed("acct1", "f1", "a.jpg", status="pending")
        db.mark_file_processed("acct1", "f2", "b.jpg", status="success")
        db.mark_file_processed("acct2", "f3", "c.jpg", status="pending")
        pending = db.get_pending_files("acct1")
        assert len(pending) == 1
        assert pending[0].file_id == "f1"


class TestRetweets:
    def test_record_and_check(self, db):
        assert not db.is_already_retweeted("acct1", "tw_001")
        db.record_retweet("acct1", "@target", "tw_001")
        assert db.is_already_retweeted("acct1", "tw_001")

    def test_different_accounts_same_tweet(self, db):
        db.record_retweet("acct1", "@t", "tw_100")
        # Different accounts CAN retweet the same tweet independently
        db.record_retweet("acct2", "@t", "tw_100")
        assert db.is_already_retweeted("acct1", "tw_100")
        assert db.is_already_retweeted("acct2", "tw_100")
        # But acct3 hasn't retweeted it
        assert not db.is_already_retweeted("acct3", "tw_100")


class TestAccountStatus:
    def test_update_and_get(self, db):
        db.update_account_status("acct1", status="running")
        st = db.get_account_status("acct1")
        assert st is not None
        assert st.status == "running"

    def test_retweets_today_counter(self, db):
        assert db.get_retweets_today("acct1") == 0
        db.increment_retweets_today("acct1")
        assert db.get_retweets_today("acct1") == 1
        db.increment_retweets_today("acct1")
        assert db.get_retweets_today("acct1") == 2

    def test_retweets_today_resets_on_new_day(self, db):
        # Manually set yesterday's date
        db.update_account_status("acct1", retweets_today=5, retweets_date="2020-01-01")
        # get_retweets_today should detect the old date and reset
        assert db.get_retweets_today("acct1") == 0
