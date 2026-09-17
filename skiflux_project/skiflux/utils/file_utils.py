import os
import tempfile
import uuid


def save_temp_file(uploaded_file) -> str:
    temp_dir = tempfile.gettempdir()
    _, ext = os.path.splitext(uploaded_file.name)
    temp_file_path = os.path.join(temp_dir, f"{uuid.uuid4()}{ext}")

    with open(temp_file_path, "wb+") as destination:
        for chunk in uploaded_file.chunks():
            destination.write(chunk)

    return temp_file_path
