"""
Lock de instancia unica compartido por los scripts de indexado y revision
del disco externo/ChromaDB. Extraido de indexar_documentos.py, que tenia
este mismo bloque duplicado literalmente en indexar_fotos.py.
"""
import msvcrt


def adquirir_lock(ruta_lock):
    """Lock de instancia unica via msvcrt.locking sobre un fichero abierto,
    no por comprobacion de existencia: si el proceso anterior crasheo,
    Windows libera el lock del descriptor solo, sin dejar candados
    huerfanos que haya que borrar a mano.

    Devuelve el file object con el lock activo, o None si ya hay otra
    instancia corriendo.
    """
    f = open(ruta_lock, "a+b")
    try:
        if f.tell() == 0:
            f.write(b"0")
            f.flush()
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        f.close()
        return None
    return f


def liberar_lock(f):
    if f is None:
        return
    try:
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
    except OSError:
        pass
    f.close()
