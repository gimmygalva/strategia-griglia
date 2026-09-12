"""Immutable, validated endpoints. Public Demo prices are Mainnet prices."""

from dataclasses import dataclass

from gridbot.errors import ValidationError
from gridbot.models import Credentials, Environment


@dataclass(frozen=True, slots=True)
class Endpoints:
    rest: str
    private_ws: str
    public_ws: str
    public_rest: str
    namespace: str


_ENDPOINTS = {
    Environment.DEMO: Endpoints(
        rest="https://api-demo.bybit.com",
        private_ws="wss://stream-demo.bybit.com/v5/private",
        public_ws="wss://stream.bybit.com/v5/public/linear",
        public_rest="https://api.bybit.com",
        namespace="demo",
    ),
    Environment.MAINNET: Endpoints(
        rest="https://api.bybit.com",
        private_ws="wss://stream.bybit.com/v5/private",
        public_ws="wss://stream.bybit.com/v5/public/linear",
        public_rest="https://api.bybit.com",
        namespace="live",
    ),
}


def endpoints_for(environment: Environment) -> Endpoints:
    try:
        return _ENDPOINTS[Environment(environment)]
    except (KeyError, ValueError, TypeError) as exc:
        raise ValidationError("Ambiente Bybit non valido") from exc


class EnvironmentValidation:
    """Called at construction and before every signed operation."""

    @staticmethod
    def validate(
        environment: Environment,
        credentials: Credentials,
        endpoints: Endpoints,
    ) -> None:
        if credentials.environment != environment:
            raise ValidationError("Credenziali e ambiente Bybit non corrispondono")
        if endpoints != endpoints_for(environment):
            raise ValidationError("Endpoint Bybit incoerenti: trading bloccato")
