"""
BeeBus Fatture Extractor - API FastAPI per estrazione dati da fatture carburante.
Supporta fatture IP Plus, Esso e Q8 con auto-detection del formato.

Version 2.0.0 - Architettura modulare con estrattori multipli
"""
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import csv
import io
from datetime import datetime

# Import nuova architettura estrattori
from extractors.extractor_factory import ExtractorFactory

app = FastAPI(
    title="BeeBus Fatture Extractor",
    description="Estrazione automatica dati da fatture carburante (IP, Esso, Q8)",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS per frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In produzione: domini specifici BeeBus
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic models per API documentation
class ExtractionResult(BaseModel):
    status: str
    filename: str
    timestamp: str
    records_count: int
    total_amount: float
    data: List[dict]
    fornitore: Optional[str] = None
    message: Optional[str] = None

# Colonne del CSV per Autoroute (le nuove sono in coda per non spostare le esistenti)
CSV_FIELDNAMES = [
    "Targa", "Data_Rifornimento", "Ora_Rifornimento", "Chilometraggio",
    "Litri", "Importo_Totale", "Fornitore", "Tipo_Rifornimento",
    "Numero_Scontrino", "Localita", "Numero_Fattura", "Note", "Autista"
]

class BatchResult(BaseModel):
    status: str
    processed_files: int
    total_records: int
    results: List[ExtractionResult]

# Health check per Railway monitoring
@app.get("/")
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "beebus-extractor",
        "timestamp": datetime.now().isoformat(),
        "version": "2.0.0",
        "supported_providers": ["IP Plus", "Esso", "Q8"]
    }

def process_pdf_content(pdf_content: bytes, filename: str) -> dict:
    """
    Processa un PDF usando la Factory per auto-detection del tipo di fattura.

    Args:
        pdf_content: Contenuto binario del PDF
        filename: Nome del file

    Returns:
        Dizionario con i dati estratti

    Raises:
        HTTPException: Se il tipo di fattura non è riconosciuto o si verifica un errore
    """
    try:
        # Usa la Factory per identificare il tipo e estrarre i dati
        result = ExtractorFactory.extract_from_pdf(pdf_content, filename)
        return result

    except ValueError as e:
        # Errore di identificazione tipo fattura
        raise HTTPException(
            status_code=400,
            detail=f"Tipo di fattura non riconosciuto: {str(e)}"
        )
    except Exception as e:
        # Altri errori di processing
        raise HTTPException(
            status_code=500,
            detail=f"Errore durante l'estrazione: {str(e)}"
        )

# API ENDPOINTS

@app.post("/extract", response_model=ExtractionResult)
async def extract_single_pdf(file: UploadFile = File(...)):
    """
    Estrae dati da singolo PDF fattura carburante.
    Supporta automaticamente fatture IP Plus, Esso e Q8.

    - **file**: PDF file della fattura (max 50MB)

    Returns:
        ExtractionResult con dati estratti e fornitore identificato
    """
    if not file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="File deve essere PDF")

    if file.size and file.size > 50 * 1024 * 1024:  # 50MB limit
        raise HTTPException(status_code=400, detail="File troppo grande (max 50MB)")

    content = await file.read()
    result = process_pdf_content(content, file.filename)

    return result

@app.post("/extract-batch", response_model=BatchResult)
async def extract_multiple_pdfs(files: List[UploadFile] = File(...)):
    """
    Estrae dati da multipli PDF fatture.
    Ogni PDF viene processato automaticamente in base al suo tipo (IP, Esso, Q8).

    - **files**: Lista di PDF files (max 10 files)

    Returns:
        BatchResult con risultati aggregati e dettagli per ogni file
    """
    if len(files) > 10:
        raise HTTPException(status_code=400, detail="Max 10 files per batch")

    results = []
    total_records = 0
    errors = []

    for file in files:
        if file.filename.endswith('.pdf'):
            try:
                content = await file.read()
                result = process_pdf_content(content, file.filename)
                results.append(result)
                total_records += result["records_count"]
            except HTTPException as e:
                # Registra l'errore ma continua con gli altri file
                errors.append({
                    "filename": file.filename,
                    "error": e.detail
                })
                continue

    batch_result = {
        "status": "success" if results else "error",
        "processed_files": len(results),
        "total_records": total_records,
        "results": results
    }

    if errors:
        batch_result["errors"] = errors

    return batch_result

