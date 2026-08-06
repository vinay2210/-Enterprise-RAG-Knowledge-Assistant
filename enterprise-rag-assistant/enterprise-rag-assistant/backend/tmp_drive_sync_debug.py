from app.database import SessionLocal
from app.drive.sync import run_sync
from app.models import Document


db = SessionLocal()
count = run_sync(db)
print('run_sync_returned', count)
print('documents:')
for doc in db.query(Document).order_by(Document.uploaded_at.desc()).all():
    print(doc.id, doc.drive_file_id, doc.file_name, doc.status, doc.error_message)
db.close()
