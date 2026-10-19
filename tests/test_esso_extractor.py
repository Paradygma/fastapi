"""
Test suite per EssoExtractor — formato WEX Europe Services SRL.
"""
import pytest
import re
from extractors.esso_extractor import EssoExtractor

WEX_LINE_WITH_KM = (
    "03.04.26 001621 DI 1452020MAGLIANO EM647VW 385756 gasolio autotrazion "
    "122,18 263,79 215,90 176,97 216,22 22,00 47,57 263,79"
)
WEX_LINE_WITHOUT_KM = (
    "13.04.26 007089 DI 1451479RIGNANO F FS549TP gasolio autotrazion "
    "41,39 91,02 219,91 180,26 74,61 22,00 16,41 91,02"
)
WEX_LINE_UNLEADED = (
    "09.04.26 000571 DI 1451899RIETI FK444ZJ 1 Unleaded "
    "68,88 148,64 215,80 176,89 121,84 22,00 26,81 148,65"
)


class TestEssoExtractor:
    """Test per l'estrattore WEX (ex Esso)"""

    @pytest.fixture
    def extractor(self):
        return EssoExtractor()

    def test_can_handle_wex_text(self, extractor):
        assert extractor.can_handle("WEX Europe Services SRL") is True

    def test_can_handle_essocard_legacy(self, extractor):
        assert extractor.can_handle("WEX Europe Services - ESSO CARD") is True

    def test_pattern_matches_with_km(self, extractor):
        match = extractor._pattern_transazione.search(WEX_LINE_WITH_KM)
        assert match is not None
        assert match.group(1) == "03.04.26"
        assert match.group(2) == "001621"
        assert match.group(3) == "MAGLIANO"
        assert match.group(4) == "EM647VW"
        assert match.group(5) == "385756"
        assert match.group(7) == "122,18"

    def test_pattern_matches_without_km(self, extractor):
        match = extractor._pattern_transazione.search(WEX_LINE_WITHOUT_KM)
        assert match is not None
        assert match.group(1) == "13.04.26"
        assert match.group(2) == "007089"
        assert match.group(3) == "RIGNANO F"
        assert match.group(4) == "FS549TP"
        assert match.group(5) is None
        assert match.group(7) == "41,39"

    def test_pattern_matches_unleaded(self, extractor):
        match = extractor._pattern_transazione.search(WEX_LINE_UNLEADED)
        assert match is not None
        assert match.group(4) == "FK444ZJ"
        assert "unleaded" in match.group(6).lower()

    def test_parse_transaction_with_km(self, extractor):
        match = extractor._pattern_transazione.search(WEX_LINE_WITH_KM)
        t = extractor._parse_transaction(match, WEX_LINE_WITH_KM)
        assert t["data"] == "03/04/26"
        assert t["numero_scontrino"] == "001621"
        assert t["localita"] == "MAGLIANO"
        assert t["targa"] == "EM647VW"
        assert t["chilometraggio"] == 385756
        assert t["quantita"] == 122.18
        assert t["prodotto"] == "GASOLIO AUTOTRAZION"
        assert t["fornitore"] == "WEX"

    def test_parse_transaction_without_km(self, extractor):
        match = extractor._pattern_transazione.search(WEX_LINE_WITHOUT_KM)
        t = extractor._parse_transaction(match, WEX_LINE_WITHOUT_KM)
        assert t["data"] == "13/04/26"
        assert t["targa"] == "FS549TP"
        assert t["chilometraggio"] == 0
        assert t["quantita"] == 41.39

    def test_importo_totale_is_last_amount(self, extractor):
        """Importo = ultimo valore riga = Totale incl. IVA"""
        match = extractor._pattern_transazione.search(WEX_LINE_WITH_KM)
        t = extractor._parse_transaction(match, WEX_LINE_WITH_KM)
        assert t["importo_totale"] == 263.79

    def test_fornitore_name(self, extractor):
        assert extractor.fornitore == "WEX"

    def test_codice_sede_empty(self, extractor):
        match = extractor._pattern_transazione.search(WEX_LINE_WITH_KM)
        t = extractor._parse_transaction(match, WEX_LINE_WITH_KM)
        assert t["codice_sede"] == ""


