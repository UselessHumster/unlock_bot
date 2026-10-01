import asyncio
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from telegram_with_max import Platform

from unlock_bot.ad.worker import ADWorker
from unlock_bot.config import Settings
from unlock_bot.database import Database
from unlock_bot.messaging.handlers import BotController
from unlock_bot.messaging.states import RegistrationStates


class FakeState:
    def __init__(self):
        self.value = None

    async def set_state(self, state):
        self.value = str(state)

    async def clear(self):
        self.value = None


class FakeMessage:
    def __init__(
        self,
        *,
        platform=Platform.MAX,
        user_id=20,
        chat_id=20,
        text=None,
        display_name="MAX User",
        username="max_user",
    ):
        self.platform = platform
        self.user_id = user_id
        self.chat_id = chat_id
        self.text = text
        self.display_name = display_name
        self.username = username
        self.answer = AsyncMock()
        self.edit_text = AsyncMock()


def make_controller(tmp_path):
    database = Database(tmp_path / "bot.db")
    database.initialize()
    settings = Settings(
        telegram_bot_token="telegram-token",
        max_bot_token="max-token",
        domains=("example.com",),
        search_zone="OU=Users,DC=example,DC=com",
        admin_chat=99,
        database_path=str(tmp_path / "bot.db"),
    )
    app = SimpleNamespace(send_message=AsyncMock())
    return BotController(app=app, database=database, settings=settings), app, database


async def register_max_user(controller, database, *, user_id=20):
    request = database.create_registration_request(
        platform="max",
        external_user_id=user_id,
        chat_id=user_id,
        display_name="MAX User",
        username="max_user",
        requested_upn="user@example.com",
    )
    database.decide_registration(request.id, approved=True, decided_by_external_id=99)


async def test_start_uses_common_state_for_max(tmp_path):
    controller, _, _ = make_controller(tmp_path)
    message = FakeMessage(text="/start")
    state = FakeState()

    await controller.command_start(message, state)

    assert state.value == str(RegistrationStates.await_email)
    message.answer.assert_awaited_once_with("Введите вашу рабочую почту")


async def test_max_registration_is_approved_from_telegram(tmp_path, monkeypatch):
    controller, app, database = make_controller(tmp_path)
    monkeypatch.setattr(
        "unlock_bot.messaging.handlers.is_ad_user_exists", lambda upn: True
    )
    message = FakeMessage(text="user@example.com")
    state = FakeState()

    await controller.register_email(message, state)

    admin_call = app.send_message.await_args_list[0]
    assert admin_call.kwargs["platform"] is Platform.TELEGRAM
    keyboard = admin_call.kwargs["reply_markup"]
    request_id = keyboard.rows[0][0].callback_data.split(":")[1]

    admin_message = FakeMessage(
        platform=Platform.TELEGRAM,
        user_id=99,
        chat_id=99,
        text="request",
        display_name="Admin",
        username="admin",
    )
    callback = SimpleNamespace(
        platform=Platform.TELEGRAM,
        user_id=99,
        data=f"reg:{request_id}:yes",
        message=admin_message,
        answer=AsyncMock(),
    )
    await controller.admin_decision(callback)

    assert database.get_identity("max", 20).upn == "user@example.com"
    user_call = app.send_message.await_args_list[1]
    assert user_call.kwargs["platform"] is Platform.MAX
    assert user_call.kwargs["chat_id"] == 20
    admin_message.edit_text.assert_awaited_once()

    await controller.admin_decision(callback)
    assert app.send_message.await_count == 2
    assert callback.answer.await_args_list[-1].args == ("Уже обработано",)


@pytest.mark.parametrize("platform", [Platform.MAX, Platform.TELEGRAM])
async def test_registration_falls_back_to_real_ad_domain_and_hides_it(
    tmp_path, monkeypatch, platform
):
    controller, app, database = make_controller(tmp_path)
    lookup = Mock(side_effect=[False, True])
    monkeypatch.setattr("unlock_bot.messaging.handlers.is_ad_user_exists", lookup)
    message = FakeMessage(platform=platform, text="user@alkaloid.ru")
    await controller.register_email(message, FakeState())
    assert [call.args[0] for call in lookup.call_args_list] == [
        "user@alkaloid.ru",
        "user@alkaloid.com.mk",
    ]
    admin_call = app.send_message.await_args
    request_id = (
        admin_call.kwargs["reply_markup"].rows[0][0].callback_data.split(":")[1]
    )
    database.decide_registration(request_id, approved=True, decided_by_external_id=99)
    assert database.get_identity(platform.value, 20).upn == "user@alkaloid.com.mk"
    unlock = Mock()
    monkeypatch.setattr(controller, "_unlock_ad_user", unlock)
    message.text = "/unlock"
    await controller.command_unlock(message)
    unlock.assert_called_once_with("user@alkaloid.com.mk")
    reply = message.answer.await_args.args[0]
    assert "user@alkaloid.ru" in reply
    assert "alkaloid.com.mk" not in reply
    await controller.ad.close()


