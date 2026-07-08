import os
from dotenv import load_dotenv
load_dotenv()

from app import create_app
from extensions import db
from models import User

app = create_app()
with app.app_context():
    users = User.query.all()
    print("Found users:")
    for u in users:
        print(f"ID: {u.id}, Username: {u.username}, Email: {u.email}, Role: {'PRO' if u.is_pro else 'FREE'}")
