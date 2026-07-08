import requests

s1 = requests.Session()
r_post = s1.post("http://localhost:5000/login", data={
    "identifier": "kelvinkipkirui",
    "password": "Password123"
}, allow_redirects=False)

print("POST Status:", r_post.status_code)
print("POST Location:", r_post.headers.get("Location"))
print("POST Body Snippet:", r_post.text[:500])
