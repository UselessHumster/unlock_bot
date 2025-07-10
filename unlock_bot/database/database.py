from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker

from unlock_bot.config import settings

engine = create_engine(f'sqlite:///{settings.DATABASE_PATH}', echo=False)
Base = declarative_base()
Session = sessionmaker(bind=engine)


class User(Base):
    __tablename__ = 'users'

    telegram_id = Column(Integer, primary_key=True)
    permissions = Column(String(50))
    san = Column(String(100), unique=True)
    upn = Column(String(100), unique=True)


def get_user_by_tg_id(telegram_id):
    session = Session()
    user = session.query(User).filter(User.telegram_id == telegram_id).first()
    session.close()
    return user


def create_user(telegram_id, san, upn, permissions='guest'):
    session = Session()
    new_user = User(
        telegram_id=telegram_id,
        san=san,
        upn=upn,
        permissions=permissions)
    session.add(new_user)
    session.commit()  # сохраняем изменения
    return new_user


def change_san(user: User, new_san):
    session = Session()
    user.san = new_san
    session.commit()
    session.close()


def change_upn(user: User, new_upn):
    session = Session()
    user.upn = new_upn
    session.commit()
    session.close()
