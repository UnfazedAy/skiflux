from rest_framework import status
from rest_framework.response import Response


class APIResponse(Response):
    def __init__(
        self,
        data=None,
        message="Success",
        status="success",
        status_code=status.HTTP_200_OK,
        **kwargs,
    ):
        if isinstance(message, dict):
            if data is None or data == "error":
                data = message
            first_key = list(message.keys())[0]
            val = message[first_key]
            message = f"{first_key}: {val[0] if isinstance(val, list) else val}"
        elif isinstance(message, list):
            message = str(message[0])

        payload = {
            "status": status,
            "status_code": status_code,
            "message": str(message),
        }
        if status == "error":
            payload["error"] = data if data is not None else {}
        else:
            payload["data"] = data if data is not None else {}

        super().__init__(data=payload, status=status_code, **kwargs)
