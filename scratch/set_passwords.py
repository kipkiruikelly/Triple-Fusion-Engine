import os
from dotenv import load_dotenv
load_dotenv()

from app import create_app
from extensions import db
from models import User

app = create_app()
with app.app_context():
    from werkzeug.security import generate_password_hash
    u1 = User.query.get(1)
    u2 = User.query.get(2)
    
    # Save original hashes to temporary file if not already done
    if not os.path.exists("scratch/original_hashes.txt"):
        with open("scratch/original_hashes.txt", "w") as f:
            f.write(f"1:{u1.password_hash}\n")
            f.write(f"2:{u2.password_hash}\n")
            print("Backup created")
    
    u1.password_hash = generate_password_hash("Password123")
    u2.password_hash = generate_password_hash("Password123")
    db.session.commit()
    print("Both passwords set to Password123")
