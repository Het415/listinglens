/* eslint-disable @typescript-eslint/no-explicit-any */
'use client'

let jsPDFPromise: Promise<any> | null = null
async function getJsPDF() {
  if (!jsPDFPromise) {
    jsPDFPromise = import('jspdf/dist/jspdf.umd.min.js').then((mod) => (mod as any).default ?? mod)
  }
  return jsPDFPromise
}

export type AnalyzeResponse = {
  asin: string
  product_name?: string
  summary?: {
    avg_rating?: number
    pct_negative?: number
    pct_positive?: number
    top_topics?: Array<{
      id?: number
      label: string
      keywords?: string[]
      count?: number
      complaint_level?: 'HIGH' | 'MEDIUM' | 'LOW' | string
    }>
    total_reviews?: number
  }
  features?: Record<string, number> | null
  risk?: {
    risk_score?: number
    risk_pct?: number
    risk_label?: string
    explanation?: string
  }
}

function safeNumber(n: unknown, fallback = 0): number {
  return typeof n === 'number' && Number.isFinite(n) ? n : fallback
}

function wrapText(doc: any, text: string, maxWidth: number): string[] {
  const t = text || ''
  if (!t.trim()) return ['']
  return doc.splitTextToSize(t, maxWidth)
}

function formatPercent(n: number): string {
  return `${n.toFixed(1).replace(/\.0$/, '')}%`
}

function hexRgb(hex: string): { r: number; g: number; b: number } {
  const h = hex.replace('#', '')
  return {
    r: parseInt(h.slice(0, 2), 16),
    g: parseInt(h.slice(2, 4), 16),
    b: parseInt(h.slice(4, 6), 16),
  }
}

function riskLabelColors(label: string): { r: number; g: number; b: number } {
  const u = label.toUpperCase()
  if (u.includes('HIGH')) return hexRgb('#DC2626')
  if (u.includes('MEDIUM')) return hexRgb('#D97706')
  return hexRgb('#16A34A')
}

function complaintDotRgb(level: string | undefined): { r: number; g: number; b: number } {
  const u = (level || '').toUpperCase()
  if (u === 'HIGH') return hexRgb('#EF4444')
  if (u === 'MEDIUM') return hexRgb('#F59E0B')
  if (u === 'LOW') return hexRgb('#22C55E')
  return hexRgb('#94A3B8')
}

/**
 * Single-page A4 PDF (210×297 mm). All Y positions are fixed in millimeters — no addPage(), no dynamic page breaks.
 */
