import logging
import subprocess as sp

from unlock_bot import get_domain_from_txt
from unlock_bot.config import get_settings

adsearch = None
aduser = None
invalidResults = ()


def _require_pyad() -> None:
    global adsearch, aduser, invalidResults
    if adsearch is None or aduser is None:
        # Import only on the AD worker: pyad creates COM objects at import time.
        from pyad import adsearch as search
        from pyad import aduser as user
        from pyad.pyadexceptions import invalidResults as invalid_results

        adsearch, aduser, invalidResults = search, user, invalid_results


def cache(max_size=128):
    def dec(func):
        memory = {}

        def wrapper(*args, **kwargs):
            if len(memory) > max_size:
                first_key = next(iter(memory))
                removed_item = memory.pop(first_key)
                logging.info(f"Popping from cache {removed_item}")

            if cached_data := memory.get(args[0]):
                return cached_data

            data = func(*args, **kwargs)
            memory[args[0]] = data

            logging.info(f"Caching {args[0]}")

            return data

        return wrapper

    return dec


@cache()
def get_cn_of_ad_user(upn):
    _require_pyad()
    logging.info(f"Searching cn by {upn=}")
    cn = adsearch.by_upn(upn)
    logging.info(f"Found {cn=}")
    return cn


def is_ad_user_exists(upn) -> bool:
    try:
        logging.info(f"Checking if user exist by {upn=}")
        get_cn_of_ad_user(upn)
        logging.info(f"User {upn=} exists")
        return True

    except invalidResults:
        logging.info(f"User {upn=} does not exists")
        return False


def search_correct_upn(upn):
    settings = get_settings()
    upn_domain = get_domain_from_txt(upn)
    if upn_domain in {
        *settings.domains,
        "alkaloid.com.mk",
        "alkaloid.ru",
    }:
        return upn
    for domain in settings.domains:
        try_upn = upn + f"@{domain}"
        if is_ad_user_exists(try_upn):
            upn = try_upn
            break
    return upn


def get_ad_user_by_upn(upn):
    _require_pyad()
    logging.info(f"Getting user by {upn=}")
    upn = search_correct_upn(upn)

    if is_ad_user_exists(upn):
        cn = get_cn_of_ad_user(upn)
        ad_user = aduser.ADUser.from_dn(cn)
        logging.info(f"Found {ad_user=}")
        return ad_user

    return None


def get_locked_users_list() -> list:
    settings = get_settings()
    command = (
        f"powershell search-ADAccount -SearchBase '{settings.search_zone}' -LockedOut"
    )
    locked_users_data = sp.check_output(command, shell=True, timeout=60).decode()
    locked_users_list = []
    for line in locked_users_data.split("\n"):
        if "UserPrincipalName" in line:
            locked_users_list.append(line.split(":")[1].strip())
    return locked_users_list
