import os
from dotenv import load_dotenv
load_dotenv()

from app import create_app
from extensions import db
from models import User
from flask_login import current_user

app = create_app()

print("Running test_login_flow...")
with app.test_client() as client:
    # 1. Log in with user 1 credentials
    resp1 = client.post("/login", data={
        "identifier": "kelvinkipkirui",
        "password": "Password123"
    }, follow_redirects=True)
    
    # Check currently logged in user
    with client.session_transaction() as sess:
        print("After login 1, session keys:", list(sess.keys()))
        print("Flask-login user id in session:", sess.get("_user_id"))

    # 2. Log out
    client.get("/logout", follow_redirects=True)
    with client.session_transaction() as sess:
        print("After logout, session keys:", list(sess.keys()))
        print("Flask-login user id in session:", sess.get("_user_id"))

    # 3. Log in with user 2 credentials
    resp2 = client.post("/login", data={
        "identifier": "kelvinkipkirui2",
        "password": "Password123"
    }, follow_redirects=True)
    with client.session_transaction() as sess:
        print("After login 2, session keys:", list(sess.keys()))
        print("Flask-login user id in session:", sess.get("_user_id"))
