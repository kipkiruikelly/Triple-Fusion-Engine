import os
from dotenv import load_dotenv
load_dotenv()

from app import create_app
from extensions import db
from models import User

app = create_app()
with app.app_context():
    from werkzeug.security import check_password_hash
    u1 = User.query.get(1)
    u2 = User.query.get(2)
    print("User 1:", u1.username, "Email:", u1.email)
    print("User 2:", u2.username, "Email:", u2.email)
    
    # Try different passwords
    # Wait, we know u1's original password has been restored. What is u2's password?
    # Let's check if the hashes are correct and how check_password behaves
    p1_check = u1.check_password("Password123")
    p2_check = u2.check_password("Password123")
    print("U1 with Password123:", p1_check)
    print("U2 with Password123:", p2_check)
