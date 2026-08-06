import shutil
from pathlib import Path
from datetime import datetime

CARPETA = Path.home() / "Downloads"

CATEGORIAS = {
    "Imagenes": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".svg", ".tiff"],
    "PDFs": [".pdf"],
    "Documentos": [".doc", ".docx", ".txt", ".odt", ".rtf", ".md", ".xls", ".xlsx", ".csv", ".ppt", ".pptx"],
    "Instaladores": [".exe", ".msi", ".appx"],
    "Comprimidos": [".zip", ".rar", ".7z", ".tar", ".gz", ".iso"],
    "Videos": [".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm"],
    "Audio": [".mp3", ".wav", ".flac", ".m4a", ".ogg"],
    "Otros": [],
}

# Extensiones que nunca se tocan (descargas en curso)
IGNORAR = {".crdownload", ".part", ".tmp", ".partial"}
IGNORAR_NOMBRES = {"desktop.ini", "thumbs.db"}

def destino_para(ext):
    for categoria, extensiones in CATEGORIAS.items():
        if ext in extensiones:
            return categoria
    return "Otros"


def nombre_libre(ruta):
    """Evita sobrescribir: archivo.pdf -> archivo (1).pdf"""
    if not ruta.exists():
        return ruta
    contador = 1
    while True:
        nuevo = ruta.with_name(f"{ruta.stem} ({contador}){ruta.suffix}")
        if not nuevo.exists():
            return nuevo
        contador += 1


def main():
    if not CARPETA.exists():
        print(f"No existe la carpeta {CARPETA}")
        return

    movidos = 0
    subcarpetas = set(CATEGORIAS.keys())

    for item in CARPETA.iterdir():
        if item.is_dir():
            continue
        if item.name.lower() in IGNORAR_NOMBRES:
            continue
        ext = item.suffix.lower()
        if ext in IGNORAR:
            continue

        categoria = destino_para(ext)
        carpeta_destino = CARPETA / categoria
        carpeta_destino.mkdir(exist_ok=True)

        destino = nombre_libre(carpeta_destino / item.name)
        try:
            shutil.move(str(item), str(destino))
            print(f"{datetime.now():%Y-%m-%d %H:%M} | {item.name} -> {categoria}")
            movidos += 1
        except Exception as e:
            print(f"ERROR con {item.name}: {e}")

    if movidos == 0:
        print(f"{datetime.now():%Y-%m-%d %H:%M} | Nada que organizar")


if __name__ == "__main__":
    main()