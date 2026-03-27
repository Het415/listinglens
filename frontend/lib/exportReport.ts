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

/** risk_score from API is 0–1 probability; some payloads may use 0–100. Fallback to risk_pct. */
function normalizeRiskScore01(risk: AnalyzeResponse['risk'] | undefined): number {
  const raw = risk?.risk_score
  if (typeof raw === 'number' && Number.isFinite(raw)) {
    if (raw > 1) return Math.min(1, raw / 100)
    return Math.max(0, Math.min(1, raw))
  }
  const pct = risk?.risk_pct
  if (typeof pct === 'number' && Number.isFinite(pct)) {
    return Math.max(0, Math.min(1, pct / 100))
  }
  return 0
}

function wrapText(doc: any, text: string, maxWidth: number): string[] {
  const t = text || ''
  if (!t.trim()) return ['']
  return doc.splitTextToSize(t, maxWidth)
}

function roundedRectFallback(doc: any, x: number, y: number, w: number, h: number, rx: number, ry: number) {
  const anyDoc = doc as any
  if (typeof anyDoc.roundedRect === 'function') {
    anyDoc.roundedRect(x, y, w, h, rx, ry)
    return
  }
  doc.rect(x, y, w, h)
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

export async function exportToPDF(data: AnalyzeResponse): Promise<void> {
  const jsPDF = await getJsPDF()

  const now = new Date()
  const dateStr = now.toISOString().slice(0, 10)

  const asin = data.asin || ''
  const productName = data.product_name || asin

  const risk = data.risk || {}
  const summary = data.summary || {}
  const features = data.features || {}

  const riskNorm = normalizeRiskScore01(risk)
  const overallListingScore = Math.round((1 - riskNorm) * 100)

  const riskPct = safeNumber(risk.risk_pct, Math.round(riskNorm * 100))
  const riskLabel = (risk.risk_label || 'UNKNOWN').toUpperCase()

  const ratingAvg = safeNumber(summary.avg_rating, 0)
  const pctPositive = safeNumber(summary.pct_positive, 0)
  const pctNegative = safeNumber(summary.pct_negative, 0)
  const avgCompoundScore = safeNumber(features.avg_compound_score, 0)
  const ratingSentimentGap = safeNumber(features.rating_sentiment_gap, 0)

  const topTopics = Array.isArray(summary.top_topics) ? summary.top_topics : []

  const doc = new jsPDF({ unit: 'pt', format: 'a4' })
  const pageW = doc.internal.pageSize.getWidth()
  const pageH = doc.internal.pageSize.getHeight()

  const MM_TO_PT = 2.8346456693
  const sectionGap = 8 * MM_TO_PT

  const marginX = 8 * MM_TO_PT
  const maxContentW = pageW - marginX * 2

  const navy = hexRgb('#0F172A')
  const teal = hexRgb('#2DD4BF')
  const grayBorder = hexRgb('#E2E8F0')
  const rowAlt = hexRgb('#F8FAFC')
  const recBox = hexRgb('#EFF6FF')
  const blueLabel = hexRgb('#2563EB')
  const amberLabel = hexRgb('#D97706')
  const redLabel = hexRgb('#DC2626')

  const footerUrl = 'https://listinglens-kappa.vercel.app'

  // ── HEADER (full width navy) ─────────────────────────────────────────────
  const headerH = 118
  doc.setFillColor(navy.r, navy.g, navy.b)
  doc.rect(0, 0, pageW, headerH, 'F')

  // Logo: 2×2 grid + wordmark
  const logoX = marginX
  const logoY = 22
  const sq = 5
  const sqGap = 2
  doc.setFillColor(255, 255, 255)
  doc.rect(logoX, logoY, sq, sq, 'F')
  doc.rect(logoX + sq + sqGap, logoY, sq, sq, 'F')
  doc.rect(logoX, logoY + sq + sqGap, sq, sq, 'F')
  doc.rect(logoX + sq + sqGap, logoY + sq + sqGap, sq, sq, 'F')

  doc.setTextColor(255, 255, 255)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(18)
  doc.text('ListingLens', logoX + sq * 2 + sqGap * 2 + 10, logoY + 9)

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(11)
  const grayRgb = hexRgb('#94A3B8')
  doc.setTextColor(grayRgb.r, grayRgb.g, grayRgb.b)
  doc.text(`ASIN ${asin}`, logoX, logoY + 32)
  doc.text(dateStr, pageW - marginX - doc.getTextWidth(dateStr), logoY + 32)

  doc.setTextColor(255, 255, 255)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(20)
  const titleLines = wrapText(doc, productName, maxContentW - 8)
  let hy = logoY + 52
  for (const line of titleLines.slice(0, 2)) {
    doc.text(line, marginX, hy)
    hy += 22
  }

  doc.setDrawColor(teal.r, teal.g, teal.b)
  doc.setLineWidth(1.2)
  doc.line(0, headerH - 2, pageW, headerH - 2)

  let y = headerH + sectionGap

  const bodyText = (text: string, color = [15, 23, 42] as const) => {
    doc.setFontSize(11)
    doc.setFont('helvetica', 'normal')
    doc.setTextColor(color[0], color[1], color[2])
    const lines = wrapText(doc, text, maxContentW)
    const lineH = 14
    for (const line of lines) {
      doc.text(line, marginX, y)
      y += lineH
    }
  }

  const riskExplanation = typeof risk.explanation === 'string' ? risk.explanation.trim() : ''

  // ── Executive Summary (2×2 grid) ────────────────────────────────────────
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(13)
  doc.setTextColor(15, 23, 42)
  doc.text('Executive Summary', marginX, y)
  y += 20

  const gutter = 10
  const cellW = (maxContentW - gutter) / 2
  const cellH = 52
  const gridTop = y

  type CellSpec = {
    label: string
    labelRgb: { r: number; g: number; b: number }
    value: string
    valueRgb: { r: number; g: number; b: number }
  }

  const returnRiskRgb = riskLabelColors(riskLabel)

  const execCells: CellSpec[] = [
    { label: 'Overall Score', labelRgb: blueLabel, value: `${overallListingScore}/100`, valueRgb: blueLabel },
    {
      label: 'Return Risk',
      labelRgb: returnRiskRgb,
      value: `${formatPercent(riskPct)} — ${riskLabel}`,
      valueRgb: returnRiskRgb,
    },
    {
      label: 'Average Rating',
      labelRgb: amberLabel,
      value: `${ratingAvg.toFixed(1)}/5.0`,
      valueRgb: hexRgb('#0F172A'),
    },
    {
      label: 'Negative %',
      labelRgb: redLabel,
      value: formatPercent(pctNegative),
      valueRgb: redLabel,
    },
  ]

  execCells.forEach((cell, i) => {
    const col = i % 2
    const row = Math.floor(i / 2)
    const x = marginX + col * (cellW + gutter)
    const cy = gridTop + row * (cellH + gutter)

    doc.setDrawColor(grayBorder.r, grayBorder.g, grayBorder.b)
    doc.setLineWidth(0.6)
    const rd = doc as any
    if (typeof rd.roundedRect === 'function') {
      rd.roundedRect(x, cy, cellW, cellH, 4, 4, 'S')
    } else {
      doc.rect(x, cy, cellW, cellH, 'S')
    }

    doc.setFont('helvetica', 'normal')
    doc.setFontSize(8)
    doc.setTextColor(cell.labelRgb.r, cell.labelRgb.g, cell.labelRgb.b)
    doc.text(cell.label.toUpperCase(), x + 10, cy + 14)

    doc.setFont('helvetica', 'bold')
    doc.setFontSize(15)
    doc.setTextColor(cell.valueRgb.r, cell.valueRgb.g, cell.valueRgb.b)
    doc.text(cell.value, x + 10, cy + 38)
  })

  y = gridTop + 2 * (cellH + gutter) + sectionGap

  // ── Risk Assessment ───────────────────────────────────────────────────
  const riskTitleY = y + sectionGap
  y = riskTitleY
  const riskTitleStr = 'Return Risk Analysis'
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(13)
  doc.setTextColor(15, 23, 42)
  const riskTitleW = doc.getTextWidth(riskTitleStr)
  doc.text(riskTitleStr, marginX, y)

  const badgePadX = 8
  const badgeText = riskLabel
  doc.setFontSize(9)
  doc.setFont('helvetica', 'bold')
  const badgeW = doc.getTextWidth(badgeText) + badgePadX * 2
  const badgeH = 14
  const badgeX = marginX + riskTitleW + 6
  const br = riskLabelColors(riskLabel)
  doc.setFillColor(br.r, br.g, br.b)
  doc.rect(badgeX, y - badgeH + 4, badgeW, badgeH, 'F')
  doc.setTextColor(255, 255, 255)
  doc.setFont('helvetica', 'bold')
  doc.text(badgeText, badgeX + badgePadX, y - 1)
  y += 22

  doc.setTextColor(15, 23, 42)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(11)
  bodyText(riskExplanation || 'No risk explanation was provided by the analysis.')
  y += 8

  // Sentiment bar: negative (red) vs positive (teal)
  const barY = y
  const barH = 16
  const sumP = Math.max(1e-6, pctNegative + pctPositive)
  const wNeg = maxContentW * (pctNegative / sumP)
  const wPos = maxContentW * (pctPositive / sumP)

  doc.setFontSize(9)
  doc.setTextColor(100, 116, 139)
  doc.text('Review sentiment mix', marginX, barY - 4)

  doc.setFillColor(hexRgb('#EF4444').r, hexRgb('#EF4444').g, hexRgb('#EF4444').b)
  doc.rect(marginX, barY, wNeg, barH, 'F')
  doc.setFillColor(hexRgb('#14B8A6').r, hexRgb('#14B8A6').g, hexRgb('#14B8A6').b)
  doc.rect(marginX + wNeg, barY, wPos, barH, 'F')

  doc.setDrawColor(grayBorder.r, grayBorder.g, grayBorder.b)
  doc.setLineWidth(0.4)
  doc.rect(marginX, barY, wNeg + wPos, barH, 'S')

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(8)
  doc.setTextColor(15, 23, 42)
  doc.text(`Negative ${formatPercent(pctNegative)}`, marginX + 4, barY + 11)
  const posLabel = `Positive ${formatPercent(pctPositive)}`
  doc.text(posLabel, marginX + wNeg + wPos - doc.getTextWidth(posLabel) - 4, barY + 11)

  y = barY + barH + 18

  doc.setFontSize(11)
  doc.setTextColor(15, 23, 42)
  doc.text(`Compound score (avg): ${avgCompoundScore.toFixed(3)}`, marginX, y)
  y += sectionGap + 8

  // ── What customers are talking about ───────────────────────────────────
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(13)
  doc.text('What Customers Are Talking About', marginX, y)
  y += 20

  if (topTopics.length === 0) {
    bodyText('No topics were available in the analysis.')
  } else {
    const rowH = 22
    topTopics.forEach((t, idx) => {
      const label = t.label || 'Topic'
      const count = typeof t.count === 'number' ? t.count : 0
      const level = typeof t.complaint_level === 'string' ? t.complaint_level : undefined
      const dot = complaintDotRgb(level)
      const alt = idx % 2 === 1

      if (alt) {
        doc.setFillColor(rowAlt.r, rowAlt.g, rowAlt.b)
        doc.rect(marginX, y - 14, maxContentW, rowH, 'F')
      }

      doc.setFillColor(dot.r, dot.g, dot.b)
      const d = doc as any
      if (typeof d.circle === 'function') {
        d.circle(marginX + 6, y - 4, 2.5, 'F')
      } else {
        doc.rect(marginX + 3.5, y - 6.5, 5, 5, 'F')
      }

      doc.setFont('helvetica', 'normal')
      doc.setFontSize(11)
      doc.setTextColor(15, 23, 42)
      doc.text(label, marginX + 16, y)

      const countStr = `${count} reviews`
      doc.setFont('helvetica', 'bold')
      doc.text(countStr, pageW - marginX - doc.getTextWidth(countStr), y)

      y += rowH
    })
  }

  y += sectionGap

  // ── Recommended actions (numbered, light blue boxes) ───────────────────
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(13)
  doc.setTextColor(15, 23, 42)
  doc.text('Recommended Actions', marginX, y)
  y += 22

  const riskNegLine =
    pctNegative > 30
      ? `Address negative review patterns — ${pctNegative.toFixed(1)}% of reviews are negative. Focus on resolving the most common complaints.`
      : `Keep improving — negative sentiment is ${formatPercent(pctNegative)}.`

  const ratingLine =
    ratingAvg < 3.5
      ? `Improve product quality signals — average rating is ${ratingAvg.toFixed(1)}/5`
      : `Maintain quality signals — average rating is ${ratingAvg.toFixed(1)}/5`

  const gapLine =
    ratingSentimentGap > 0.1
      ? `Align listing description with customer expectations`
      : `Align messaging — customer expectations already match ratings closely`

  const recommendations = [riskNegLine, ratingLine, gapLine]

  const recPad = 10
  recommendations.forEach((rec, i) => {
    const lines = wrapText(doc, rec, maxContentW - recPad * 2 - 18)
    const boxH = Math.max(36, lines.length * 13 + recPad * 2)

    doc.setFillColor(recBox.r, recBox.g, recBox.b)
    roundedRectFallback(doc, marginX, y, maxContentW, boxH, 4, 4)
    doc.rect(marginX, y, maxContentW, boxH, 'F')

    doc.setFont('helvetica', 'bold')
    doc.setFontSize(11)
    doc.setTextColor(blueLabel.r, blueLabel.g, blueLabel.b)
    doc.text(`${i + 1}.`, marginX + recPad, y + 18)

    doc.setFont('helvetica', 'normal')
    doc.setTextColor(15, 23, 42)
    let ly = y + 18
    for (const line of lines) {
      doc.text(line, marginX + recPad + 16, ly)
      ly += 13
    }
    y += boxH + 10
  })

  // ── Footer ─────────────────────────────────────────────────────────────
  const footerY = pageH - 36
  doc.setDrawColor(grayBorder.r, grayBorder.g, grayBorder.b)
  doc.setLineWidth(0.5)
  doc.line(marginX, footerY - 18, pageW - marginX, footerY - 18)

  doc.setFontSize(9)
  doc.setFont('helvetica', 'normal')
  doc.setTextColor(100, 116, 139)
  const leftFooter = 'Generated by ListingLens'
  doc.text(leftFooter, marginX, footerY)

  const tealRgb = hexRgb('#2DD4BF')
  doc.setTextColor(tealRgb.r, tealRgb.g, tealRgb.b)
  doc.text(footerUrl, pageW - marginX - doc.getTextWidth(footerUrl), footerY)

  const pageCount = doc.getNumberOfPages ? doc.getNumberOfPages() : 1
  doc.setTextColor(100, 116, 139)
  doc.text(`Page ${pageCount}`, pageW / 2 - doc.getTextWidth(`Page ${pageCount}`) / 2, footerY)

  const safeFileBase = `${productName}`.replace(/[^a-z0-9]+/gi, '_').slice(0, 40)
  const filename = `${safeFileBase}_${asin}_report_${dateStr}.pdf`
  doc.save(filename)
}