@app.post("/extract-csv")
async def extract_and_download_csv(files: List[UploadFile] = File(...)):
    """
    Estrae dati da multipli PDF e restituisce CSV unificato per download.
    Il CSV contiene tutte le transazioni di tutte le fatture in formato standardizzato.

    - **files**: Lista di PDF files

    Returns:
        JSONResponse con CSV data e filename per download
    """
    all_records = []
    processed_count = 0
    error_count = 0

    for file in files:
        if file.filename.endswith('.pdf'):
            try:
                content = await file.read()
                result = process_pdf_content(content, file.filename)
                all_records.extend(result["data"])
                processed_count += 1
            except Exception as e:
                error_count += 1
                continue

    if not all_records:
        raise HTTPException(
            status_code=400,
            detail=f"Nessun dato estratto. File processati: {processed_count}, Errori: {error_count}"
        )

    # Genera CSV
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDNAMES, delimiter=";")
    writer.writeheader()
    writer.writerows(all_records)

    # Return CSV as download
    csv_content = output.getvalue()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"beebus_rifornimenti_{timestamp}.csv"

    return JSONResponse(
        content={
            "csv_data": csv_content,
            "filename": filename,
            "total_records": len(all_records),
            "processed_files": processed_count,
            "errors": error_count
        },
        headers={"Content-Type": "application/json"}
    )

@app.post("/download-csv")
async def download_csv_file(files: List[UploadFile] = File(...)):
    """
    Estrae dati da multipli PDF e restituisce CSV scaricabile direttamente.
    Questo endpoint è ottimizzato per n8n e form web che vogliono download diretto.

    - **files**: Lista di PDF files

    Returns:
        File CSV scaricabile direttamente (Content-Disposition: attachment)
    """
    all_records = []
    processed_count = 0
    error_count = 0
    total_amount = 0.0

    for file in files:
        if file.filename.endswith('.pdf'):
            try:
                content = await file.read()
                result = process_pdf_content(content, file.filename)
                all_records.extend(result["data"])
                processed_count += 1
            except Exception as e:
                error_count += 1
                continue

    if not all_records:
        raise HTTPException(
            status_code=400,
            detail=f"Nessun dato estratto. File processati: {processed_count}, Errori: {error_count}"
        )

    # Calcola totale importo da tutti i record
    for record in all_records:
        try:
            amount = float(record.get("Importo_Totale", 0))
            total_amount += amount
        except (ValueError, TypeError):
            continue

    # Genera CSV
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDNAMES, delimiter=";")
    writer.writeheader()
    writer.writerows(all_records)

    # Prepara il file per il download
    csv_content = output.getvalue()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"beebus_rifornimenti_{timestamp}.csv"

    # Restituisci come file scaricabile con metadati negli header
    return StreamingResponse(
        io.BytesIO(csv_content.encode('utf-8')),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "X-Total-Records": str(len(all_records)),
            "X-Processed-Files": str(processed_count),
            "X-Errors": str(error_count),
            "X-Total-Amount": f"{total_amount:.2f}"
        }
    )

@app.get("/supported-providers")
async def get_supported_providers():
    """
    Restituisce la lista dei fornitori supportati con le loro caratteristiche.

    Returns:
        Lista dei fornitori supportati
    """
    return {
        "providers": [
            {
                "name": "IP Plus",
                "code": "IP",
                "description": "IP Plus S.R.L. - Fatture rifornimenti carburante",
                "identification": "IP PLUS S.R.L"
            },
            {
                "name": "Esso",
                "code": "ESSO",
                "description": "WEX Europe Services - Esso Card",
                "identification": "WEX Europe Services / ESSO CARD"
            },
            {
                "name": "Q8",
                "code": "Q8",
                "description": "Kuwait Petroleum Italia - CartissimaQ8",
                "identification": "Kuwait Petroleum Italia / CartissimaQ8"
            }
        ]
    }

# Per development locale
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
