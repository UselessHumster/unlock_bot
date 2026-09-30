import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import event, inspect

from unlock_bot.database import Database, IdentityConflictError


def make_database(tmp_path):
    database = Database(tmp_path / "bot.db")
    database.initialize()
    return database


def test_registration_links_telegram_and_max_to_one_profile(tmp_path):
    database = make_database(tmp_path)
    telegram = database.create_registration_request(
        platform="telegram",
        external_user_id=10,
        chat_id=10,
        display_name="Telegram User",
        username="telegram_user",
        requested_upn="USER@example.com",
    )
    telegram_decision = database.decide_registration(
        telegram.id, approved=True, decided_by_external_id=99
    )
    assert telegram_decision.changed is True

    max_request = database.create_registration_request(
        platform="max",
        external_user_id=20,
        chat_id=20,
        display_name="MAX User",
        username="max_user",
        requested_upn="user@example.com",
    )
    max_decision = database.decide_registration(
        max_request.id, approved=True, decided_by_external_id=99
    )

    telegram_identity = database.get_identity("telegram", 10)
    max_identity = database.get_identity("max", 20)
    assert max_decision.changed is True
    assert telegram_identity.profile_id == max_identity.profile_id
    assert telegram_identity.upn == max_identity.upn == "user@example.com"

    repeated = database.decide_registration(
        max_request.id, approved=True, decided_by_external_id=99
    )
    assert repeated.changed is False
    assert repeated.request.status == "approved"


def test_second_identity_on_same_platform_is_rejected(tmp_path):
    database = make_database(tmp_path)
    first = database.create_registration_request(
        platform="max",
        external_user_id=20,
        chat_id=20,
        display_name="First",
        username=None,
        requested_upn="user@example.com",
    )
    database.decide_registration(first.id, approved=True, decided_by_external_id=99)
    second = database.create_registration_request(
        platform="max",
        external_user_id=21,
        chat_id=21,
        display_name="Second",
        username=None,
        requested_upn="user@example.com",
    )

    with pytest.raises(IdentityConflictError):
        database.decide_registration(
            second.id, approved=True, decided_by_external_id=99
        )


def test_simultaneous_decisions_are_idempotent(tmp_path):
    database = make_database(tmp_path)
    request = database.create_registration_request(
        platform="max",
        external_user_id=20,
        chat_id=20,
        display_name="MAX User",
        username=None,
        requested_upn="user@example.com",
    )

    def approve():
        return database.decide_registration(
            request.id, approved=True, decided_by_external_id=99
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        decisions = list(executor.map(lambda _: approve(), range(2)))

    assert sorted(decision.changed for decision in decisions) == [False, True]
    assert database.get_identity("max", 20).upn == "user@example.com"


def test_legacy_users_are_migrated_without_deleting_source_table(tmp_path):
    path = tmp_path / "legacy.db"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE users ("
        "telegram_id INTEGER PRIMARY KEY, permissions VARCHAR(50), "
        "san VARCHAR(100) UNIQUE, upn VARCHAR(100) UNIQUE)"
    )
    connection.execute(
        "INSERT INTO users VALUES (?, ?, ?, ?)",
        (282760082, "admin", "admin@example.com", "admin@example.com"),
    )
    connection.commit()
    connection.close()

    database = Database(path)
    database.initialize()
    identity = database.get_identity("telegram", 282760082)

    assert identity.permissions == "admin"
    assert identity.upn == "admin@example.com"
    assert "users_legacy" in inspect(database.engine).get_table_names()


def test_interrupted_migration_rolls_back_and_retries(tmp_path):
    path = tmp_path / "interrupted.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE users (telegram_id INTEGER PRIMARY KEY, "
            "permissions TEXT, san TEXT UNIQUE, upn TEXT UNIQUE)"
        )
        connection.execute(
            "INSERT INTO users VALUES (1, 'admin', 'user', 'User@example.com')"
        )
    database = Database(path)

    def fail_copy(conn, cursor, statement, parameters, context, many):
        if statement.startswith("INSERT INTO external_identities"):
            raise RuntimeError("simulated failure")

    event.listen(database.engine, "before_cursor_execute", fail_copy)
    with pytest.raises(RuntimeError, match="simulated failure"):
        database.initialize()
    assert "users" in inspect(database.engine).get_table_names()
    event.remove(database.engine, "before_cursor_execute", fail_copy)
    database.initialize()
    assert database.get_identity("telegram", 1).permissions == "admin"
    backups = list(tmp_path.glob("*.bak"))
    database.initialize()
    assert list(tmp_path.glob("*.bak")) == backups

    request = database.create_registration_request(
        platform="max",
        external_user_id=2,
        chat_id=3,
        display_name="Test",
        username=None,
        requested_upn="user@example.com",
    )
    database.decide_registration(request.id, approved=True, decided_by_external_id=1)
    assert database.get_identity("max", 2).permissions == "admin"
