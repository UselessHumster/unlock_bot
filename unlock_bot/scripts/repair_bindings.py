"""Repair obsolete internal-domain bindings using read-only AD validation."""

import argparse
import asyncio
import sqlite3
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from unlock_bot.ad import is_ad_user_exists
from unlock_bot.ad.worker import ADWorker
from unlock_bot.config import get_settings
from unlock_bot.database import Database
from unlock_bot.database.database import Profile


async def repair_bindings(*, apply: bool = False) -> None:
    database = Database(get_settings().database_path)
    worker = ADWorker()
    try:
        with Session(database.engine) as session:
            profiles = session.execute(
                select(Profile.id, Profile.upn).where(
                    func.lower(Profile.upn).like("%@alkaloid.com.mk")
                )
            ).all()
        plan: list[tuple[int, str, str]] = []
        valid, missing = 0, 0
        # Several independent profiles may share a legacy account.
        lookups: dict[str, bool] = {}

        async def exists(upn: str) -> bool:
            key = upn.lower()
            if key not in lookups:
                lookups[key] = await worker.run(is_ad_user_exists, upn)
            return lookups[key]

        for index, (profile_id, old_upn) in enumerate(profiles, 1):
            new_upn = old_upn.rpartition("@")[0] + "@alkaloid.ru"
            if await exists(old_upn):
                valid += 1
            elif await exists(new_upn):
                plan.append((profile_id, old_upn, new_upn))
            else:
                missing += 1
            if index % 20 == 0 or index == len(profiles):
                print(f"Checked {index}/{len(profiles)} profiles", flush=True)
        print(
            f"Plan: repair={len(plan)}, valid_internal={valid}, "
            f"missing_in_both_domains={missing}",
            flush=True,
        )
        if not apply or not plan:
            return
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        backup = database.path.with_name(f"{database.path.name}.rebind.{stamp}.bak")
        with (
            sqlite3.connect(database.path) as source,
            sqlite3.connect(backup) as target,
        ):
            source.backup(target)
        print(f"Backup: {backup}", flush=True)
        changed = 0
        for profile_id, old_upn, new_upn in plan:
            changed += database.rebind_account(
                profile_id, expected_upn=old_upn, new_upn=new_upn
            )
        print(
            f"Updated {changed} profiles; "
            f"skipped {len(plan) - changed} changed profiles"
        )
    finally:
        await worker.close()
        database.engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Apply validated repairs")
    arguments = parser.parse_args()
    asyncio.run(repair_bindings(apply=arguments.apply))
