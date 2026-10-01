from __future__ import annotations

import asyncio
import html
import logging
import re

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
            await message.answer(
                "Вы уже зарегистрированы. Напишите любой текст "
                "для разблокировки своей учётной записи."
            )
            return
        await state.set_state(RegistrationStates.await_email)
        await message.answer("Введите вашу рабочую почту")

    async def register_email(
        self, message: UnifiedMessage, state: UnifiedContext
    ) -> None:
        email = self._clean_input(message.text)
        allowed_domains = {*self.settings.domains, "alkaloid.ru", "alkaloid.com.mk"}
        if not email or get_domain_from_txt(email) not in allowed_domains:
            await message.answer("Вы указали почту неправильно, попробуйте ещё раз")
            return

        resolved_email = await self.ad.run(self._resolve_registration_upn, email)
        if resolved_email is None:
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
            requested_upn=resolved_email,
        )
        keyboard = InlineKeyboard(
            [
                [
                    InlineButton("Да", f"reg:{request.id}:yes"),
                    InlineButton("Нет", f"reg:{request.id}:no"),
                ]
            ]
        )
        await self._notify_admin_user(
            message,
            "Заявка на привязку",
            f"📧 Запрошено: <code>{html.escape(email)}</code>\n"
            f"📌 Найдено в AD: <code>{html.escape(resolved_email)}</code>\n"
            "Подтвердить регистрацию?",
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
                    "Для разблокировки своей учётной записи напишите любой текст."
                    if request.status == "approved"
                    else "❌Администратор отказал в регистрации. Если это ошибка, "
                    "напишите ещё раз, чтобы повторить регистрацию."
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
            await message.answer("Для регистрации напишите вашу рабочую почту")
            return
        if not identity.upn:
            await message.answer(
                "У вас пока нет закреплённой учётной записи. "
                "Отправьте логин обычным сообщением, чтобы найти и разблокировать её."
            )
            return

        raw_text = (message.text or "").strip()
        text = "" if raw_text.startswith("/") else raw_text
        try:
            unlocked_upn, used_fallback, _tried = await self.ad.run(
                self._unlock_text_or_bound, text, identity.upn
            )
        except Exception as error:
            logger.exception("Failed to unlock AD user %s", identity.upn)
            await message.answer(
                "❌ Не удалось разблокировать ни учётную запись из сообщения, "
                "ни закреплённую за вами. Попробуйте ещё раз позже."
            )
            await self._notify_admin_user(
                message,
                "Ошибка разблокировки",
                f"💬 Запрос: «{html.escape(text[:800])}»\n"
                f"📌 Закреплённая учётка: <code>{html.escape(identity.upn)}</code>\n"
                f"⚠️ {html.escape(str(error)[:800])}",
                identity=identity,
            )
            return

        is_bound_account = unlocked_upn.casefold() == identity.upn.casefold()
        if used_fallback and text:
            user_result = (
                f"Не получилось разблокировать «{html.escape(self._user_text(text))}»; "
                f"разблокирована закреплённая за вами учётная запись "
                f"{html.escape(self._user_text(unlocked_upn))}."
            )
            admin_result = (
                "не найден текстовый вариант; разблокирована закреплённая учётка"
            )
        elif not is_bound_account:
            user_result = (
                "Разблокирована другая учётная запись "
                f"{html.escape(self._user_text(unlocked_upn))}."
            )
            admin_result = f"разблокирована другая учётка {html.escape(unlocked_upn)}"
        else:
            user_result = (
                f"Разблокирована закреплённая за вами учётная запись "
                f"{html.escape(self._user_text(unlocked_upn))}."
            )
            admin_result = (
                f"разблокирована закреплённая учётка {html.escape(unlocked_upn)}"
                if not text
                else f"разблокирована учётка {html.escape(unlocked_upn)} по тексту"
            )
        await self._notify_admin_user(
            message,
            "Разблокировка",
            f"💬 Запрос: «{html.escape(text[:800])}»\n"
            f"🔎 Результат: {admin_result}.",
            identity=identity,
        )
        await message.answer(f"✅ {user_result}")

    def _unlock_text_or_bound(self, text: str, bound_upn: str):
        tried = []
        for candidate in self._upn_candidates(text):
            tried.append(candidate)
            if candidate.casefold() == bound_upn.casefold():
                continue
            try:
                self._unlock_ad_user(candidate)
                return candidate, False, tried
            except LookupError:
                continue
            except Exception:
                logger.exception("Could not unlock candidate AD account %s", candidate)
                continue

        tried.append(bound_upn)
        self._unlock_ad_user(bound_upn)
        return bound_upn, True, tried

    @staticmethod
    def _upn_candidates(text: str) -> list[str]:
        value = text.strip().strip("<>()[]{}'\".,;:")
        domains = ["alkaloid.com.mk", "alkaloid.ru"]
        if "@" in value:
            local, suffix = value.rsplit("@", 1)
            if suffix.casefold() in domains:
                domains.remove(suffix.casefold())
                domains.insert(0, suffix.casefold())
            username = local
        else:
            username = value
        if not username or not re.fullmatch(r"[\w.-]+", username, flags=re.UNICODE):
            return []
        username = username.casefold()
        return [f"{username}@{domain}" for domain in domains]

    async def command_connect(
        self, message: UnifiedMessage, state: UnifiedContext
    ) -> None:
        identity = await self._get_identity(message)
        if identity is None:
            await message.answer("Для регистрации напишите вашу рабочую почту")
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
        text = self._user_text(text)
        for offset in range(0, len(text), 600):
            await message.answer(html.escape(text[offset : offset + 600]))

    async def unknown_message(
        self, message: UnifiedMessage, state: UnifiedContext
    ) -> None:
        if (message.text or "").lstrip().startswith("/"):
            await message.answer("Неизвестная команда")
            return
        if not message.text or not message.text.strip():
            await message.answer("Пожалуйста, отправьте текстовое сообщение")
            return
        identity = await self._get_identity(message)
        if identity is None:
            await state.set_state(RegistrationStates.await_email)
            await self.register_email(message, state)
        elif not identity.upn:
            await state.clear()
            await self._unlock_and_pin_first_account(message, identity)
        else:
            await state.clear()
            await self.command_unlock(message)

    async def _unlock_and_pin_first_account(
        self, message: UnifiedMessage, identity: IdentityRecord
    ) -> None:
        text = (message.text or "").strip()
        candidates = self._upn_candidates(text)
        for candidate in candidates:
            try:
                await self.ad.run(self._unlock_ad_user, candidate)
            except LookupError:
                continue
            except Exception:
                logger.exception("Failed to unlock candidate AD account %s", candidate)
                continue

            try:
                pinned_identity, newly_pinned = await asyncio.to_thread(
                    self.database.bind_discovered_account,
                    message.platform.value,
                    message.user_id,
                    upn=candidate,
                )
            except Exception:
                logger.exception("Could not pin successfully unlocked AD account")
                await message.answer(
                    "✅ Разблокирована учётная запись "
                    f"{html.escape(self._user_text(candidate))}, "
                    "но не удалось закрепить её за вами. Сообщите администратору."
                )
                await self._notify_admin_user(
                    message,
                    "Учётка разблокирована, привязка не выполнена",
                    f"💬 Запрос: «{html.escape(text[:800])}»\n"
                    f"✅ Разблокирована: <code>{html.escape(candidate)}</code>\n"
                    "⚠️ Не удалось закрепить учётку за профилем",
                    identity=identity,
                )
                return

            if newly_pinned:
                result = f"Она закреплена за вами как {pinned_identity.upn}."
            else:
                result = f"За вами уже закреплена учётная запись {pinned_identity.upn}."
            await message.answer(
                "✅ Разблокирована учётная запись "
                f"{html.escape(self._user_text(candidate))}. "
                f"{html.escape(self._user_text(result))}"
            )
            await self._notify_admin_user(
                message,
                "Разблокировка и привязка",
                f"💬 Запрос: «{html.escape(text[:800])}»\n"
                f"✅ Разблокирована: <code>{html.escape(candidate)}</code>\n"
                f"📌 {html.escape(result)}",
                identity=identity,
            )
            return

        await message.answer(
            "Не удалось найти или разблокировать учётную запись по этому тексту. "
            "Попробуйте другой логин или используйте /connect для привязки."
        )
        await self._notify_admin_user(
            message,
            "Учётная запись не найдена",
            f"💬 Запрос: «{html.escape(text[:800])}»\n"
            "❌ Разблокировка не выполнена",
            identity=identity,
        )

    async def _connect(self, message: UnifiedMessage, value: str) -> bool:
        identity = await self._get_identity(message)
        if identity is None:
            await message.answer("Для регистрации напишите вашу рабочую почту")
            return False
        if identity.upn:
            await message.answer("Ваша учетная запись уже подключена")
            return True
        written_upn = self._clean_input(value)
        if not written_upn:
            await message.answer("Укажите корректный логин")
            return False
        if get_domain_from_txt(written_upn) in {"alkaloid.ru", "alkaloid.com.mk"}:
            resolved_upn = await self.ad.run(
                self._resolve_registration_upn, written_upn
            )
        else:
            resolved_upn = await self.ad.run(search_correct_upn, written_upn)
            if not await self.ad.run(is_ad_user_exists, resolved_upn):
                resolved_upn = None
        if resolved_upn is None:
            identity = await self._get_identity(message)
            await self._notify_admin_user(
                message,
                "Привязка не выполнена",
                f"📧 Запрошено: <code>{html.escape(written_upn)}</code>\n"
                "❌ Учётная запись не найдена в Active Directory",
                identity=identity,
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
            await self._notify_admin_user(
                message,
                "Привязка не выполнена",
                f"📧 Запрошена: <code>{html.escape(resolved_upn)}</code>\n"
                "⚠️ Учётная запись уже закреплена за другим профилем",
                identity=identity,
            )
            return False
        await message.answer(
            "Ваша учетная запись подключена. Напишите любой текст для её разблокировки."
        )
        identity = await self._get_identity(message)
        await self._notify_admin_user(
            message,
            "Учётная запись привязана",
            f"📌 Учётная запись: <code>{html.escape(resolved_upn)}</code>",
            identity=identity,
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

    async def _notify_admin_user(
        self,
        message: UnifiedMessage,
        heading: str,
        details: str,
        *,
        identity: IdentityRecord | None = None,
        reply_markup: InlineKeyboard | None = None,
    ) -> None:
        """Send a compact, consistent admin event with enough user identifiers."""
        username = (
            f"@{html.escape(message.username)}" if message.username else "не указан"
        )
        lines = [
            f"🔔 <b>{html.escape(heading)}</b>",
            f"👤 {html.escape(message.display_name or 'Имя не указано')}",
            f"🔗 {username}",
            f"🌐 {html.escape(message.platform.value)} · ID: "
            f"<code>{message.user_id}</code>",
        ]
        if identity is not None and identity.upn:
            lines.append(
                f"📌 Закреплённая учётка: <code>{html.escape(identity.upn)}</code>"
            )
        lines.append(details)
        await self.app.send_message(
            platform=Platform.TELEGRAM,
            chat_id=self.settings.admin_chat,
            text="\n".join(lines),
            reply_markup=reply_markup,
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
    def _user_text(value: str) -> str:
        """Show the public email domain without changing the underlying AD UPN."""
        return re.sub(
            r"@alkaloid\.com\.mk\b", "@alkaloid.ru", value, flags=re.IGNORECASE
        )

    @staticmethod
    def _resolve_registration_upn(email: str) -> str | None:
        local, separator, domain = email.rpartition("@")
        candidates = (
            [f"{local}@alkaloid.ru", f"{local}@alkaloid.com.mk"]
            if separator and domain.casefold() in {"alkaloid.ru", "alkaloid.com.mk"}
            else [email]
        )
        for candidate in candidates:
            if is_ad_user_exists(candidate):
                return candidate
        return None

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
    router.message(with_state=True)(guarded(controller.unknown_message))
    return router
