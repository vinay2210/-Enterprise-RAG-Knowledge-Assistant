from app.database import SessionLocal
from app.auth.google_oauth import get_valid_credentials
from app.drive.drive_service import DriveService
from app.models import UserToken


db = SessionLocal()
creds = get_valid_credentials(db)
token = db.query(UserToken).first()
print('folder_id', token.drive_folder_id if token else None)
if creds and token and token.drive_folder_id:
    drive = DriveService(creds)
    file_id = '1n4YoNOURgrnzGAsKIzul8sPKVFlD6MJn'
    print('file_id', file_id)
    try:
        meta = drive.service.files().get(fileId=file_id, fields='id,name,mimeType,owners,shared,sharedWithMe,parents,driveId,capabilities,permissions', supportsAllDrives=True).execute()
        print('meta', meta)
    except Exception as e:
        print('meta_err', repr(e))
    try:
        print('download try')
        data = drive.service.files().get_media(fileId=file_id, supportsAllDrives=True).execute()
        print('download size', len(data))
    except Exception as e:
        print('download_err', repr(e))
        import traceback
        traceback.print_exc()

    # list file parents metadata
    try:
        parents = meta.get('parents', []) if isinstance(meta, dict) else []
        print('parents', parents)
        for p in parents:
            pmeta = drive.service.files().get(fileId=p, fields='id,name,driveId,owners,mimeType,shared', supportsAllDrives=True).execute()
            print('parent meta', pmeta)
    except Exception as e:
        print('parent_err', repr(e))
else:
    print('no creds or folder id')
db.close()
