from app.database import SessionLocal
from app.drive.sync import run_sync
from app.models import Document, UserToken


db = SessionLocal()
print('=== USER TOKEN ===')
token = db.query(UserToken).first()
print(token and {'email': token.email, 'drive_folder_id': token.drive_folder_id, 'refresh_token_present': bool(token.refresh_token)})
print('=== RUN SYNC ===')
count = run_sync(db)
print('sync returned', count)
print('=== DOCUMENTS ===')
for doc in db.query(Document).order_by(Document.uploaded_at.desc()).all():
    print(doc.id, doc.drive_file_id, doc.file_name, doc.status, doc.error_message, doc.deleted_at, doc.drive_modified_time)

print('=== ACTIVE DOCS ===')
for doc in db.query(Document).filter(Document.status != 'deleted').order_by(Document.uploaded_at.desc()).all():
    print('ACTIVE', doc.id, doc.drive_file_id, doc.file_name, doc.status, doc.error_message)

db.close()
