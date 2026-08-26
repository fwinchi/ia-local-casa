"""
Parser de importes en formato europeo, usado por sumar_importes() en
mcp_documentos.py. Extraido a su propio modulo para poder testearlo sin
arrastrar el import de mcp_documentos.py -- que abre un
chromadb.PersistentClient en cuanto se importa.
"""

import re
from decimal import Decimal

# Importe en formato europeo: miles con punto OPCIONAL (grupos de 3 tras
# el primer grupo de 1-3 digitos) o sin separador de miles, siempre con
# coma decimal y exactamente 2 cifras -- 1.234,56 / 234,56 / 1234,56.
# Los lookaround (?<!\d) / (?!\d) evitan capturar un trozo de un numero
# mas largo (un simbolo como € pegado al numero no cuenta como digito, asi
# que no interfiere). Sin coma+2 cifras no hay match: asi se ignoran
# fechas, numeros de factura y referencias, que no tienen parte decimal.
_RE_IMPORTE = re.compile(r"(?<!\d)(?:\d{1,3}(?:\.\d{3})+|\d+),\d{2}(?!\d)")


def _parsear_importes_linea(linea: str) -> list[Decimal]:
    """Extrae los importes en formato europeo de una linea de texto, como
    Decimal (nunca float). Un parentesis o un guion inmediatamente delante
    del numero (ignorando espacios de por medio) marca el importe como
    negativo -- p.ej. "(1.234,56)" o "- 234,56"."""
    importes = []
    for m in _RE_IMPORTE.finditer(linea):
        valor = Decimal(m.group().replace(".", "").replace(",", "."))
        antes = linea[:m.start()].rstrip()
        if antes and antes[-1] in "(-":
            valor = -valor
        importes.append(valor)
    return importes


def _formatear_importe(valor: Decimal) -> str:
    """Decimal -> string en formato europeo (miles con punto, 2 decimales
    con coma). Inverso de lo que extrae _parsear_importes_linea."""
    valor = valor.quantize(Decimal("0.01"))
    entero, _, decimales = f"{abs(valor):.2f}".partition(".")
    grupos = []
    while len(entero) > 3:
        grupos.insert(0, entero[-3:])
        entero = entero[:-3]
    grupos.insert(0, entero)
    signo = "-" if valor < 0 else ""
    return f"{signo}{'.'.join(grupos)},{decimales}"
