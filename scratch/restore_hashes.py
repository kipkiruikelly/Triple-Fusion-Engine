import os
from dotenv import load_dotenv
load_dotenv()

from app import create_app
from extensions import db
from models import User

app = create_app()
with app.app_context():
    if os.path.exists("scratch/original_hashes.txt"):
        with open("scratch/original_hashes.txt", "r") as f:
            lines = f.readlines()
        for line in lines:
            if ":" in line:
                uid_str, h = line.strip().split(":", 1)
                uid = int(uid_str)
                u = User.query.get(uid)
                if u:
                    u.password_hash = h
                    print(f"Restored hash for user ID {uid}")
        db.session.commit()
        print("Commit completed!")
    else:
        print("Backup file not found")
