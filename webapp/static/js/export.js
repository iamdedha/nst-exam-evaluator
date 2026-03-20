/* Client-side CSV export from currently visible table rows */

function exportTableCSV() {
    const table = document.getElementById('resultsTable');
    if (!table) return;

    const rows = [];

    // Header
    const headers = [];
    table.querySelectorAll('thead th').forEach(th => {
        headers.push(th.textContent.trim());
    });
    rows.push(headers.join(','));

    // Visible rows only
    table.querySelectorAll('tbody tr').forEach(tr => {
        if (tr.style.display === 'none') return;
        const cells = [];
        tr.querySelectorAll('td').forEach(td => {
            let text = td.textContent.trim().replace(/"/g, '""');
            // Skip action column
            if (td.querySelector('a.small-btn')) {
                text = '';
            }
            cells.push(`"${text}"`);
        });
        rows.push(cells.join(','));
    });

    const csv = rows.join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);

    const a = document.createElement('a');
    a.href = url;
    a.download = 'evaluation_results_filtered.csv';
    a.click();
    URL.revokeObjectURL(url);
}