class TestEssoIntegration:
    """Test di integrazione con PDF reali WEX"""

    @pytest.fixture
    def extractor(self):
        return EssoExtractor()

    @pytest.fixture
    def pdf_path(self):
        return "/Users/mirkopapadopoli/Code/PARADYGMA/fastapi/Fatture nuove/fattura wex 15-4.pdf"

    def test_extract_real_pdf(self, extractor, pdf_path):
        import os
        if not os.path.exists(pdf_path):
            pytest.skip(f"PDF non trovato: {pdf_path}")

        with open(pdf_path, 'rb') as f:
            pdf_content = f.read()

        from io import BytesIO
        result = extractor.extract(BytesIO(pdf_content), "wex_test.pdf")

        assert result.status == "success"
        assert result.fornitore == "WEX"
        assert result.records_count > 0

    def test_extract_all_transactions(self, extractor, pdf_path):
        import os
        if not os.path.exists(pdf_path):
            pytest.skip(f"PDF non trovato: {pdf_path}")

        with open(pdf_path, 'rb') as f:
            pdf_content = f.read()

        from io import BytesIO
        result = extractor.extract(BytesIO(pdf_content), "wex_test.pdf")

        assert result.records_count == 39

    def test_all_amounts_positive(self, extractor, pdf_path):
        import os
        if not os.path.exists(pdf_path):
            pytest.skip(f"PDF non trovato: {pdf_path}")

        with open(pdf_path, 'rb') as f:
            pdf_content = f.read()

        from io import BytesIO
        result = extractor.extract(BytesIO(pdf_content), "wex_test.pdf")

        for trans in result.invoice_data.transactions:
            assert trans.importo_totale > 0, f"Importo zero: scontrino {trans.numero_scontrino}"

    def test_unleaded_transaction_extracted(self, extractor, pdf_path):
        """CRITICAL: transazione Unleaded (benzina) non deve essere persa"""
        import os
        if not os.path.exists(pdf_path):
            pytest.skip(f"PDF non trovato: {pdf_path}")

        with open(pdf_path, 'rb') as f:
            pdf_content = f.read()

        from io import BytesIO
        result = extractor.extract(BytesIO(pdf_content), "wex_test.pdf")

        unleaded = [t for t in result.invoice_data.transactions
                    if "UNLEADED" in t.prodotto.upper()]
        assert len(unleaded) == 1
        assert unleaded[0].targa == "FK444ZJ"
        assert unleaded[0].quantita == 68.88


@pytest.mark.esso
@pytest.mark.integration
class TestWexColonneAutoroute:
    """Colonne Numero_Fattura, Note (matricola carta) e Autista nel CSV"""

    PDF_WEX = "Fatture nuove/fattura wex 15-4.pdf"

    @pytest.fixture
    def records(self):
        from pathlib import Path
        from extractors.extractor_factory import ExtractorFactory

        pdf_path = Path(__file__).parent.parent / self.PDF_WEX
        if not pdf_path.exists():
            pytest.skip(f"PDF non trovato: {pdf_path}")
        result = ExtractorFactory.extract_from_pdf(pdf_path.read_bytes(), pdf_path.name)
        return result["data"]

    def test_numero_fattura_su_ogni_riga(self, records):
        assert all(r["Numero_Fattura"] == "00154751" for r in records)

    def test_note_e_autista_vuoti(self, records):
        """Note e Autista vengono compilati a mano: sempre vuoti, anche se il PDF riporta 'Carta: NNN'"""
        assert all(r["Note"] == "" for r in records)
        assert all(r["Autista"] == "" for r in records)
