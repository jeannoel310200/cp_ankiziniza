from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# Import models for metadata registration side-effects.
from app.modules.account_deletion.model import AccountDeletionRequest  # noqa: F401,E402
from app.modules.auth.model import RefreshSession  # noqa: F401,E402
from app.modules.bonus.model import (
    BonusCode,
    BonusRule,
    DailyBonusClaim,
    DailyQuestion,
    DailyQuestionAnswer,
    ZoBalance,
)
from app.modules.notification.model import Notification
from app.modules.profile.model import Profile  # noqa: F401,E402
from app.modules.relationships.model import (
    RelationshipRequest,
    RelationshipStatus,
)  # noqa: F401,E402
from app.modules.users.model import User  # noqa: F401,E402
from app.modules.wallet.model import AnkTransaction, Wallet  # noqa: F401,E402
from app.modules.verification.model import VerificationRequest
