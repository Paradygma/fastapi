"""
Estrattore per fatture Q8 (Kuwait Petroleum Italia - CartissimaQ8).
Gestisce il formato specifico delle fatture CartissimaQ8.
"""
import logging
import re
from typing import List, Dict, Any
from collections import defaultdict
from .base_extractor import BaseExtractor
from models.invoice_models import Transaction

logger = logging.getLogger(__name__)


class Q8Extractor(BaseExtractor):
    """Estrattore specifico per fatture Q8"""

    def __init__(self):
        super().__init__()
        self.fornitore = "Q8"

    def can_handle(self, pdf_text: str) -> bool:
        """Verifica se il PDF è una fattura Q8"""
        indicators = ["Kuwait Petroleum Italia", "CartissimaQ8", "Cartissima Q8", "CARTISSIMA Q8"]
        return any(indicator in pdf_text for indicator in indicators)

    def extract_invoice_header(self, pdf) -> Dict[str, Any]:
        """Estrae i dati dell'intestazione della fattura Q8"""
        text = self.get_pdf_text(pdf)

        header = {
            "numero_fattura": "",
            "data_fattura": "",
            "cliente": "BEEBUS SPA",
            "totale_imponibile": 0.0,
            "totale_iva": 0.0,
            "totale_fattura": 0.0
        }

        # Estrai numero fattura (formato: n. PJ10575389 del 15/10/25)
        match_nr = re.search(r"n\.\s*([A-Z0-9]+)\s+del", text, re.IGNORECASE)
        if match_nr:
            header["numero_fattura"] = match_nr.group(1)

        # Estrai data fattura
        match_data = re.search(r"del\s+(\d{2}/\d{2}/\d{2,4})", text)
        if match_data:
            header["data_fattura"] = match_data.group(1)

        # Estrai totali
        # Cerca BASE IMPONIBILE IVA TOTALE TOTALE FATTURA
        match_totali = re.search(
            r"BASE IMPONIBILE\s+IVA TOTALE\s+TOTALE FATTURA\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)",
            text
        )
        if match_totali:
            header["totale_imponibile"] = self.normalizza_numero(match_totali.group(1))
            header["totale_iva"] = self.normalizza_numero(match_totali.group(2))
            header["totale_fattura"] = self.normalizza_numero(match_totali.group(3))

        return header

    def extract_transactions(self, pdf) -> List[Transaction]:
        """Estrae le transazioni dalla fattura Q8"""
        transactions = []
        transazioni_in_attesa = []
        visti = set()
        targa_corrente = None

        for page_num, page in enumerate(pdf.pages):
            # Le transazioni sono nella pagina 3 (indice 2)
            if page_num < 2:
                continue

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

                # Prima cerca transazioni
                match_txn = self._trova_transazione(line)
                if match_txn:
                    try:
                        trans_dict = self._parse_transaction(match_txn, line)
                        transazioni_in_attesa.append(trans_dict)
                    except Exception as e:
                        logger.debug("Riga transazione scartata: %s (%s)", line, e)
                        continue

                # Poi cerca targa (appare dopo le transazioni)
                # Formato: "* TOTALE PAN 7028009864300015041 TARGA/NOME EL934BA *********"
                match_targa = re.search(r"TARGA/NOME\s+([A-Z]{2}\d{3}[A-Z]{2})", line)
                if match_targa:
                    targa_corrente = match_targa.group(1)

                    # Assegna la targa a tutte le transazioni in attesa
                    for trans_dict in transazioni_in_attesa:
                        trans_dict["targa"] = targa_corrente
                        key = (
                            trans_dict["data"],
                            trans_dict["ora"],
                            trans_dict["numero_scontrino"]
                        )
                        if key not in visti:
                            visti.add(key)
                            transactions.append(Transaction(**trans_dict))

                    # Svuota la lista
                    transazioni_in_attesa = []
                    continue

        # Gestisci transazioni rimaste senza targa
        for trans_dict in transazioni_in_attesa:
            trans_dict["targa"] = "SCONOSCIUTA"
            key = (trans_dict["data"], trans_dict["ora"], trans_dict["numero_scontrino"])
            if key not in visti:
                visti.add(key)
                transactions.append(Transaction(**trans_dict))

        return transactions

    def _trova_transazione(self, line: str):
        """
        Pattern regex per identificare una transazione Q8.
        Formato esempio: 7028009864300015041 00002 02/10/25 0852 GLS 0000 000001 5817 LOC.ACQUAVIVA S.S. 4 NEROLA SF 75,00 45,76 1,639

        Strategia: Cerco pattern più semplice e poi estraggo manualmente il resto
        """
        # Pattern semplificato: numero carta, ticket, data, ora, prodotto
        pattern = (
            r"^(\d{19})\s+"                 # Numero carta (19 cifre)
            r"(\d{5})\s+"                   # Numero ticket (5 cifre)
            r"(\d{2}/\d{2}/\d{2})\s+"      # Data (DD/MM/YY)
            r"(\d{4})\s+"                   # Ora (HHMM)
            r"([A-Z]{3})"                   # Codice prodotto (GLS, SSP, GPL, ecc.)
        )
        return re.search(pattern, line)

    def _parse_transaction(self, match, line: str) -> Dict[str, Any]:
        """Converte il match regex in un dizionario per Transaction"""
        numero_carta = match.group(1)
        numero_ticket = match.group(2)
        data = match.group(3)
        ora_raw = match.group(4)  # HHMM
        # Converti HHMM a HH:MM
        ora = f"{ora_raw[:2]}:{ora_raw[2:]}"
        codice_prodotto = match.group(5)

        # Estrai i numeri dalla riga (importo, litri, prezzo)
        # Pattern: cerco gruppi di cifre con virgola (formato europeo)
        numeri = re.findall(r"[\d]+,[\d]+", line)

        # Gli ultimi numeri nella riga sono nell'ordine:
        # Importo, Volume, Prezzo Finale, Sconto/Premio, Prezzo Base, Importo Totale
        # Ci interessano: Importo (indice 0), Volume (indice 1), Prezzo Finale (indice 2)

        importo_raw = numeri[0] if len(numeri) > 0 else "0,00"
        quantita_raw = numeri[1] if len(numeri) > 1 else "0,00"
        prezzo_raw = numeri[2] if len(numeri) > 2 else "0,00"

        importo = self.normalizza_numero(importo_raw)
        quantita = self.normalizza_numero(quantita_raw)
        prezzo_unitario = self.normalizza_numero(prezzo_raw)

        # Dopo il codice prodotto: Cod Veic. (4 cifre), KM, Cod PV
        # Esempio: GLS 0000 589392 5484
        match_colonne = re.search(
            r"[A-Z]{3}\s+\d{4}\s+(?P<km>\d+)\s+(?P<sede>\d+)",
            line
        )
        codice_sede = match_colonne.group("sede") if match_colonne else "0000"

        # KM riportato così com'è (anche valori anomali come 1), solo zeri iniziali rimossi
        km = int(match_colonne.group("km")) if match_colonne else 0

        # Estrai località (tra il codice sede e SF/SV/PP)
        # Cerco pattern: [codice_sede] [LOCALITÀ] [SF|SV|PP]
        match_localita = re.search(rf"{codice_sede}\s+(.+?)\s+(SF|SV|PP)\s+", line)
        localita = match_localita.group(1).strip() if match_localita else "SCONOSCIUTA"

        # Determina prodotto
        prodotto_map = {
            "GLS": "GASOLIO",
            "SSP": "BENZINA",
            "GPL": "GPL",
            "HGL": "GASOLIO PREMIUM",
            "GEC": "GASOLIO ECOPLUS",
            "BWR": "BENZINA 100",
            "HBZ": "BENZINA PREMIUM"
        }
        prodotto = prodotto_map.get(codice_prodotto, "GASOLIO")

        return {
            "data": data,
            "ora": ora,
            "numero_scontrino": numero_ticket,
            "codice_sede": codice_sede,
            "localita": localita,
            "targa": "",  # Verrà assegnata dopo
            "chilometraggio": km,
            "prodotto": prodotto,
            "quantita": quantita,
            "prezzo_unitario": prezzo_unitario,
            "importo_totale": importo,
            "fornitore": "Q8",
            "numero_carta": numero_carta
        }
