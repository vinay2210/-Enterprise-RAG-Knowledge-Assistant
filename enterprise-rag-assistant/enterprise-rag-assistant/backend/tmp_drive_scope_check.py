from app.database import SessionLocal
from app.auth.google_oauth import get_valid_credentials, SCOPES
from app.models import UserToken


db = SessionLocal()
token = db.query(UserToken).first()
print('token row exists', token is not None)
if token:
    print('stored_refresh_token', bool(token.refresh_token))
    creds = get_valid_credentials(db)
    print('creds valid', bool(creds))
    print('creds scopes', getattr(creds, 'scopes', None))
    print('creds token', creds.token[:10] + '...' if creds.token else None)
    print('creds refresh_token', creds.refresh_token[:10] + '...' if creds.refresh_token else None)
    print('expected scopes', SCOPES)
    try:
        from googleapiclient.discovery import build
        drive = build('drive', 'v3', credentials=creds)
        about = drive.about().get(fields='user, storageQuota, importFormats, exportFormats, maxUploadSize').execute()
        print('about success', about.get('user', {}).get('emailAddress'))
    except Exception as e:
        print('drive about error', repr(e))
else:
    print('no token row')
db.close()
