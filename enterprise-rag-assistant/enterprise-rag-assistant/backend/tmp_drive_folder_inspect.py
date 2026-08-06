from app.database import SessionLocal
from app.auth.google_oauth import get_valid_credentials
from app.drive.drive_service import DriveService
from app.models import UserToken


db = SessionLocal()
token = db.query(UserToken).first()
print('token', bool(token))
if token:
    print('drive_folder_id', token.drive_folder_id)
    creds = get_valid_credentials(db)
    print('creds valid', bool(creds))
    drive = DriveService(creds)

    print('\n=== AI Knowledge Base folders ===')
    query = "name = 'AI Knowledge Base' and mimeType='application/vnd.google-apps.folder' and trashed = false"
    resp = drive.service.files().list(q=query, fields='files(id,name,parents)').execute()
    folders = resp.get('files', [])
    for f in folders:
        print('folder', f)
        try:
            list_resp = drive.service.files().list(q=f"'{f['id']}' in parents and trashed=false", fields='files(id,name,mimeType)').execute()
            print('  file_count', len(list_resp.get('files', [])))
            for g in list_resp.get('files', []):
                print('   file', g)
        except Exception as e:
            print('  list error', repr(e))

    print('\n=== Specific file parent info ===')
    file_id = '1n4YoNOURgrnzGAsKIzul8sPKVFlD6MJn'
    try:
        file_meta = drive.service.files().get(fileId=file_id, fields='id,name,parents', supportsAllDrives=True).execute()
        print('file_meta', file_meta)
    except Exception as e:
        print('file_meta err', repr(e))

    print('\n=== Current folder contents ===')
    if token.drive_folder_id:
        try:
            resp = drive.service.files().list(q=f"'{token.drive_folder_id}' in parents and trashed=false", fields='files(id,name,mimeType)').execute()
            print('files', resp.get('files', []))
        except Exception as e:
            print('current folder list err', repr(e))

db.close()
