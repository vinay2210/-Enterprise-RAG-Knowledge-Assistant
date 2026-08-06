from app.database import SessionLocal
from app.auth.google_oauth import get_valid_credentials
from app.drive.drive_service import DriveService
from app.models import UserToken


db = SessionLocal()
token_row = db.query(UserToken).first()
print('token_row_exists', token_row is not None)
if token_row:
    print('saved_drive_folder_id', token_row.drive_folder_id)
    creds = get_valid_credentials(db)
    print('creds_valid', bool(creds))
    if creds:
        drive = DriveService(creds)
        if token_row.drive_folder_id:
            print('using_folder_id', token_row.drive_folder_id)
            try:
                files = drive.list_files_in_folder(token_row.drive_folder_id)
                print('files_in_saved_folder_count', len(files))
                for f in files:
                    print('saved_folder_file', f)
            except Exception as e:
                print('saved_folder_error', repr(e))
        query = "name = 'AI Knowledge Base' and mimeType='application/vnd.google-apps.folder' and trashed = false"
        try:
            folder_results = drive.service.files().list(q=query, fields='files(id,name,parents)').execute()
            print('folders_named_ai_knowledge_base', len(folder_results.get('files', [])))
            for f in folder_results.get('files', []):
                print('named_folder', f)
        except Exception as e:
            print('folder_query_error', repr(e))
        query2 = "mimeType='application/pdf' and trashed = false"
        try:
            pdf_results = drive.service.files().list(q=query2, fields='files(id,name,parents)').execute()
            print('pdf_count', len(pdf_results.get('files', [])))
            for f in pdf_results.get('files', []):
                print('pdf_file', f)
        except Exception as e:
            print('pdf_query_error', repr(e))

        query3 = "name contains 'vinay' and trashed = false"
        try:
            named_results = drive.service.files().list(q=query3, fields='files(id,name,parents)').execute()
            print('name_contains_vinay_count', len(named_results.get('files', [])))
            for f in named_results.get('files', []):
                print('named_file', f)
        except Exception as e:
            print('name_query_error', repr(e))

        if token_row.drive_folder_id:
            print('folder_url', f"https://drive.google.com/drive/folders/{token_row.drive_folder_id}")

db.close()
