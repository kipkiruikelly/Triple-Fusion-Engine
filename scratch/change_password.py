import os
from dotenv import load_dotenv
load_dotenv()

from app import create_app
from extensions import db
from models import User

app = create_app()
with app.app_context():
    u = User.query.filter_by(username="kelvinkipkirui").first()
    if u:
        print(f"Original hash: {u.password_hash}")
        # Save it to a temporary file
        with open("scratch/original_hash.txt", "w") as f:
            f.write(u.password_hash)
        from werkzeug.security import generate_password_hash
        u.password_hash = generate_password_hash("Password123")
        db.session.commit()
        print("Password updated to Password123")
    else:
        print("User not found")
