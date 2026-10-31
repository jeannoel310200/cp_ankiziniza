import uuid
from pathlib import Path

from fastapi import UploadFile

UPLOAD_DIR = Path("uploads/verification")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


async def save_upload(file: UploadFile, subfolder: str = "") -> str:
    target_dir = UPLOAD_DIR / subfolder if subfolder else UPLOAD_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    ext = Path(file.filename).suffix
    filename = f"{uuid.uuid4()}{ext}"
    filepath = target_dir / filename

    content = await file.read()
    filepath.write_bytes(content)

    return str(filepath)
