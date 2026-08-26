"""
Tests unitarios del parser de importes de utils_importes.py, usado por
sumar_importes() en mcp_documentos.py. Solo prueban las funciones puras
del parser -- sin red ni llamada a Paperless, y sin arrastrar el import de
mcp_documentos.py (que abre un chromadb.PersistentClient en cuanto se
importa: importar solo utils_importes.py evita ese efecto).

Uso:
    python -m unittest scripts.test_sumar_importes -v
    (o, desde dentro de scripts\\: python -m unittest test_sumar_importes -v)
"""

import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils_importes import _parsear_importes_linea, _formatear_importe


class TestParsearImportesLinea(unittest.TestCase):

    def test_importe_sin_miles(self):
        self.assertEqual(_parsear_importes_linea("Total: 234,56 EUR"), [Decimal("234.56")])

    def test_importe_con_miles_punto(self):
        self.assertEqual(_parsear_importes_linea("Importe: 1.234,56 EUR"), [Decimal("1234.56")])

    def test_importe_sin_punto_de_miles_pero_4_cifras(self):
        self.assertEqual(_parsear_importes_linea("Base imponible 1234,56"), [Decimal("1234.56")])

    def test_miles_multiples(self):
        self.assertEqual(_parsear_importes_linea("Total 12.345.678,90"), [Decimal("12345678.90")])

    def test_simbolo_euro_pegado_detras(self):
        self.assertEqual(_parsear_importes_linea("Total 1.234,56€"), [Decimal("1234.56")])

    def test_simbolo_euro_pegado_delante(self):
        self.assertEqual(_parsear_importes_linea("Total €1.234,56"), [Decimal("1234.56")])

    def test_cuatro_cifras_sin_separador_de_miles(self):
        self.assertEqual(_parsear_importes_linea("Importe 1234,56"), [Decimal("1234.56")])

    def test_negativo_con_guion(self):
        self.assertEqual(_parsear_importes_linea("Descuento -234,56"), [Decimal("-234.56")])

    def test_negativo_con_guion_y_espacio(self):
        self.assertEqual(_parsear_importes_linea("Descuento - 234,56"), [Decimal("-234.56")])

    def test_negativo_con_parentesis(self):
        self.assertEqual(_parsear_importes_linea("Ajuste (1.234,56)"), [Decimal("-1234.56")])

    def test_ignora_numeros_sin_decimales(self):
        # Numero de factura, fecha (ddmmaaaa) y referencia -- ninguno lleva
        # coma decimal, ninguno debe interpretarse como importe.
        self.assertEqual(
            _parsear_importes_linea("Factura 2024001 del 15012024 ref 987654"), []
        )

    def test_ignora_anio_suelto(self):
        self.assertEqual(_parsear_importes_linea("Ejercicio fiscal 2024"), [])

    def test_linea_sin_importe(self):
        self.assertEqual(_parsear_importes_linea("Gracias por su compra"), [])

    def test_linea_vacia(self):
        self.assertEqual(_parsear_importes_linea(""), [])

    def test_varios_importes_en_la_misma_linea(self):
        self.assertEqual(
            _parsear_importes_linea("Subtotal 100,00 IVA 21,00 Total 121,00"),
            [Decimal("100.00"), Decimal("21.00"), Decimal("121.00")],
        )

    def test_positivo_y_negativo_en_la_misma_linea(self):
        self.assertEqual(
            _parsear_importes_linea("Cargo 50,00 Abono -20,00"),
            [Decimal("50.00"), Decimal("-20.00")],
        )

    def test_usa_decimal_no_float(self):
        # 0,1 + 0,2 en float da 0.30000000000000004; con Decimal debe ser
        # exacto, sin arrastrar ese error de redondeo.
        importes = _parsear_importes_linea("0,10 0,20")
        self.assertEqual(sum(importes), Decimal("0.30"))
        self.assertIsInstance(importes[0], Decimal)


class TestFormatearImporte(unittest.TestCase):

    def test_formatea_sin_miles(self):
        self.assertEqual(_formatear_importe(Decimal("234.56")), "234,56")

    def test_formatea_con_miles(self):
        self.assertEqual(_formatear_importe(Decimal("1234.56")), "1.234,56")

    def test_formatea_negativo(self):
        self.assertEqual(_formatear_importe(Decimal("-1234.56")), "-1.234,56")

    def test_formatea_cero(self):
        self.assertEqual(_formatear_importe(Decimal("0")), "0,00")

    def test_redondea_a_2_decimales(self):
        self.assertEqual(_formatear_importe(Decimal("1234.5")), "1.234,50")


if __name__ == "__main__":
    unittest.main()
