"""Shared verified TLS policy with CA roots incorporated into frozen sidecars."""

import ssl
import sys
from functools import lru_cache
from pathlib import Path

import certifi

from .errors import ValidationError


@lru_cache(maxsize=1)
def verified_context() -> ssl.SSLContext:
    try:
        certificates = Path(certifi.where()).resolve()
        if getattr(sys, "frozen", False) and not certificates.is_relative_to(
            Path(sys._MEIPASS).resolve()
        ):
            raise ValidationError("Pacchetto certificati TLS non incorporato: trading bloccato")
        context = ssl.create_default_context(cafile=str(certificates))
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        if not context.cert_store_stats()["x509_ca"]:
            raise ValidationError("Pacchetto certificati TLS vuoto: trading bloccato")
        return context
    except (OSError, ssl.SSLError) as exc:
        raise ValidationError("Certificati TLS non disponibili: trading bloccato") from exc


def status() -> dict[str, str | int]:
    return {
        "ca_certificates": verified_context().cert_store_stats()["x509_ca"],
        "source": "bundled" if getattr(sys, "frozen", False) else "installed",
    }
