from unlock_bot.ad.backend import cache
from unlock_bot.ad import get_ad_user_by_upn


def test_cache():
    @cache()
    def test_caching(username):
        data = f'{username} data'
        return data

    assert test_caching('username') == 'username data'
    assert test_caching('username2') == 'username2 data'

    assert get_ad_user_by_upn('nmoroz@alkaloid.com.mk') == 'CN=Natalia NM. Moroz,OU=Rusija Office Users,OU=Office,OU=Rusija,OU=Branch Offices,DC=AlkaloidAD,DC=local'