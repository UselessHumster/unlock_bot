from unlock_bot.config import settings
import pyad
from pyad.pyadexceptions import invalidResults
import subprocess as sp


def is_ad_user_exists(upn) -> bool:
    try:
        pyad.adsearch.by_upn(f'{upn}')
        return True

    except invalidResults:
        return False

def get_ad_user_by_upn(upn):
    if f'@{settings.domain}' not in upn:
        upn += f'@{settings.DOMAIN}'

    if is_ad_user_exists(upn):
        cn = pyad.adsearch.by_upn(f'{upn}')
        return pyad.aduser.ADUser.from_dn(cn)

    return None

def unlock_by_upn(upn):
    ad_user = get_ad_user_by_upn(upn)
    if ad_user:
        ad_user.unlock()


def get_locked_users_list() -> list:
        locked_users_data = sp.check_output(f"powershell search-ADAccount -SearchBase '{settings.SEARCH_ZONE}' -LockedOut",
                                            shell=True).decode()
        locked_users_list = []
        for i in locked_users_data.split('\n'):
            if 'UserPrincipalName' in i:
                locked_users_list.append(i.split(':')[1].strip().replace(f'@{settings.DOMAIN}', ''))
        return locked_users_list
