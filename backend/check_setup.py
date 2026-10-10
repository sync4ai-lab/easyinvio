"""Report invalid environment variable names without exposing their values."""
from pydantic import ValidationError
from main import Settings

if __name__ == "__main__":
    try:
        Settings()
    except ValidationError as exc:
        fields = sorted({str(error["loc"][0]).upper() if error["loc"] else "SANDBOX_CONFIGURATION" for error in exc.errors()})
        print("Configure these variables in .env: " + ", ".join(fields))
        raise SystemExit(1)
    print("Settings validate. Database connectivity and migrations are checked by configured startup.")
