from __future__ import annotations

import asyncio
import html
import logging

from telegram_with_max import (
    App,
    InlineButton,
    InlineKeyboard,
    Platform,
    Router,
    UnifiedCallback,
    UnifiedContext,
    UnifiedMessage,
)

from unlock_bot import get_domain_from_txt
from unlock_bot.ad import (
    get_ad_user_by_upn,
    get_locked_users_list,
    is_ad_user_exists,
    search_correct_upn,
)
from unlock_bot.ad.worker import ADWorker
from unlock_bot.config import Settings
from unlock_bot.database import Database, IdentityConflictError, IdentityRecord
from unlock_bot.messaging.states import ConnectStates, RegistrationStates

logger = logging.getLogger(__name__)


class BotController:
    def __init__(self, *, app: App, database: Database, settings: Settings) -> None:
        self.app = app
        self.database = database
        self.settings = settings
        self.ad = ADWorker()
        self.notification_lock = asyncio.Lock()

    async def command_start(
        self, message: UnifiedMessage, state: UnifiedContext
    ) -> None:
        if await self._get_identity(message) is not None:
            await state.clear()
            await message.answer("Вы уже зарегистрированы")
            return
        await state.set_state(RegistrationStates.await_email)
        await message.answer("Введите вашу рабочую почту")

    async def register_email(
        self, message: UnifiedMessage, state: UnifiedContext
    ) -> None:
        email = self._clean_input(message.text)
        if not email or get_domain_from_txt(email) not in self.settings.domains:
            await message.answer("Вы указали почту неправильно, попробуйте ещё раз")
            return

        if not await self.ad.run(is_ad_user_exists, email):
            await message.answer(
                "Такого пользователя не существует, проверьте правильность "
                "написания почты, или укажите почту со старой фамилией"
            )
            return

        request = await asyncio.to_thread(
            self.database.create_registration_request,
            platform=message.platform.value,
            external_user_id=message.user_id,
            chat_id=message.chat_id,
            display_name=message.display_name,
            username=message.username,
            requested_upn=email,
        )
        keyboard = InlineKeyboard(
            [
                [
                    InlineButton("Да", f"reg:{request.id}:yes"),
                    InlineButton("Нет", f"reg:{request.id}:no"),
                ]
            ]
        )
        await self.app.send_message(
            platform=Platform.TELEGRAM,
            chat_id=self.settings.admin_chat,
            text=(
                f"Пользователь {html.escape(self._actor_label(message))} "
                f"из {message.platform.value} с ID {message.user_id} хочет "
                f"подключить учетную запись {html.escape(email)}. Принять?"
            ),
            reply_markup=keyboard,
        )
        await message.answer(
            "Я отправил данные администраторам. Дождитесь решения — я сообщу вам."
        )
        await state.clear()

    async def admin_decision(self, callback: UnifiedCallback) -> None:
        if (
            callback.platform is not Platform.TELEGRAM
            or callback.message.chat_id != self.settings.admin_chat
        ):
            await callback.answer("Недостаточно прав")
            return

        admin = await asyncio.to_thread(
            self.database.get_identity, "telegram", callback.user_id
        )
        if not (
            callback.user_id == self.settings.admin_chat
            or callback.user_id in self.settings.admin_user_ids
            or (admin is not None and admin.permissions == "admin")
        ):
            await callback.answer("Недостаточно прав")
            return

        try:
            prefix, request_id, action = (callback.data or "").split(":", 2)
        except ValueError:
            await callback.answer("Некорректная заявка")
            return
        if prefix != "reg" or action not in {"yes", "no"}:
            await callback.answer("Некорректная заявка")
            return

        try:
            decision = await asyncio.to_thread(
                self.database.decide_registration,
                request_id,
                approved=action == "yes",
                decided_by_external_id=callback.user_id,
            )
        except IdentityConflictError as error:
            logger.warning("Registration conflict: %s", error)
            await callback.answer("Учётная запись уже привязана")
            return

        if decision is None:
            await callback.answer("Заявка не найдена")
            return

        request = decision.request
        await self.deliver_notifications()
        if not decision.changed:
            await callback.answer("Уже обработано")
            return

        approved = request.status == "approved"
        status_text = (
            "✅Пользователь зарегистрирован"
            if approved
            else ("❌Пользователь НЕ зарегистрирован")
        )
        await callback.message.edit_text(
            f"{status_text} ({html.escape(request.requested_upn)})"
        )
        await callback.answer("Готово")

    async def deliver_notifications(self) -> None:
        async with self.notification_lock:
            pending = await asyncio.to_thread(self.database.pending_notifications)
            for request in pending:
                user_text = (
                    "✅Вы успешно зарегистрированы\n\n"
                    "Для разблокировки используйте /unlock"
                    if request.status == "approved"
                    else "❌Администратор отказал в регистрации. Если это ошибка, "
                    "используйте /start ещё раз."
                )
                try:
                    await self.app.send_message(
                        platform=Platform(request.platform),
                        chat_id=request.chat_id,
                        text=user_text,
                    )
                    await asyncio.to_thread(self.database.mark_notified, request.id)
                except Exception:
                    logger.exception("Notification %s will be retried", request.id)

    async def notification_loop(self) -> None:
        while True:
            try:
                await self.deliver_notifications()
            except Exception:
                logger.exception("Notification queue unavailable")
            await asyncio.sleep(30)

    async def command_unlock(self, message: UnifiedMessage) -> None:
        identity = await self._get_identity(message)
        if identity is None:
            await message.answer("Для регистрации используйте /start или /reg")
            return
        if not identity.upn:
            await message.answer(
                "Для подключения учетной записи используйте /connect <логин>"
            )
            return

        try:
            await self.ad.run(self._unlock_ad_user, identity.upn)
        except Exception as error:
            logger.exception("Failed to unlock AD user %s", identity.upn)
            await message.answer("❌ Произошла ошибка, попробуйте снова")
            await self._notify_admin(
                f"❌ Пользователь {html.escape(self._actor_label(message))} "
                f"не смог разблокировать {html.escape(identity.upn)}: "
                f"{html.escape(str(error))}"
            )
            return

        await message.answer(
            f"✅ Учетная запись {html.escape(identity.upn)} успешно разблокирована"
        )
        await self._notify_admin(
            f"Пользователь {html.escape(self._actor_label(message))} "
            f"из {message.platform.value} с ID {message.user_id} успешно "
            f"разблокировал {html.escape(identity.upn)} ✅"
        )

    async def command_connect(
        self, message: UnifiedMessage, state: UnifiedContext
    ) -> None:
        identity = await self._get_identity(message)
        if identity is None:
            await message.answer("Для регистрации используйте /start или /reg")
            return
        if identity.upn:
            await message.answer("Ваша учетная запись уже подключена")
            return

        parts = (message.text or "").split(maxsplit=1)
        if len(parts) == 2:
            await self._connect(message, parts[1])
            return

        await state.set_state(ConnectStates.await_upn)
        await message.answer("Напишите свой логин")

    async def connect_upn(self, message: UnifiedMessage, state: UnifiedContext) -> None:
        if await self._connect(message, message.text or ""):
            await state.clear()

    async def command_status(self, message: UnifiedMessage) -> None:
        identity = await self._get_identity(message)
        if identity is None or identity.permissions != "admin":
            await message.answer("Недостаточно прав")
            return
        locked_users = await self.ad.run(get_locked_users_list)
        if locked_users:
            text = "Список заблокированных пользователей:\n\n" + "\n".join(locked_users)
        else:
            text = "Сейчас нет заблокированных пользователей"
        # Leave room for HTML escaping and the smaller MAX message limit.
        for offset in range(0, len(text), 600):
            await message.answer(html.escape(text[offset : offset + 600]))

    async def unknown_message(self, message: UnifiedMessage) -> None:
        if await self._get_identity(message) is None:
            await message.answer("У Вас не хватает прав доступа")
            return
        await message.answer("Используйте команды /unlock, /connect или /status")

    async def _connect(self, message: UnifiedMessage, value: str) -> bool:
        identity = await self._get_identity(message)
        if identity is None:
            await message.answer("Для регистрации используйте /start или /reg")
            return False
        if identity.upn:
            await message.answer("Ваша учетная запись уже подключена")
            return True
        written_upn = self._clean_input(value)
        if not written_upn:
            await message.answer("Укажите корректный логин")
            return False
        resolved_upn = await self.ad.run(search_correct_upn, written_upn)
        if not await self.ad.run(is_ad_user_exists, resolved_upn):
            await self._notify_admin(
                f"❌Пользователь {html.escape(self._actor_label(message))} "
                f"попытался подключить {html.escape(written_upn)}, но такой "
                "учетной записи не существует"
            )
            await message.answer("Такой учетной записи не существует")
            return False
        try:
            await asyncio.to_thread(
                self.database.connect_identity,
                message.platform.value,
                message.user_id,
                upn=resolved_upn,
            )
        except IdentityConflictError:
            await message.answer("Эта учетная запись уже подключена к другому профилю")
            return False
        await message.answer("Ваша учетная запись подключена")
        await self._notify_admin(
            f"✅Пользователь {html.escape(self._actor_label(message))} "
            f"подключил учетную запись {html.escape(resolved_upn)}"
        )
        return True

    async def _get_identity(self, message: UnifiedMessage) -> IdentityRecord | None:
        identity = await asyncio.to_thread(
            self.database.get_identity,
            message.platform.value,
            message.user_id,
        )
        if identity is not None:
            await asyncio.to_thread(
                self.database.touch_identity,
                message.platform.value,
                message.user_id,
                chat_id=message.chat_id,
                display_name=message.display_name,
                username=message.username,
            )
        return identity

    async def _notify_admin(self, text: str) -> None:
        await self.app.send_message(
            platform=Platform.TELEGRAM,
            chat_id=self.settings.admin_chat,
            text=text,
        )

    def _clean_input(self, value: str | None) -> str:
        if value is None:
            return ""
        parts = value.strip().split()
        if len(parts) != 1:
            return ""
        cleaned = parts[0].lower()
        if any(symbol in cleaned for symbol in self.settings.restricted_symbols):
            return ""
        return cleaned

    @staticmethod
    def _actor_label(message: UnifiedMessage) -> str:
        if message.username:
            return f"@{message.username} ({message.display_name})"
        return message.display_name

    @staticmethod
    def _unlock_ad_user(upn: str) -> None:
        user = get_ad_user_by_upn(upn)
        if user is None:
            raise LookupError(f"AD user {upn} was not found")
        user.unlock()


def create_router(controller: BotController) -> Router:
    def guarded(handler):
        async def wrapped(event, *args):
            try:
                return await handler(event, *args)
            except Exception:
                logger.exception("Handler %s failed", handler.__name__)
                await event.answer("Произошла ошибка. Попробуйте ещё раз позже.")

        return wrapped

    router = Router(name="unlock-bot")
    router.started(with_state=True)(guarded(controller.command_start))
    router.message(commands=["reg"], with_state=True)(guarded(controller.command_start))
    router.message(commands=["unlock"])(guarded(controller.command_unlock))
    router.message(commands=["connect"], with_state=True)(
        guarded(controller.command_connect)
    )
    router.message(commands=["status"])(guarded(controller.command_status))
    router.message(states=[RegistrationStates.await_email], with_state=True)(
        guarded(controller.register_email)
    )
    router.message(states=[ConnectStates.await_upn], with_state=True)(
        guarded(controller.connect_upn)
    )
    router.callback(startswith="reg:", platforms=[Platform.TELEGRAM])(
        guarded(controller.admin_decision)
    )
    router.message()(guarded(controller.unknown_message))
    return router
