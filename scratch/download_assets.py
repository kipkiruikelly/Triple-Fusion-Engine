import urllib.request
import os

os.makedirs("Static Files", exist_ok=True)

assets = {
    "Static Files/lightweight-charts.js": "https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js",
    "Static Files/chart.js": "https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"
}

for local_path, url in assets.items():
    try:
        print(f"Downloading {url} to {local_path}...")
        urllib.request.urlretrieve(url, local_path)
        print("Success!")
    except Exception as e:
        print(f"Failed to download {url}: {e}")
