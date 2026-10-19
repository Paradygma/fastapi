"""
Test suite per TamoilExtractor
Verifica l'estrazione corretta di dati da fatture Tamoil
"""
import pytest
import pdfplumber
from extractors.tamoil_extractor import TamoilExtractor


class TestTamoilExtractor:
    """Test per l'estrattore Tamoil"""

    @pytest.fixture
    def extractor(self):
        """Fixture che restituisce un'istanza di TamoilExtractor"""
        return TamoilExtractor()

    def test_can_handle_tamoil_text(self, extractor):
        """Verifica che can_handle riconosca testo Tamoil"""
        tamoil_text = "TAMOIL ITALIA S.p.A. Via Andrea Costa"
        assert extractor.can_handle(tamoil_text) is True

    def test_can_handle_mycard_text(self, extractor):
        """Verifica che can_handle riconosca il marchio mycard"""
        mycard_text = "mycard Fattura N° DA25191152"
        assert extractor.can_handle(mycard_text) is True

    def test_cannot_handle_other_provider(self, extractor):
        """Verifica che can_handle rifiuti altri fornitori"""
        esso_text = "ESSO Italiana S.r.l."
        assert extractor.can_handle(esso_text) is False

    def test_trova_transazione_with_valid_line(self, extractor):
        """Verifica pattern regex per transazione valida"""
        line = "S 8478 SACROFANO (RM) 674676 01/10/2025 09:55 1 Gasolio Self LT 61,92 101,49"
        match = extractor._trova_transazione(line)

        assert match is not None
        assert match.group(1) == "8478"  # Codice PV
        assert match.group(2) == "SACROFANO (RM)"  # Località
        assert match.group(3) == "674676"  # Numero autorizzazione
        assert match.group(4) == "01/10/2025"  # Data
        assert match.group(5) == "09:55"  # Ora
        assert match.group(6) == "1"  # KM
        assert match.group(7) == "Gasolio Self"  # Prodotto
        assert match.group(8) == "61,92"  # Quantità
        assert match.group(9) == "101,49"  # Importo

    def test_trova_transazione_with_gasolio(self, extractor):
        """Verifica estrazione con prodotto Gasolio (non Self)"""
        line = "S 8478 SACROFANO (RM) 715213 13/10/2025 14:53 1 Gasolio LT 50,66 81,01"
        match = extractor._trova_transazione(line)

        assert match is not None
        assert match.group(7) == "Gasolio"

    def test_parse_transaction_structure(self, extractor):
        """Verifica che _parse_transaction restituisca struttura corretta"""
        line = "S 8478 SACROFANO (RM) 674676 01/10/2025 09:55 1 Gasolio Self LT 61,92 101,49"
        match = extractor._trova_transazione(line)
        trans_dict = extractor._parse_transaction(match, line)

        assert trans_dict["data"] == "01/10/2025"
        assert trans_dict["ora"] == "09:55"
        assert trans_dict["numero_scontrino"] == "674676"
        assert trans_dict["codice_sede"] == "8478"
        assert trans_dict["localita"] == "SACROFANO (RM)"
        assert trans_dict["targa"] == ""  # Verrà assegnata dopo
        assert trans_dict["chilometraggio"] == 0  # "1" indica non inserito
        assert trans_dict["prodotto"] == "GASOLIO SELF"  # Normalizzato in uppercase
        assert trans_dict["quantita"] == 61.92
        assert trans_dict["importo_totale"] == 101.49
        assert trans_dict["fornitore"] == "TAMOIL"

    def test_parse_transaction_km_handling(self, extractor):
        """Verifica che KM = 1 venga convertito a 0 (non inserito)"""
        line = "S 8478 SACROFANO (RM) 674676 01/10/2025 09:55 1 Gasolio Self LT 61,92 101,49"
        match = extractor._trova_transazione(line)
        trans_dict = extractor._parse_transaction(match, line)

        assert trans_dict["chilometraggio"] == 0

    def test_parse_transaction_km_real_value(self, extractor):
        """Verifica che KM reali vengano mantenuti"""
        line = "S 8478 SACROFANO (RM) 674676 01/10/2025 09:55 15000 Gasolio Self LT 61,92 101,49"
        match = extractor._trova_transazione(line)
        trans_dict = extractor._parse_transaction(match, line)

        assert trans_dict["chilometraggio"] == 15000

    def test_parse_transaction_price_calculation(self, extractor):
        """Verifica calcolo prezzo unitario"""
        line = "S 8478 SACROFANO (RM) 674676 01/10/2025 09:55 1 Gasolio Self LT 61,92 101,49"
        match = extractor._trova_transazione(line)
        trans_dict = extractor._parse_transaction(match, line)

        expected_price = 101.49 / 61.92
        assert abs(trans_dict["prezzo_unitario"] - expected_price) < 0.01

    def test_targa_extraction_pattern(self, extractor):
        """Verifica pattern regex per estrazione targa"""
        line = "Totale Carta 7083651392996570 Targa FK444ZJ 112,58 182,50"
        match = extractor._trova_transazione(line)

        # Non deve matchare come transazione
        assert match is None

        # Ma deve matchare il pattern targa
        import re
        targa_match = re.search(r"Targa\s+([A-Z]{2}\d{3}[A-Z]{2})", line)
        assert targa_match is not None
        assert targa_match.group(1) == "FK444ZJ"

    def test_normalizza_numero_italiano(self, extractor):
        """Verifica normalizzazione numeri formato italiano"""
        assert extractor.normalizza_numero("61,92") == 61.92
        assert extractor.normalizza_numero("101,49") == 101.49
        assert extractor.normalizza_numero("1.234,56") == 1234.56

    def test_fornitore_name(self, extractor):
        """Verifica che il nome fornitore sia corretto"""
        assert extractor.fornitore == "TAMOIL"


