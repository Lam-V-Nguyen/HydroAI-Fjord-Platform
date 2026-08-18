

export function pdfOpener(pdfName=null) {
    if (!pdfName) return;
    const win = window.open(`src_frontend/pdfs/${pdfName}`, '_blank');
    if (!win) alert('Please allow popups for this document');
}