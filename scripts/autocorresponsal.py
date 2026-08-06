import os
import unicodedata
import requests

PAPERLESS_URL = "http://localhost:8010"
TOKEN = os.environ.get("PAPERLESS_TOKEN")
CAMPO_PROVEEDOR = 7

if not TOKEN:
    raise SystemExit(
        "Falta la variable de entorno PAPERLESS_TOKEN. "
        "Define el token de Paperless (ver secrets.local.bat.example) "
        "antes de ejecutar este script."
    )

H = {"Authorization": f"Token {TOKEN}", "Content-Type": "application/json"}


def norm(s):
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = "".join(c for c in s if c.isalnum() or c.isspace())
    return " ".join(s.lower().split())


def get_all(endpoint):
    items, url = [], f"{PAPERLESS_URL}/api/{endpoint}/?page_size=200"
    while url:
        r = requests.get(url, headers=H).json()
        items += r["results"]
        url = r["next"]
    return items


def main():
    corres = {norm(c["name"]): c["id"] for c in get_all("correspondents")}
    for d in get_all("documents"):
        if d.get("correspondent"):
            continue
        val = next((f["value"] for f in d.get("custom_fields", [])
                    if f["field"] == CAMPO_PROVEEDOR), None)
        if not val:
            continue
        val = val.strip()
        key = norm(val)
        if key not in corres:
            r = requests.post(f"{PAPERLESS_URL}/api/correspondents/",
                              headers=H, json={"name": val, "matching_algorithm": 0})
            if r.status_code not in (200, 201):
                print(f"ERROR creando '{val}': {r.status_code} {r.text}")
                continue
            corres[key] = r.json()["id"]
            print(f"Creado interlocutor: {val}")
        r = requests.patch(f"{PAPERLESS_URL}/api/documents/{d['id']}/",
                           headers=H, json={"correspondent": corres[key]})
        print(f"Doc #{d['id']} -> {val} ({r.status_code})")


if __name__ == "__main__":
    main()