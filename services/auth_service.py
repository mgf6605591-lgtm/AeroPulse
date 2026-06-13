from sqlalchemy.orm import Session
from controllers.UserController import UserController


class AuthService:

    def __init__(self):
        pass

    def login_user(self, session: Session, username: str, pwd: str):
        user = UserController.get_user_by_login(session, username)
        if user is not None and user.password_hash == pwd:
            return True
        else:
            return False


auth_service = AuthService()
