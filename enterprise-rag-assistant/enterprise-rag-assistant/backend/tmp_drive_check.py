from app.database import SessionLocal
from app.auth.google_oauth import get_valid_credentials
from app.drive.drive_service import DriveService


db = SessionLocal()
creds = get_valid_credentials(db)
print('creds', bool(creds))
if creds:
    svc = DriveService(creds)
    folder_id = svc.find_or_create_folder('AI Knowledge Base')
    print('folder', folder_id)
    files = svc.list_files_in_folder(folder_id)
    print('count', len(files))
    print(files[:5])
db.close()
