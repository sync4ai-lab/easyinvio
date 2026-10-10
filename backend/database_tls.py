"""Verified PostgreSQL TLS with explicit legacy-CA compatibility."""
import ssl


def database_tls_context(cafile: str | None = None, *, strict: bool = True):
    context = ssl.create_default_context(cafile=cafile)
    if not strict:
        # Supabase Intermediate 2021 CA lacks Key Usage. Keep CA signature,
        # validity and hostname checks; relax only X.509 strict conformance.
        context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return context