export async function exportToPDF(data: AnalyzeResponse): Promise<void> {
  const jsPDF = await getJsPDF()

  const now = new Date()
  const dateStr = now.toISOString().slice(0, 10)

  const asin = data.asin || ''
  const productName = data.product_name || asin

  const risk = data.risk || {}
  const summary = data.summary || {}
  const features = data.features || {}

  const overallScore = Math.round((1 - (risk?.risk_score ?? 0.5)) * 100)

  const riskPct = safeNumber(risk.risk_pct, 0)
  const riskLabel = (risk.risk_label || 'UNKNOWN').toUpperCase()

  const ratingAvg = safeNumber(summary.avg_rating, 0)
  const pctPositive = safeNumber(summary.pct_positive, 0)
  const pctNegative = safeNumber(summary.pct_negative, 0)
  const ratingSentimentGap = safeNumber(features.rating_sentiment_gap, 0)

  const topTopics = Array.isArray(summary.top_topics) ? summary.top_topics : []

  const doc = new jsPDF({ unit: 'mm', format: 'a4' })
  const pageW = 210

  const navy = hexRgb('#0F172A')
  const teal = hexRgb('#2DD4BF')
  const grayMuted = hexRgb('#64748B')
  const grayBorder = hexRgb('#E2E8F0')
  const dark = hexRgb('#0F172A')
  const blueLabel = hexRgb('#2563EB')
  const amberLabel = hexRgb('#D97706')
  const redLabel = hexRgb('#DC2626')

  const riskExplanation = typeof risk.explanation === 'string' ? risk.explanation.trim() : ''

  // ── Header ───────────────────────────────────────────────────────────────
  doc.setFillColor(navy.r, navy.g, navy.b)
  doc.rect(0, 0, pageW, 32, 'F')

  doc.setTextColor(255, 255, 255)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(16)
  doc.text('ListingLens', 14, 12)

  doc.setFontSize(11)
  const nameLines = wrapText(doc, productName, 180)
  let nameY = 22
  for (const line of nameLines.slice(0, 2)) {
    doc.text(line, 14, nameY)
    nameY += 4
  }

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(8)
  doc.setTextColor(grayMuted.r, grayMuted.g, grayMuted.b)
  const asinDate = `ASIN ${asin}  ·  ${dateStr}`
  doc.text(asinDate, 196, 12, { align: 'right' })

  doc.setFillColor(teal.r, teal.g, teal.b)
  doc.rect(0, 32, pageW, 0.8, 'F')

  // ── Executive Summary label + 4 boxes (one row) ────────────────────────
  doc.setTextColor(dark.r, dark.g, dark.b)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(10)
  doc.text('Executive Summary', 14, 42)

  const returnRiskRgb = riskLabelColors(riskLabel)
  const boxY = 46
  const boxH = 22
  const boxW = 44
  const boxXs = [14, 60, 106, 152]

  const cells = [
    { label: 'OVERALL SCORE', value: `${overallScore}/100`, lr: blueLabel, vr: blueLabel },
    {
      label: 'RETURN RISK',
      value: `${formatPercent(riskPct)} ${riskLabel}`,
      lr: returnRiskRgb,
      vr: returnRiskRgb,
    },
    {
      label: 'AVERAGE RATING',
      value: `${ratingAvg.toFixed(1)}/5.0`,
      lr: amberLabel,
      vr: dark,
    },
    {
      label: 'NEGATIVE %',
      value: formatPercent(pctNegative),
      lr: redLabel,
      vr: redLabel,
    },
  ]

  cells.forEach((cell, i) => {
    const x = boxXs[i]
    doc.setDrawColor(grayBorder.r, grayBorder.g, grayBorder.b)
    doc.setLineWidth(0.2)
    doc.rect(x, boxY, boxW, boxH, 'S')

    doc.setFont('helvetica', 'normal')
    doc.setFontSize(6)
    doc.setTextColor(cell.lr.r, cell.lr.g, cell.lr.b)
    doc.text(cell.label, x + 2, boxY + 5)

    doc.setFont('helvetica', 'bold')
    doc.setFontSize(9)
    doc.setTextColor(cell.vr.r, cell.vr.g, cell.vr.b)
    const vlines = wrapText(doc, cell.value, boxW - 4)
    let vy = boxY + 12
    for (const vl of vlines.slice(0, 2)) {
      doc.text(vl, x + 2, vy)
      vy += 4
    }
  })

  // ── Return Risk Analysis ────────────────────────────────────────────────
  const titleStr = 'Return Risk Analysis'
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(10)
  doc.setTextColor(dark.r, dark.g, dark.b)
  doc.text(titleStr, 14, 76)

  doc.setFontSize(7)
  const titleW = doc.getTextWidth(titleStr)
  const badgeText = riskLabel
  doc.setFont('helvetica', 'bold')
  const badgePadX = 1.5
  const badgeW = doc.getTextWidth(badgeText) + badgePadX * 2
  const badgeH = 6
  const badgeX = 14 + titleW + 2
  const br = riskLabelColors(riskLabel)
  doc.setFillColor(br.r, br.g, br.b)
  doc.rect(badgeX, 76 - 4.5, badgeW, badgeH, 'F')
  doc.setTextColor(255, 255, 255)
  doc.text(badgeText, badgeX + badgePadX, 76 - 0.5)

  // Explanation y=84, 8.5pt, 180mm
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(8.5)
  doc.setTextColor(dark.r, dark.g, dark.b)
  const explainLines = wrapText(doc, riskExplanation || 'No risk explanation was provided.', 180)
  let ey = 84
  for (const line of explainLines) {
    doc.text(line, 14, ey)
    ey += 3.6
  }

  // Sentiment mix y=96
  const sumP = Math.max(1e-6, pctNegative + pctPositive)
  const wNeg = 180 * (pctNegative / sumP)
  const wPos = 180 * (pctPositive / sumP)
  const barY = 98
  const barH = 4

  doc.setFontSize(8.5)
  doc.setTextColor(grayMuted.r, grayMuted.g, grayMuted.b)
  doc.text('Review sentiment mix', 14, 96)

  doc.setFillColor(hexRgb('#EF4444').r, hexRgb('#EF4444').g, hexRgb('#EF4444').b)
  doc.rect(14, barY, wNeg, barH, 'F')
  doc.setFillColor(hexRgb('#14B8A6').r, hexRgb('#14B8A6').g, hexRgb('#14B8A6').b)
  doc.rect(14 + wNeg, barY, wPos, barH, 'F')
  doc.setDrawColor(grayBorder.r, grayBorder.g, grayBorder.b)
  doc.setLineWidth(0.15)
  doc.rect(14, barY, wNeg + wPos, barH, 'S')

  doc.setFontSize(7)
  doc.setTextColor(dark.r, dark.g, dark.b)
  doc.text(`Neg ${formatPercent(pctNegative)}`, 15, barY + barH + 3)
  doc.text(`Pos ${formatPercent(pctPositive)}`, 14 + wNeg + wPos - doc.getTextWidth(`Pos ${formatPercent(pctPositive)}`), barY + barH + 3)

  // ── Topics ──────────────────────────────────────────────────────────────
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(10)
  doc.setTextColor(dark.r, dark.g, dark.b)
  doc.text('What Customers Are Talking About', 14, 106)

  const topicRowH = 7
  const topicStartY = 112
  for (let i = 0; i < 5; i++) {
    const y = topicStartY + i * topicRowH
    const left = topTopics[i]
    const right = topTopics[i + 5]

    if (left) {
      const dot = complaintDotRgb(left.complaint_level)
      doc.setFillColor(dot.r, dot.g, dot.b)
      doc.circle(15, y - 0.8, 0.9, 'F')
      doc.setFont('helvetica', 'normal')
      doc.setFontSize(8)
      doc.setTextColor(dark.r, dark.g, dark.b)
      const lt = wrapText(doc, left.label || 'Topic', 85)[0] || ''
      doc.text(lt, 18, y)
      doc.setFont('helvetica', 'bold')
      doc.text(`${left.count ?? 0}`, 100, y, { align: 'right' })
    }

    if (right) {
      const dot = complaintDotRgb(right.complaint_level)
      doc.setFillColor(dot.r, dot.g, dot.b)
      doc.circle(111, y - 0.8, 0.9, 'F')
      doc.setFont('helvetica', 'normal')
      doc.setFontSize(8)
      doc.setTextColor(dark.r, dark.g, dark.b)
      const rt = wrapText(doc, right.label || 'Topic', 85)[0] || ''
      doc.text(rt, 114, y)
      doc.setFont('helvetica', 'bold')
      doc.text(`${right.count ?? 0}`, 196, y, { align: 'right' })
    }
  }

  // ── Recommended Actions ────────────────────────────────────────────────
  const pctNeg = pctNegative
  const riskNegLine =
    pctNeg > 30
      ? `Address negative review patterns — ${pctNeg.toFixed(1)}% of reviews are negative. Focus on resolving the most common complaints.`
      : `Keep improving — negative sentiment is ${formatPercent(pctNeg)}.`

  const ratingLine =
    ratingAvg < 3.5
      ? `Improve product quality signals — average rating is ${ratingAvg.toFixed(1)}/5`
      : `Maintain quality signals — average rating is ${ratingAvg.toFixed(1)}/5`

  const gapLine =
    ratingSentimentGap > 0.1
      ? `Align listing description with customer expectations`
      : `Align messaging — customer expectations already match ratings closely`

  doc.setFont('helvetica', 'bold')
  doc.setFontSize(10)
  doc.setTextColor(dark.r, dark.g, dark.b)
  doc.text('Recommended Actions', 14, 152)

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(8.5)
  const recs = [riskNegLine, ratingLine, gapLine]
  const recYs = [159, 166, 173]
  recs.forEach((rec, idx) => {
    const lines = wrapText(doc, `${idx + 1}. ${rec}`, 180)
    lines.forEach((line, li) => {
      doc.text(line, 14, recYs[idx] + li * 3.5)
    })
  })

  // ── Footer ──────────────────────────────────────────────────────────────
  doc.setDrawColor(grayBorder.r, grayBorder.g, grayBorder.b)
  doc.setLineWidth(0.3)
  doc.line(14, 284, 196, 284)

  doc.setFontSize(8)
  doc.setFont('helvetica', 'normal')
  doc.setTextColor(grayMuted.r, grayMuted.g, grayMuted.b)
  doc.text('Generated by ListingLens', 14, 289)

  const tealRgb = hexRgb('#2DD4BF')
  doc.setTextColor(tealRgb.r, tealRgb.g, tealRgb.b)
  const url = 'https://listinglens-kappa.vercel.app'
  doc.text(url, 196, 289, { align: 'right' })

  doc.setTextColor(grayMuted.r, grayMuted.g, grayMuted.b)
  doc.text('Page 1', 105, 289, { align: 'center' })

  const safeFileBase = `${productName}`.replace(/[^a-z0-9]+/gi, '_').slice(0, 40)
  const filename = `${safeFileBase}_${asin}_report_${dateStr}.pdf`
  doc.save(filename)
}