@pytest.mark.parametrize("platform", [Platform.MAX, Platform.TELEGRAM])
@pytest.mark.parametrize("fallback_succeeds", [True, False])
async def test_failed_internal_binding_switches_only_after_successful_unlock(
    tmp_path, monkeypatch, platform, fallback_succeeds
):
    controller, app, database = make_controller(tmp_path)
    request = database.create_registration_request(
        platform=platform.value,
        external_user_id=20,
        chat_id=20,
        display_name="Existing user",
        username=None,
        requested_upn="user@alkaloid.com.mk",
    )
    database.decide_registration(request.id, approved=True, decided_by_external_id=99)
    unlock = Mock(
        side_effect=[
            LookupError("old account missing"),
            None if fallback_succeeds else LookupError("fallback missing"),
        ]
    )
    monkeypatch.setattr(controller, "_unlock_ad_user", unlock)
    message = FakeMessage(platform=platform, text="/unlock")
    await controller.command_unlock(message)
    assert [call.args[0] for call in unlock.call_args_list] == [
        "user@alkaloid.com.mk",
        "user@alkaloid.ru",
    ]
    assert database.get_identity(platform.value, 20).upn == (
        "user@alkaloid.ru" if fallback_succeeds else "user@alkaloid.com.mk"
    )
    if fallback_succeeds:
        assert "закреплённая за вами" in message.answer.await_args.args[0]
        assert "Привязка обновлена" in app.send_message.await_args.kwargs["text"]
    await controller.ad.close()


@pytest.mark.parametrize(
    ("exists", "expected"),
    [([True], "user@alkaloid.ru"), ([False, False], None)],
)
def test_registration_prefers_public_domain_and_rejects_missing_account(
    monkeypatch, exists, expected
):
    lookup = Mock(side_effect=exists)
    monkeypatch.setattr("unlock_bot.messaging.handlers.is_ad_user_exists", lookup)
    assert BotController._resolve_registration_upn("user@alkaloid.ru") == expected
    assert lookup.call_args_list[0].args == ("user@alkaloid.ru",)


@pytest.mark.parametrize("platform", [Platform.MAX, Platform.TELEGRAM])
async def test_any_text_unlocks_only_bound_account(tmp_path, monkeypatch, platform):
    controller, app, database = make_controller(tmp_path)
    request = database.create_registration_request(
        platform=platform.value,
        external_user_id=20,
        chat_id=20,
        display_name="Tester",
        username=None,
        requested_upn="user@example.com",
    )
    database.decide_registration(request.id, approved=True, decided_by_external_id=99)
    unlock = Mock(
        side_effect=[LookupError("not found"), LookupError("not found"), None]
    )
    monkeypatch.setattr(controller, "_unlock_ad_user", unlock)
    message = FakeMessage(platform=platform, text="other.user@example.com")
    await controller.unknown_message(message, FakeState())
    assert [call.args[0] for call in unlock.call_args_list] == [
        "other.user@alkaloid.com.mk",
        "other.user@alkaloid.ru",
        "user@example.com",
    ]
    assert "закреплённая за вами" in message.answer.await_args.args[0]
    assert "other.user@example.com" in app.send_message.await_args.kwargs["text"]
    assert app.send_message.await_args.kwargs["platform"] is Platform.TELEGRAM
    await controller.ad.close()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("ksitnik", ["ksitnik@alkaloid.com.mk", "ksitnik@alkaloid.ru"]),
        (
            "ksitnik@alkaloid.ru",
            ["ksitnik@alkaloid.ru", "ksitnik@alkaloid.com.mk"],
        ),
        (
            "ksitnik@other.example",
            ["ksitnik@alkaloid.com.mk", "ksitnik@alkaloid.ru"],
        ),
        ("/unlock", []),
        ("random words!", []),
    ],
)
def test_upn_candidates_try_both_alkaloid_domains(text, expected):
    assert BotController._upn_candidates(text) == expected


@pytest.mark.parametrize("platform", [Platform.MAX, Platform.TELEGRAM])
async def test_text_account_success_skips_bound_account(
    tmp_path, monkeypatch, platform
):
    controller, app, database = make_controller(tmp_path)
    request = database.create_registration_request(
        platform=platform.value,
        external_user_id=20,
        chat_id=20,
        display_name="Tester",
        username=None,
        requested_upn="bound@alkaloid.ru",
    )
    database.decide_registration(request.id, approved=True, decided_by_external_id=99)
    unlock = Mock(return_value=None)
    monkeypatch.setattr(controller, "_unlock_ad_user", unlock)
    message = FakeMessage(platform=platform, text="ksitnik@alkaloid.ru")
    await controller.unknown_message(message, FakeState())
    unlock.assert_called_once_with("ksitnik@alkaloid.ru")
    assert "ksitnik@alkaloid.ru" in message.answer.await_args.args[0]
    assert "другая учётка" in app.send_message.await_args.kwargs["text"]
    await controller.ad.close()


