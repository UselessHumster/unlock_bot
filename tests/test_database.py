from unlock_bot.database import get_user_by_tg_id

def test_get_user():
    user = get_user_by_tg_id(282760082)
    assert user.upn == 'ksitnik@alkaloid.com.mk'