from unlock_bot.config import settings

from pyad.pyadexceptions import invalidResults
from pyad import adsearch, aduser
import subprocess as sp
import logging


def cache(max_size=128):
    def dec(func):
        memory = {}

        def wrapper(*args, **kwargs):
            if len(memory) > max_size:
                first_key = next(iter(memory))
                removed_item = memory.pop(first_key)
                logging.info(f'Popping from cache {removed_item}')

            if cached_data := memory.get(args[0]):
                return cached_data

            data = func(*args, **kwargs)
            memory[args[0]] = data

            logging.info(f'Caching {args[0]}')

            return data

        return wrapper

    return dec



@cache()
def get_cn_of_ad_user(upn):
    logging.info(f'Searching cn by {upn=}')
    cn = adsearch.by_upn(upn)
    logging.info(f'Found {cn=}')
    return cn


def is_ad_user_exists(upn) -> bool:
    try:
        logging.info(f'Checking if user exist by {upn=}')
        get_cn_of_ad_user(upn)
        logging.info(f'User {upn=} exists')
        return True

    except invalidResults:
        logging.info(f'User {upn=} does not exists')
        return False


def get_ad_user_by_upn(upn):
    if f'@{settings.DOMAIN}' not in upn:
        upn += f'@{settings.DOMAIN}'

    logging.info(f'Getting user by {upn=}')

    if is_ad_user_exists(upn):
        cn = get_cn_of_ad_user(upn)
        ad_user = aduser.ADUser.from_dn(cn)
        logging.info(f'Found {ad_user=}')
        return ad_user

    return None


def get_locked_users_list() -> list:
        locked_users_data = sp.check_output(f"powershell search-ADAccount -SearchBase '{settings.SEARCH_ZONE}' -LockedOut",
                                            shell=True).decode()
        locked_users_list = []
        for i in locked_users_data.split('\n'):
            if 'UserPrincipalName' in i:
                locked_users_list.append(i.split(':')[1].strip().replace(f'@{settings.DOMAIN}', ''))
        return locked_users_list



