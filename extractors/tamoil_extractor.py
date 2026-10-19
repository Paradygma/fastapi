"""
Estrattore per fatture Tamoil Italia S.p.A.
Gestisce il formato specifico delle fatture Tamoil mycard.
"""
import logging
import re
from typing import List, Dict, Any
from collections import defaultdict
from .base_extractor import BaseExtractor
from models.invoice_models import Transaction

logger = logging.getLogger(__name__)


class TamoilExtractor(BaseExtractor):
    """Estrattore specifico per fatture Tamoil"""

    def __init__(self):
        super().__init__()
        self.fornitore = "TAMOIL"

    def can_handle(self, pdf_text: str) -> bool:
        """Verifica se il PDF è una fattura Tamoil"""
        indicators = ["TAMOIL ITALIA S.p.A.", "TAMOIL", "mycard"]
        return any(indicator in pdf_text for indicator in indicators)

    def extract_invoice_header(self, pdf) -> Dict[str, Any]:
        """Estrae i dati dell'intestazione della fattura Tamoil"""
        text = self.get_pdf_text(pdf)

        header = {
            "numero_fattura": "",
            "data_fattura": "",
            "cliente": "BEEBUS SPA",
            "totale_imponibile": 0.0,
            "totale_iva": 0.0,
            "totale_fattura": 0.0
        }

        # Estrai numero fattura (formato: DA25191152)
        # Il numero sta nella riga dei valori sotto le etichette:
        # "Fattura N° Data fattura Cod. Cliente ..." / "DA25191152 15/10/2025 ..."
        match_nr = re.search(r"Fattura N°[\s\S]*?\b([A-Z]{2}\d{6,})\b", text)
        if match_nr:
            header["numero_fattura"] = match_nr.group(1)

        # Estrai data fattura
        match_data = re.search(r"Data fattura\s*(\d{2}/\d{2}/\d{4})", text)
        if match_data:
            header["data_fattura"] = match_data.group(1)

        # Estrai cliente
        match_cliente = re.search(r"Cliente:\s*Spett\.\s*([A-Z\s]+)", text)
        if match_cliente:
            header["cliente"] = match_cliente.group(1).strip()

        # Estrai totali
        match_imponibile = re.search(r"Imponibile IVA\s*EUR\s*([\d.,]+)", text)
        if match_imponibile:
            header["totale_imponibile"] = self.normalizza_numero(match_imponibile.group(1))

        match_iva = re.search(r"Importo IVA\s*EUR\s*([\d.,]+)", text)
        if match_iva:
            header["totale_iva"] = self.normalizza_numero(match_iva.group(1))

        match_totale = re.search(r"Totale Fattura.*?EUR\s*([\d.,]+)", text)
        if match_totale:
            header["totale_fattura"] = self.normalizza_numero(match_totale.group(1))

        return header

    def extract_transactions(self, pdf) -> List[Transaction]:
        """Estrae le transazioni dalla fattura Tamoil"""
        transactions = []
        transazioni_in_attesa = []
        visti = set()
        targa_corrente = None

        for page in pdf.pages:
            words = page.extract_words(
                x_tolerance=3,
                y_tolerance=3,
                keep_blank_chars=False,
                use_text_flow=True
            )

            # Raggruppa parole per riga
            righe = defaultdict(list)
            for w in words:
                righe[round(w["top"])].append(w["text"])

            # Processa ogni riga
            for top in sorted(righe.keys()):
                line = " ".join(righe[top]).strip()
                if not line:
                    continue

                # Cerca targa nella riga totale carta
                # Formato: "Totale Carta 7083651392996570 Targa FK444ZJ"
                match_targa = re.search(r"Targa\s+([A-Z]{2}\d{3}[A-Z]{2})", line)
                if match_targa:
                    # Assegna targa alle transazioni in attesa
                    targa = match_targa.group(1)
                    for trans_dict in transazioni_in_attesa:
                        trans_dict["targa"] = targa
                        key = (
                            trans_dict["data"],
                            trans_dict["ora"],
                            trans_dict["numero_scontrino"]
                        )
                        if key not in visti:
                            visti.add(key)
                            transactions.append(Transaction(**trans_dict))

                    transazioni_in_attesa = []
                    targa_corrente = targa
                    continue

                # Cerca transazioni
                # Formato: S 8478 SACROFANO (RM) 674676 01/10/2025 09:55 1 Gasolio Self LT 61,92 101,49
                match_txn = self._trova_transazione(line)
                if match_txn:
                    try:
                        trans_dict = self._parse_transaction(match_txn, line)
                        transazioni_in_attesa.append(trans_dict)
                    except Exception as e:
                        logger.debug("Riga transazione scartata: %s (%s)", line, e)
                        continue

        # Gestisci transazioni rimaste (senza targa)
        for trans_dict in transazioni_in_attesa:
            trans_dict["targa"] = "SCONOSCIUTA"
            key = (trans_dict["data"], trans_dict["ora"], trans_dict["numero_scontrino"])
            if key not in visti:
                visti.add(key)
                transactions.append(Transaction(**trans_dict))

        return transactions

    def _trova_transazione(self, line: str):
        """
        Pattern regex per identificare una transazione Tamoil.
        Formato: S 8478 SACROFANO (RM) 674676 01/10/2025 09:55 1 Gasolio Self LT 61,92 101,49
        """
        pattern = (
            r"^S\s+"                            # Nota (S = Self pre-pay)
            r"(\d+)\s+"                         # Codice PV
            r"([A-Z\s()]+?)\s+"                 # Località (può contenere parentesi)
            r"(\d+)\s+"                         # N° Autorizzazione (numero scontrino)
            r"(\d{2}/\d{2}/\d{4})\s+"          # Data (DD/MM/YYYY)
            r"(\d{2}:\d{2})\s+"                # Ora
            r"(\d+)\s+"                         # KM
            r"(.+?)\s+"                         # Prodotto (es: Gasolio Self, Gasolio)
            r"LT\s+"                            # Unità di misura (sempre LT)
            r"([\d,]+)\s+"                      # Quantità
            r"([\d,]+)"                         # Importo
        )
        return re.search(pattern, line)

    def _parse_transaction(self, match, line: str) -> Dict[str, Any]:
        """Converte il match regex in un dizionario per Transaction"""
        codice_pv = match.group(1)
        localita_raw = match.group(2)
        numero_autorizzazione = match.group(3)
        data = match.group(4)
        ora = match.group(5)
        km_raw = match.group(6)
        prodotto_raw = match.group(7)
        quantita_raw = match.group(8)
        importo_raw = match.group(9)

        localita = localita_raw.strip()
        km = int(km_raw) if km_raw and km_raw != "1" else 0  # "1" indica KM non inseriti
        prodotto = self.normalizza_prodotto(prodotto_raw)
        quantita = self.normalizza_numero(quantita_raw)
        importo = self.normalizza_numero(importo_raw)
        prezzo_unitario = importo / quantita if quantita > 0 else 0.0

        return {
            "data": data,
            "ora": ora,
            "numero_scontrino": numero_autorizzazione,
            "codice_sede": codice_pv,
            "localita": localita,
            "targa": "",  # Verrà assegnata dopo
            "chilometraggio": km,
            "prodotto": prodotto,
            "quantita": quantita,
            "prezzo_unitario": prezzo_unitario,
            "importo_totale": importo,
            "fornitore": "TAMOIL"
        }
