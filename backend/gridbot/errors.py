class BotError(Exception):
    code = "BOT_ERROR"


class NetworkError(BotError):
    code = "NETWORK_ERROR"


class AuthenticationError(BotError):
    code = "AUTHENTICATION_FAILED"


class BybitAPIError(BotError):
    code = "BYBIT_API_ERROR"

    def __init__(self, message: str, ret_code: int = 0):
        super().__init__(message)
        self.ret_code = ret_code


class ValidationError(BotError):
    code = "VALIDATION_ERROR"


class RiskError(BotError):
    code = "RISK_ERROR"


class OrderNotSentError(RiskError):
    """Local pre-send veto: the HTTP request has provably not been initiated."""

    code = "ORDER_NOT_SENT"


class DatabaseError(BotError):
    code = "DATABASE_ERROR"


class RecoveryError(BotError):
    code = "RECOVERY_ERROR"


class UncertainOrderError(BotError):
    code = "ORDER_UNCERTAIN"
