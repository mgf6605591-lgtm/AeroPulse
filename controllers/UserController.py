from sqlalchemy.orm import Session
from db.models.entities import User


class UserController:

    @classmethod
    def get_user_by_login(cls, session: Session, login: str):
        return session.query(User).filter(User.username == login).first()
