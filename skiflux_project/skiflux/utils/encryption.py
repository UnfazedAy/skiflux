import json
from django.conf import settings
from cryptography.fernet import Fernet


class PayloadEncryptor:
    @classmethod
    def get_cipher(cls):
        key = getattr(settings, "ENCRYPTION_KEY", None)
        if not key:
            raise ValueError("ENCRYPTION_KEY is not set in settings.")
        return Fernet(key.encode())

    @classmethod
    def encrypt_json(cls, data: dict) -> str:
        if not data:
            return None
        cipher = cls.get_cipher()
        json_str = json.dumps(data)
        return cipher.encrypt(json_str.encode()).decode()

    @classmethod
    def decrypt_json(cls, encrypted_str: str) -> dict:
        if not encrypted_str:
            return {}
        cipher = cls.get_cipher()
        decrypted_str = cipher.decrypt(encrypted_str.encode()).decode()
        return json.loads(decrypted_str)
