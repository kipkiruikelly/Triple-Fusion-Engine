import os
from dotenv import load_dotenv
load_dotenv()

from app import create_app
from extensions import db
from models import User

app = create_app()
with app.app_context():
    if os.path.exists("scratch/original_hash.txt"):
        with open("scratch/original_hash.txt", "r") as f:
            orig_hash = f.read().strip()
        
        u = User.query.filter_by(username="kelvinkipkirui").first()
        if u:
            u.password_hash = orig_hash
            db.session.commit()
            print("Password hash restored successfully!")
        else:
            print("User not found")
    else:
        print("Backup file not found")
