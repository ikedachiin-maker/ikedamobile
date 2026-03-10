"""Google Drive へ本人確認書類をアップロードするユーティリティ"""
import os
import io

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from sheets_reader import get_credentials

# アップロード先フォルダID（.env の GOOGLE_DRIVE_FOLDER_ID）
# 未設定の場合はマイドライブのルートに保存
DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "")

MIME_MAP = {
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png":  "image/png",
    ".pdf":  "application/pdf",
}


def upload_file_to_drive(file_bytes: bytes, filename: str, ext: str) -> str:
    """
    ファイルを Google Drive にアップロードし、ファイル ID を返す。

    Parameters
    ----------
    file_bytes : bytes  アップロードするファイルの内容
    filename   : str    Drive 上のファイル名
    ext        : str    拡張子（例: ".jpg"）

    Returns
    -------
    str  Google Drive のファイル ID
    """
    creds   = get_credentials()
    service = build("drive", "v3", credentials=creds)

    mime_type = MIME_MAP.get(ext.lower(), "application/octet-stream")

    file_metadata: dict = {"name": filename}
    if DRIVE_FOLDER_ID:
        file_metadata["parents"] = [DRIVE_FOLDER_ID]

    media = MediaIoBaseUpload(
        io.BytesIO(file_bytes),
        mimetype=mime_type,
        resumable=False,
    )

    uploaded = service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id",
    ).execute()

    file_id = uploaded.get("id", "")
    print(f"[Drive] アップロード完了: {filename} → file_id={file_id}")
    return file_id
