from functools import lru_cache

from unlock_bot.config import settings

from pyad.pyadexceptions import invalidResults
from pyad import adsearch, aduser
import subprocess as sp
import logging


@lru_cache(maxsize=128)
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
        ad_user = aduser.ADUser.from_cn(cn)
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