class TestTamoilIntegration:
    """Test di integrazione con PDF reali Tamoil"""

    @pytest.fixture
    def extractor(self):
        return TamoilExtractor()

    @pytest.fixture
    def pdf_path(self):
        return "/Users/mirkopapadopoli/Code/fastapi/Fatture nuove/tamoil 1-10...pdf"

    def test_extract_real_pdf(self, extractor, pdf_path):
        """Test estrazione da PDF Tamoil reale"""
        import os
        if not os.path.exists(pdf_path):
            pytest.skip(f"PDF non trovato: {pdf_path}")

        with open(pdf_path, 'rb') as f:
            pdf_content = f.read()

        from io import BytesIO
        result = extractor.extract(BytesIO(pdf_content), "tamoil_test.pdf")

        # Verifica risultato
        assert result.status == "success"
        assert result.fornitore == "TAMOIL"
        assert result.records_count > 0
        assert len(result.invoice_data.transactions) > 0

    def test_extract_targa_from_real_pdf(self, extractor, pdf_path):
        """Verifica estrazione targa FK444ZJ da PDF reale"""
        import os
        if not os.path.exists(pdf_path):
            pytest.skip(f"PDF non trovato: {pdf_path}")

        with open(pdf_path, 'rb') as f:
            pdf_content = f.read()

        from io import BytesIO
        result = extractor.extract(BytesIO(pdf_content), "tamoil_test.pdf")

        # Verifica che tutte le transazioni abbiano targa FK444ZJ
        for transaction in result.invoice_data.transactions:
            assert transaction.targa == "FK444ZJ", f"Targa mancante o errata: {transaction.targa}"

    def test_extract_two_transactions(self, extractor, pdf_path):
        """Verifica che vengano estratte 2 transazioni dal PDF reale"""
        import os
        if not os.path.exists(pdf_path):
            pytest.skip(f"PDF non trovato: {pdf_path}")

        with open(pdf_path, 'rb') as f:
            pdf_content = f.read()

        from io import BytesIO
        result = extractor.extract(BytesIO(pdf_content), "tamoil_test.pdf")

        # Il PDF contiene 2 transazioni
        assert len(result.invoice_data.transactions) == 2

    def test_total_amount_calculation(self, extractor, pdf_path):
        """Verifica calcolo totale importo"""
        import os
        if not os.path.exists(pdf_path):
            pytest.skip(f"PDF non trovato: {pdf_path}")

        with open(pdf_path, 'rb') as f:
            pdf_content = f.read()

        from io import BytesIO
        result = extractor.extract(BytesIO(pdf_content), "tamoil_test.pdf")

        # Totale dovrebbe essere 101.49 + 81.01 = 182.50
        expected_total = 182.50
        actual_total = sum(t.importo_totale for t in result.invoice_data.transactions)
        assert abs(actual_total - expected_total) < 0.01


@pytest.mark.tamoil
@pytest.mark.unit
class TestTamoilNumeroFattura:
    """Il numero fattura sta nella riga dei valori, sotto le etichette"""

    def test_numero_fattura_riga_sotto_etichette(self):
        import re
        text = (
            "Fattura N° Data fattura Cod. Cliente Agente Codice Fiscale / Partita IVA\n"
            "DA25191152 15/10/2025 0000270740 053 07119341001 30 giorni data fattura 1\n"
        )
        extractor = TamoilExtractor()
        extractor.get_pdf_text = lambda pdf: text
        header = extractor.extract_invoice_header(None)

        assert header["numero_fattura"] == "DA25191152"
