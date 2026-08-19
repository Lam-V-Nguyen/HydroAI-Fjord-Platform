

export function pdfOpener(pdfName=null) {
    if (!pdfName) return;
    const win = window.open(`src_frontend/pdfs/${pdfName}`, '_blank');
    if (!win) alert('Please allow popups for this document');
}

export async function projectRender(objectInput, objectList, fullList) {
    // Update project list
    objectInput.addEventListener('input', (e) => { 
        if (fullList.length === 0) return;
        const value = e.target.value.trim();
        objectList.innerHTML = "";
        const filtered = fullList.filter(p => p.toLowerCase().includes(value.toLowerCase()));
        if (filtered.length === 0) {
            objectList.style.display = "none"; return;
        }
        filtered.forEach(p => {
            const li = document.createElement("li");
            li.textContent = p;
            li.addEventListener('mousedown', () => { 
                objectInput.value = p; objectList.style.display = "none";
            });
            objectList.appendChild(li);
        });
        objectList.style.display = filtered.length > 0 ? "block": "none";
    });
    objectInput.addEventListener('click', async () => {
        objectInput.dispatchEvent(new Event('input'));
    });
    objectInput.addEventListener('blur', () => { 
        setTimeout(() => { objectList.style.display = "none"; }, 100);
    });
}