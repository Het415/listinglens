/* eslint-disable @typescript-eslint/no-explicit-any */
'use client'

let jsPDFPromise: Promise<any> | null = null
async function getJsPDF() {
  if (!jsPDFPromise) {
    jsPDFPromise = import('jspdf/dist/jspdf.umd.min.js').then((mod) => (mod as any).default ?? mod)
  }
  return jsPDFPromise
}

export type BriefResponse = {
  asin: string
  product_name?: string
  metrics?: {
    total_reviews?: number
    avg_rating?: number
    pct_negative?: number
    return_risk?: { risk_pct?: number; risk_label?: string } | null
    conversations?: { resolution_rate?: number; escalation_rate?: number } | null
  }
  brief: {
    headline: string
    situation: string
    key_findings: Array<{ metric: string; insight: string }>
    top_risks: string[]
    recommended_actions: Array<{ action: string; rationale: string; priority: string }>
    confidence: number
  }
}

const NAVY = { r: 17, g: 24, b: 39 }
const MUTED = { r: 100, g: 116, b: 139 }

/** Render the executive brief to a branded A4 PDF and trigger download. */
export async function exportBriefToPDF(data: BriefResponse): Promise<void> {
  const JsPDF = await getJsPDF()
  const doc = new JsPDF({ unit: 'pt', format: 'a4' })
  const pageW = doc.internal.pageSize.getWidth()
  const margin = 48
  const contentW = pageW - margin * 2
  let y = 0

  // Header band
  doc.setFillColor(NAVY.r, NAVY.g, NAVY.b)
  doc.rect(0, 0, pageW, 92, 'F')
  doc.setTextColor(255, 255, 255)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(20)
  doc.text('Executive Brief', margin, 44)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(11)
  const sub = `${data.product_name || data.asin} · ASIN ${data.asin} · ${new Date().toLocaleDateString()}`
  doc.text(sub, margin, 66)
  y = 124

  const line = (txt: string, size: number, bold = false, color = NAVY) => {
    doc.setTextColor(color.r, color.g, color.b)
    doc.setFont('helvetica', bold ? 'bold' : 'normal')
    doc.setFontSize(size)
    const lines = doc.splitTextToSize(txt, contentW)
    for (const l of lines) {
      if (y > 780) { doc.addPage(); y = 60 }
      doc.text(l, margin, y)
      y += size + 5
    }
  }
  const gap = (n = 8) => { y += n }

  // Headline + situation
  line(data.brief.headline, 14, true)
  gap(4)
  line(data.brief.situation, 10.5, false, MUTED)
  gap(12)

  // Key findings
  line('Key Findings', 12, true)
  gap(2)
  for (const f of data.brief.key_findings || []) {
    line(`• ${f.metric}`, 10.5, true)
    line(`   ${f.insight}`, 10, false, MUTED)
  }
  gap(12)

  // Risks
  line('Top Risks', 12, true)
  gap(2)
  for (const r of data.brief.top_risks || []) line(`• ${r}`, 10.5, false, MUTED)
  gap(12)

  // Actions
  line('Recommended Actions', 12, true)
  gap(2)
  for (const a of data.brief.recommended_actions || []) {
    line(`• [${(a.priority || '').toUpperCase()}] ${a.action}`, 10.5, true)
    line(`   ${a.rationale}`, 10, false, MUTED)
  }
  gap(14)
  line(`Confidence: ${Math.round((data.brief.confidence || 0) * 100)}%`, 10, false, MUTED)

  const name = (data.product_name || data.asin).replace(/[^a-z0-9]+/gi, '_')
  doc.save(`${name}_${data.asin}_executive_brief_${new Date().toISOString().slice(0, 10)}.pdf`)
}
