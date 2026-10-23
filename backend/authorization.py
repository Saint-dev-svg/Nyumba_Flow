from flask_jwt_extended import get_jwt_identity

from extensions import db
from models import User


def get_current_landlord_id():
    """Return the authenticated user's ID only when the account is a landlord."""
    try:
        user_id = int(get_jwt_identity())
    except (TypeError, ValueError):
        return None

    user = db.session.get(User, user_id)
    if user is None or user.role != "landlord":
        return None
    return user.id
