from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from secrets import token_hex

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
    func,
    inspect,
    select,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


class Base(DeclarativeBase):
    pass


class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    permissions: Mapped[str] = mapped_column(String(50), default="guest")
    # Legacy shared AD accounts retain separate profiles and permissions.
    san: Mapped[str | None] = mapped_column(String(100))
    upn: Mapped[str | None] = mapped_column(String(100), index=True)


class ExternalIdentity(Base):
    __tablename__ = "external_identities"
    __table_args__ = (
        UniqueConstraint("platform", "external_user_id"),
        UniqueConstraint("profile_id", "platform"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id"))
    platform: Mapped[str] = mapped_column(String(20))
    external_user_id: Mapped[str] = mapped_column(String(100))
    chat_id: Mapped[int] = mapped_column(Integer)
    display_name: Mapped[str] = mapped_column(String(200))
    username: Mapped[str | None] = mapped_column(String(100))


class RegistrationRequest(Base):
    __tablename__ = "registration_requests"

    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    platform: Mapped[str] = mapped_column(String(20))
    external_user_id: Mapped[str] = mapped_column(String(100))
    chat_id: Mapped[int] = mapped_column(Integer)
    display_name: Mapped[str] = mapped_column(String(200))
    username: Mapped[str | None] = mapped_column(String(100))
    requested_upn: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by_external_id: Mapped[str | None] = mapped_column(String(100))


class PendingNotification(Base):
    __tablename__ = "pending_notifications"
    request_id: Mapped[str] = mapped_column(
        ForeignKey("registration_requests.id"), primary_key=True
    )


class Migration(Base):
    __tablename__ = "schema_migrations"
    name: Mapped[str] = mapped_column(String(100), primary_key=True)


@dataclass(frozen=True, slots=True)
class IdentityRecord:
    profile_id: int
    platform: str
    external_user_id: str
    chat_id: int
    display_name: str
    username: str | None
    permissions: str
    san: str | None
    upn: str | None


@dataclass(frozen=True, slots=True)
class RegistrationRecord:
    id: str
    platform: str
    external_user_id: str
    chat_id: int
    display_name: str
    username: str | None
    requested_upn: str
    status: str


@dataclass(frozen=True, slots=True)
class RegistrationDecision:
    request: RegistrationRecord
    changed: bool


class IdentityConflictError(RuntimeError):
    pass


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.engine = create_engine(f"sqlite:///{self.path}", echo=False)

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tables = set(inspect(self.engine).get_table_names())
        migrated = False
        if "schema_migrations" in tables:
            with Session(self.engine) as session:
                migrated = session.get(Migration, "legacy_users") is not None
        if not migrated and ("users" in tables or "users_legacy" in tables):
            self._migrate_legacy_users()
        Base.metadata.create_all(self.engine)

    def _migrate_legacy_users(self) -> None:
        # SQLite backup includes committed WAL contents, unlike a file copy.
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        backup_path = self.path.with_name(f"{self.path.name}.{stamp}.bak")
        with (
            sqlite3.connect(self.path) as source,
            sqlite3.connect(backup_path) as target,
        ):
            source.backup(target)
        with self.engine.begin() as connection:
            # Explicit BEGIN is required for transactional DDL in sqlite3's
            # legacy transaction mode, including on Python 3.10.
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            if "users" in inspect(connection).get_table_names():
                connection.execute(text("ALTER TABLE users RENAME TO users_legacy"))
            Base.metadata.create_all(connection)
            legacy_users = (
                connection.execute(
                    text(
                        "SELECT DISTINCT telegram_id, permissions, san, upn "
                        "FROM users_legacy"
                    )
                )
                .mappings()
                .all()
            )
            ids = [int(row["telegram_id"]) for row in legacy_users]
            if len(ids) != len(set(ids)):
                raise IdentityConflictError("Conflicting legacy Telegram records")
            for legacy in legacy_users:
                telegram_id = int(legacy["telegram_id"])
                existing = connection.execute(
                    select(ExternalIdentity.id).where(
                        ExternalIdentity.platform == "telegram",
                        ExternalIdentity.external_user_id == str(telegram_id),
                    )
                ).first()
                if existing:
                    continue
                result = connection.execute(
                    Profile.__table__.insert().values(
                        permissions=legacy["permissions"] or "guest",
                        san=legacy["san"],
                        upn=legacy["upn"],
                    )
                )
                profile_id = result.inserted_primary_key[0]
                telegram_id = int(legacy["telegram_id"])
                connection.execute(
                    ExternalIdentity.__table__.insert().values(
                        profile_id=profile_id,
                        platform="telegram",
                        external_user_id=str(telegram_id),
                        chat_id=telegram_id,
                        display_name=f"Telegram user {telegram_id}",
                        username=None,
                    )
                )
            connection.execute(Migration.__table__.insert().values(name="legacy_users"))

    def get_identity(
        self, platform: str, external_user_id: int | str
    ) -> IdentityRecord | None:
        with Session(self.engine) as session:
            row = session.execute(
                select(ExternalIdentity, Profile)
                .join(Profile, ExternalIdentity.profile_id == Profile.id)
                .where(
                    ExternalIdentity.platform == platform,
                    ExternalIdentity.external_user_id == str(external_user_id),
                )
            ).first()
            if row is None:
                return None
            identity, profile = row
            return self._identity_record(identity, profile)

    def touch_identity(
        self,
        platform: str,
        external_user_id: int | str,
        *,
        chat_id: int,
        display_name: str,
        username: str | None,
    ) -> None:
        with Session(self.engine) as session, session.begin():
            identity = session.scalar(
                select(ExternalIdentity).where(
                    ExternalIdentity.platform == platform,
                    ExternalIdentity.external_user_id == str(external_user_id),
                )
            )
            if identity is not None:
                identity.chat_id = chat_id
                identity.display_name = display_name
                identity.username = username

    def create_registration_request(
        self,
        *,
        platform: str,
        external_user_id: int | str,
        chat_id: int,
        display_name: str,
        username: str | None,
        requested_upn: str,
    ) -> RegistrationRecord:
        normalized_upn = requested_upn.strip().lower()
        with Session(self.engine) as session, session.begin():
            existing = session.scalar(
                select(RegistrationRequest).where(
                    RegistrationRequest.platform == platform,
                    RegistrationRequest.external_user_id == str(external_user_id),
                    RegistrationRequest.requested_upn == normalized_upn,
                    RegistrationRequest.status == "pending",
                )
            )
            if existing is not None:
                return self._registration_record(existing)

            request = RegistrationRequest(
                id=token_hex(6),
                platform=platform,
                external_user_id=str(external_user_id),
                chat_id=chat_id,
                display_name=display_name,
                username=username,
                requested_upn=normalized_upn,
                status="pending",
                created_at=datetime.now(timezone.utc),
            )
            session.add(request)
            session.flush()
            return self._registration_record(request)

    def decide_registration(
        self,
        request_id: str,
        *,
        approved: bool,
        decided_by_external_id: int | str,
    ) -> RegistrationDecision | None:
        with Session(self.engine) as session, session.begin():
            # Acquire SQLite's write lock before reading the status so two
            # simultaneous callback deliveries cannot both approve a request.
            session.execute(
                text(
                    "UPDATE registration_requests SET status = status "
                    "WHERE id = :request_id"
                ),
                {"request_id": request_id},
            )
            request = session.get(RegistrationRequest, request_id)
            if request is None:
                return None
            if request.status != "pending":
                return RegistrationDecision(
                    request=self._registration_record(request),
                    changed=False,
                )

            if approved:
                profiles = session.scalars(
                    select(Profile).where(
                        func.lower(Profile.upn) == request.requested_upn
                    )
                ).all()
                # Never select an arbitrary owner or inherit an administrator's
                # permissions when a legacy AD account has multiple owners.
                profile = profiles[0] if len(profiles) == 1 else None
                if profile is None:
                    profile = Profile(
                        permissions="guest",
                        san=request.requested_upn,
                        upn=request.requested_upn,
                    )
                    session.add(profile)
                    session.flush()

                external_identity = session.scalar(
                    select(ExternalIdentity).where(
                        ExternalIdentity.platform == request.platform,
                        ExternalIdentity.external_user_id == request.external_user_id,
                    )
                )
                profile_identity = session.scalar(
                    select(ExternalIdentity).where(
                        ExternalIdentity.profile_id == profile.id,
                        ExternalIdentity.platform == request.platform,
                    )
                )
                if external_identity is not None or profile_identity is not None:
                    raise IdentityConflictError(
                        "This account or profile is already linked on that platform"
                    )

                session.add(
                    ExternalIdentity(
                        profile_id=profile.id,
                        platform=request.platform,
                        external_user_id=request.external_user_id,
                        chat_id=request.chat_id,
                        display_name=request.display_name,
                        username=request.username,
                    )
                )
                request.status = "approved"
            else:
                request.status = "rejected"

            request.decided_at = datetime.now(timezone.utc)
            request.decided_by_external_id = str(decided_by_external_id)
            session.add(PendingNotification(request_id=request.id))
            session.flush()
            return RegistrationDecision(
                request=self._registration_record(request),
                changed=True,
            )

    def pending_notifications(self) -> list[RegistrationRecord]:
        with Session(self.engine) as session:
            requests = session.scalars(
                select(RegistrationRequest).join(
                    PendingNotification,
                    PendingNotification.request_id == RegistrationRequest.id,
                )
            )
            return [self._registration_record(request) for request in requests]

    def mark_notified(self, request_id: str) -> None:
        with Session(self.engine) as session, session.begin():
            pending = session.get(PendingNotification, request_id)
            if pending:
                session.delete(pending)

    def connect_identity(
        self,
        platform: str,
        external_user_id: int | str,
        *,
        upn: str,
    ) -> IdentityRecord:
        normalized_upn = upn.strip().lower()
        with Session(self.engine) as session, session.begin():
            row = session.execute(
                select(ExternalIdentity, Profile)
                .join(Profile, ExternalIdentity.profile_id == Profile.id)
                .where(
                    ExternalIdentity.platform == platform,
                    ExternalIdentity.external_user_id == str(external_user_id),
                )
            ).first()
            if row is None:
                raise LookupError("Identity is not registered")
            identity, profile = row
            if profile.upn:
                raise IdentityConflictError("Profile is already connected")
            occupied = session.scalar(
                select(Profile).where(
                    func.lower(Profile.upn) == normalized_upn,
                    Profile.id != profile.id,
                )
            )
            if occupied is not None:
                raise IdentityConflictError("AD account is linked to another profile")
            profile.upn = normalized_upn
            profile.san = normalized_upn
            session.flush()
            return self._identity_record(identity, profile)

    @staticmethod
    def _identity_record(
        identity: ExternalIdentity, profile: Profile
    ) -> IdentityRecord:
        return IdentityRecord(
            profile_id=profile.id,
            platform=identity.platform,
            external_user_id=identity.external_user_id,
            chat_id=identity.chat_id,
            display_name=identity.display_name,
            username=identity.username,
            permissions=profile.permissions,
            san=profile.san,
            upn=profile.upn,
        )

    @staticmethod
    def _registration_record(request: RegistrationRequest) -> RegistrationRecord:
        return RegistrationRecord(
            id=request.id,
            platform=request.platform,
            external_user_id=request.external_user_id,
            chat_id=request.chat_id,
            display_name=request.display_name,
            username=request.username,
            requested_upn=request.requested_upn,
            status=request.status,
        )
