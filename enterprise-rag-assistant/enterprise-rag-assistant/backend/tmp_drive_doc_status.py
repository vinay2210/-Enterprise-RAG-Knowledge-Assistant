from app.database import SessionLocal
from app.auth.google_oauth import get_valid_credentials
from app.drive.drive_service import DriveService
from app.models import Document, UserToken


db = SessionLocal()
creds = get_valid_credentials(db)
print('creds', bool(creds))
token = db.query(UserToken).first()
print('saved_folder_id', token.drive_folder_id if token else None)
if creds and token and token.drive_folder_id:
    drive = DriveService(creds)
    files = drive.list_files_in_folder(token.drive_folder_id)
    ids = {f['id'] for f in files}
    print('drive_files_count', len(files))
    print('drive_file_ids', ids)
    docs = db.query(Document).all()
    for doc in docs:
        print('doc', doc.id, doc.drive_file_id, doc.status, doc.deleted_at, doc.file_name, doc.mime_type)
        if doc.drive_file_id in ids:
            print('  -> in_drive_folder')
        else:
            print('  -> not in_drive_folder')
db.close()
