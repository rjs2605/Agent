// Export companies as CSV, Excel or PDF (built in the browser).
// Excel uses SheetJS, PDF uses jsPDF + AutoTable; both load from cdnjs only when needed.

const LIBS = {
  xlsx: ["https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js"],
  pdf: [
    "https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js",
    "https://cdnjs.cloudflare.com/ajax/libs/jspdf-autotable/3.8.2/jspdf.plugin.autotable.min.js",
  ],
};
const _loaded = {};
function loadScript(src) {
  if (_loaded[src]) return _loaded[src];
  _loaded[src] = new Promise((ok, fail) => {
    const s = document.createElement("script");
    s.src = src;
    s.onload = ok;
    s.onerror = () => { delete _loaded[src]; fail(new Error("Could not load export library (check internet)")); };
    document.head.appendChild(s);
  });
  return _loaded[src];
}

function stamp() { return new Date().toISOString().slice(0, 10); }
function fileSafe(s) { return String(s || "export").replace(/[^\w.-]+/g, "_").slice(0, 60); }

function download(blob, filename) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 500);
}

function toCsv(rows) {
  if (!rows.length) return "";
  const cols = Object.keys(rows[0]);
  const cell = (v) => {
    const s = String(v ?? "");
    return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [cols.map(cell).join(","), ...rows.map((r) => cols.map((c) => cell(r[c])).join(","))].join("\r\n");
}

function detailSheets(d) {
  const brief = [];
  const titles = { summary: "Summary", what_they_do: "What they do", size_locations_funding: "Size, locations, funding",
    recent_news: "Recent news", hiring: "Hiring", pain_points: "Pain points", opening_angle: "Opening angle", risks_unknowns: "Risks / unknowns" };
  Object.entries(titles).forEach(([k, t]) => (d.brief[k] || []).forEach((l) => brief.push({ Section: t, Text: l.text, Source: l.source_url || "" })));
  const signals = d.signals.map((s) => ({ Kind: s.is_signal ? "Signal" : "Noise", Type: s.type, Description: s.description, Date: s.event_date || "", Source: s.source_url || "" }));
  const people = d.contacts.map((c) => ({ Choice: c.rank === 1 ? "First" : "Backup", Name: c.name || "Name not found", Title: c.title || "", LinkedIn: c.profile_url || "", Confidence: c.confidence || "", Reason: c.reason || "" }));
  return { brief, signals, people };
}

async function exportCompanies(format, ids, label) {
  const q = ids && ids.length ? `?ids=${ids.join(",")}` : "";
  const data = await api(`/api/export${q}`);
  if (!data.rows.length) throw new Error("Nothing to export");
  const base = `leadpulse_${fileSafe(label || "companies")}_${stamp()}`;

  if (format === "csv") {
    download(new Blob(["﻿" + toCsv(data.rows)], { type: "text/csv;charset=utf-8" }), base + ".csv");
    return;
  }

  if (format === "xlsx") {
    await loadScript(LIBS.xlsx[0]);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(data.rows), "Companies");
    if (data.details.length === 1) {
      const s = detailSheets(data.details[0]);
      if (s.brief.length) XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(s.brief), "Brief");
      if (s.signals.length) XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(s.signals), "Signals");
      if (s.people.length) XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(s.people), "People");
    }
    XLSX.writeFile(wb, base + ".xlsx");
    return;
  }

  if (format === "pdf") {
    for (const src of LIBS.pdf) await loadScript(src);
    const { jsPDF } = window.jspdf;
    const single = data.details.length === 1;
    const doc = new jsPDF({ orientation: single ? "portrait" : "landscape", unit: "pt", format: "a4" });
    const purple = [124, 92, 255];
    doc.setFontSize(18); doc.setTextColor(40); doc.text("LeadPulse", 40, 44);
    doc.setFontSize(10); doc.setTextColor(120); doc.text(`${label || "All companies"} · exported ${stamp()}`, 40, 62);

    if (!single) {
      const cols = ["Company", "Website", "Status", "Score", "Why now", "Signal date", "Contact", "Contact title", "Message subject"];
      doc.autoTable({
        startY: 80, head: [cols], body: data.rows.map((r) => cols.map((c) => String(r[c] ?? ""))),
        styles: { fontSize: 7.5, cellPadding: 4, overflow: "linebreak" }, headStyles: { fillColor: purple },
        columnStyles: { 4: { cellWidth: 170 }, 8: { cellWidth: 140 } },
      });
    } else {
      const r = data.rows[0], d = data.details[0], s = detailSheets(d);
      doc.autoTable({ startY: 80, theme: "plain", styles: { fontSize: 9 }, body: [
        ["Company", r.Company], ["Website", r.Website], ["Score", `${r.Score} (fit ${r.Fit}, timing ${r.Timing}, reach ${r.Reachability})`],
        ["Why now", `${r["Why now"]} ${r["Signal date"] ? "(" + r["Signal date"] + ")" : ""}`], ["Contact", `${r.Contact || "Name not found"} - ${r["Contact title"]}`],
      ], columnStyles: { 0: { fontStyle: "bold", cellWidth: 90 } } });
      const section = (title, head, body) => {
        if (!body.length) return;
        doc.setFontSize(12); doc.setTextColor(40);
        doc.text(title, 40, doc.lastAutoTable.finalY + 26);
        doc.autoTable({ startY: doc.lastAutoTable.finalY + 34, head: [head], body, styles: { fontSize: 8, cellPadding: 4 }, headStyles: { fillColor: purple } });
      };
      section("Brief", ["Section", "Text", "Source"], s.brief.map((b) => [b.Section, b.Text, b.Source]));
      section("Signals", ["Kind", "Type", "Description", "Date"], s.signals.map((x) => [x.Kind, x.Type, x.Description, x.Date]));
      section("People", ["Choice", "Name", "Title", "Confidence", "Reason"], s.people.map((p) => [p.Choice, p.Name, p.Title, p.Confidence, p.Reason]));
      section("Message", ["Subject", "Body"], [[r["Message subject"], r.Message]]);
      section("Why this score", ["Reason"], (r["Score reasons"] || "").split(" | ").filter(Boolean).map((x) => [x]));
    }
    doc.save(base + ".pdf");
    return;
  }
  throw new Error("Unknown format");
}

async function runExport(format, ids, label) {
  try {
    toast(`Preparing ${format.toUpperCase()}…`);
    await exportCompanies(format, ids, label);
    toast("Export downloaded", "good");
  } catch (e) { toast(e.message, "error"); }
}
