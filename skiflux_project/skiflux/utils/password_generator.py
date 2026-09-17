import secrets
import string


def generate_temporary_password(length: int = 12) -> str:
    if length < 8:
        raise ValueError("Password length must be at least 8 characters.")

    lowercase = string.ascii_lowercase
    uppercase = string.ascii_uppercase
    digits = string.digits
    special = "!@#$%"

    # Ensure required character types exist
    password_chars = [
        secrets.choice(lowercase),
        secrets.choice(uppercase),
        secrets.choice(digits),
        secrets.choice(special),
    ]

    # Fill remaining length
    all_chars = lowercase + uppercase + digits + special

    password_chars.extend(
        secrets.choice(all_chars) for _ in range(length - len(password_chars))
    )

    # Shuffle to avoid predictable order
    secrets.SystemRandom().shuffle(password_chars)

    return "".join(password_chars)