@pytest.mark.parametrize("platform", [Platform.MAX, Platform.TELEGRAM])
async def test_first_successful_unlock_pins_account_for_existing_unbound_user(
    tmp_path, monkeypatch, platform
):
    controller, app, database = make_controller(tmp_path)
    request = database.create_registration_request(
        platform=platform.value,
        external_user_id=20,
        chat_id=20,
        display_name="Existing user",
        username=None,
        requested_upn="existing@example.com",
    )
    database.decide_registration(request.id, approved=True, decided_by_external_id=99)
    with database.engine.begin() as connection:
        connection.exec_driver_sql("UPDATE profiles SET upn=NULL, san=NULL")
    unlock = Mock(side_effect=[LookupError("not found"), None])
    monkeypatch.setattr(controller, "_unlock_ad_user", unlock)
    message = FakeMessage(platform=platform, text="newuser")

    await controller.unknown_message(message, FakeState())

    assert database.get_identity(platform.value, 20).upn == "newuser@alkaloid.ru"
    assert unlock.call_args_list[0].args == ("newuser@alkaloid.com.mk",)
    assert unlock.call_args_list[1].args == ("newuser@alkaloid.ru",)
    assert "закреплена за вами" in message.answer.await_args.args[0]
    assert app.send_message.await_args.kwargs["platform"] is Platform.TELEGRAM
    await controller.ad.close()


@pytest.mark.parametrize("platform", [Platform.MAX, Platform.TELEGRAM])
async def test_unlock_command_does_not_try_command_as_username(
    tmp_path, monkeypatch, platform
):
    controller, _, database = make_controller(tmp_path)
    request = database.create_registration_request(
        platform=platform.value,
        external_user_id=20,
        chat_id=20,
        display_name="Tester",
        username=None,
        requested_upn="bound@alkaloid.ru",
    )
    database.decide_registration(request.id, approved=True, decided_by_external_id=99)
    unlock = Mock(return_value=None)
    monkeypatch.setattr(controller, "_unlock_ad_user", unlock)
    message = FakeMessage(platform=platform, text="/unlock")
    await controller.command_unlock(message)
    unlock.assert_called_once_with("bound@alkaloid.ru")
    assert "закреплённая" in message.answer.await_args.args[0]
    await controller.ad.close()


async def test_attachment_does_not_unlock(tmp_path, monkeypatch):
    controller, _, database = make_controller(tmp_path)
    await register_max_user(controller, database)
    unlock = Mock()
    monkeypatch.setattr(controller, "_unlock_ad_user", unlock)
    await controller.unknown_message(FakeMessage(text=None), FakeState())
    unlock.assert_not_called()


async def test_slow_unlock_does_not_block_event_loop(tmp_path, monkeypatch):
    controller, app, database = make_controller(tmp_path)
    await register_max_user(controller, database)
    monkeypatch.setattr(
        controller,
        "_unlock_ad_user",
        lambda upn: time.sleep(0.08),
    )
    message = FakeMessage(text="/unlock")

    task = asyncio.create_task(controller.command_unlock(message))
    await asyncio.sleep(0.01)

    assert not task.done()
    await task
    message.answer.assert_awaited_once()
    assert app.send_message.await_count == 1


async def test_notification_failure_is_retried_after_restart(tmp_path):
    controller, app, database = make_controller(tmp_path)
    request = database.create_registration_request(
        platform="max",
        external_user_id=20,
        chat_id=30,
        display_name="Test",
        username=None,
        requested_upn="user@example.com",
    )
    database.decide_registration(request.id, approved=True, decided_by_external_id=99)
    app.send_message.side_effect = RuntimeError("offline")
    await controller.deliver_notifications()
    assert len(database.pending_notifications()) == 1

    restarted = Database(database.path)
    restarted.initialize()
    controller.database = restarted
    app.send_message.side_effect = None
    await controller.deliver_notifications()
    assert restarted.pending_notifications() == []
    assert app.send_message.await_args.kwargs["chat_id"] == 30


async def test_ad_worker_uses_one_non_event_loop_thread():
    worker = ADWorker()
    try:
        threads = await asyncio.gather(
            *[worker.run(threading.get_ident) for _ in range(10)]
        )
        assert len(set(threads)) == 1
        assert threads[0] != threading.get_ident()
    finally:
        await worker.close()


def test_blank_input_is_rejected(tmp_path):
    controller, _, _ = make_controller(tmp_path)
    for value in (None, "", "  ", "user@example.com other"):
        assert controller._clean_input(value) == ""
