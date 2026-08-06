"""
Thin wrapper around the Google Drive v3 API.
Everything the rest of the app needs from Drive lives here, so if we ever
swap SDKs, only this file changes.
"""
import io
from typing import Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from app.config import get_settings
from app.utils.logger import logger

settings = get_settings()

SUPPORTED_MIME_TYPES = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/plain": "txt",
    "text/markdown": "md",
    "text/x-markdown": "md",
}


class DriveService:
    def __init__(self, credentials: Credentials):
        self.service = build("drive", "v3", credentials=credentials)

    # ---------- Folder management ----------
    def find_or_create_folder(self, folder_name: str) -> str:
        query = (
            f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' "
            "and trashed = false"
        )
        results = self.service.files().list(q=query, fields="files(id, name)").execute()
        files = results.get("files", [])
        if files:
            logger.info(f"Found existing Drive folder '{folder_name}' ({files[0]['id']})")
            return files[0]["id"]

        metadata = {"name": folder_name, "mimeType": "application/vnd.google-apps.folder"}
        folder = self.service.files().create(body=metadata, fields="id").execute()
        logger.info(f"Created Drive folder '{folder_name}' ({folder['id']})")
        return folder["id"]

    def find_folders_by_name(self, folder_name: str) -> list[dict]:
        query = (
            f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' "
            "and trashed = false"
        )
        results = self.service.files().list(q=query, fields="files(id, name)").execute()
        return results.get("files", [])

    # ---------- Listing ----------
    def list_files_in_folder(self, folder_id: str) -> list[dict]:
        query = f"'{folder_id}' in parents and trashed = false"
        fields = "files(id, name, mimeType, size, modifiedTime)"
        files: list[dict] = []
        page_token = None
        while True:
            resp = self.service.files().list(
                q=query, fields=f"nextPageToken, {fields}", pageToken=page_token
            ).execute()
            files.extend(resp.get("files", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return files

    # ---------- Download ----------
    def download_file(self, file_id: str) -> bytes:
        request = self.service.files().get_media(fileId=file_id)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buffer.getvalue()

    @staticmethod
    def is_supported(mime_type: str) -> bool:
        return mime_type in SUPPORTED_MIME_TYPES

    @staticmethod
    def extension_for(mime_type: str) -> Optional[str]:
        return SUPPORTED_MIME_TYPES.get(mime_type)
