/* eslint-disable @typescript-eslint/no-explicit-any */
'use client'

let jsPDFPromise: Promise<any> | null = null
async function getJsPDF() {
  // Import lazily + force the browser build.
  // Importing `jspdf` at module scope causes Next.js SSR bundling to pick the Node build,
  // which in turn pulls `fflate/lib/node.cjs` and crashes with `Can't resolve <dynamic>`.
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
  // `splitTextToSize` returns lines that fit inside `maxWidth` (in current units).
  return doc.splitTextToSize(t, maxWidth)
}

function roundedRectFallback(doc: any, x: number, y: number, w: number, h: number, rx: number, ry: number) {
  // Some jsPDF builds may not expose roundedRect depending on version/bundler.
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

function firstSentence(text: string): string {
  const t = (text || '').trim()
  if (!t) return ''
  const m = t.match(/^[\s\S]*?[.!?](\s|$)/)
  const sentence = (m ? m[0] : t).trim()
  return sentence.length > 140 ? `${sentence.slice(0, 137)}...` : sentence
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

  const riskScore = safeNumber(risk.risk_score, 0)
  // Overall score should be displayed as X/100, not a decimal.
  const overallListingScore = Math.round((1 - riskScore) * 100)
  const riskPct = safeNumber(risk.risk_pct, Math.round(riskScore * 100))
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

  const marginX = 40
  const maxContentW = pageW - marginX * 2

  // Header needs extra vertical padding so Product + ASIN don't feel cramped.
  const headerH = 90
  const headerBlue = '#0F172A'

  const footerBottomPadPt = 5 * MM_TO_PT
  const sectionHeaderPrePadPt = 15 * MM_TO_PT
  const sectionBetweenPadPt = 8 * MM_TO_PT

  const headerRgb = {
    r: parseInt(headerBlue.slice(1, 3), 16),
    g: parseInt(headerBlue.slice(3, 5), 16),
    b: parseInt(headerBlue.slice(5, 7), 16),
  }

  // HEADER background
  doc.setFillColor(headerRgb.r, headerRgb.g, headerRgb.b)
  doc.rect(0, 0, pageW, headerH, 'F')

  // Header text
  doc.setTextColor(255, 255, 255)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(20)
  doc.text('ListingLens — Product Intelligence Report', marginX, 28)

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(11)
  doc.text(`Product: ${productName}`, marginX, 54)
  doc.text(`ASIN: ${asin}`, marginX, 70)
  doc.setFontSize(10)
  doc.text(`Generated on ${dateStr}`, marginX + maxContentW - 170, 70)

  // Divider line
  doc.setDrawColor(15, 23, 42)
  doc.setLineWidth(1)
  doc.line(marginX, headerH + 10, pageW - marginX, headerH + 10)

  // PAGE BODY (explicit white background)
  doc.setFillColor(255, 255, 255)
  // no need to fill; jsPDF default is white — but keep it consistent with the spec.

  let y = headerH + 18

  const sectionTitle = (title: string) => {
    // Extra whitespace before every section header.
    y += sectionHeaderPrePadPt
    doc.setFontSize(14)
    doc.setTextColor(15, 23, 42)
    doc.setFont('helvetica', 'bold')
    doc.text(title, marginX, y)
    y += 16
  }

  const bodyText = (text: string) => {
    doc.setFontSize(11)
    doc.setFont('helvetica', 'normal')
    doc.setTextColor(15, 23, 42)
    const lines = wrapText(doc, text, maxContentW)
    const lineH = 14
    for (const line of lines) {
      doc.text(line, marginX, y)
      y += lineH
    }
  }

  const riskExplanation = typeof risk.explanation === 'string' ? risk.explanation.trim() : ''

  // SECTION 1 — Executive Summary
  sectionTitle('Executive Summary')

  const gutter = 8
  // Box sizing: >= 42mm wide and ~20mm tall.
  const boxW = (maxContentW - gutter * 3) / 4
  const boxH = 20 * MM_TO_PT

  const boxes = [
    {
      title: 'Overall Listing Score',
      value: `${overallListingScore}/100`,
    },
    {
      title: 'Return Risk',
      value: `${formatPercent(riskPct)} — ${riskLabel}`,
    },
    {
      title: 'Average Rating',
      value: `${ratingAvg.toFixed(1)}/5.0`,
    },
    {
      title: 'Negative Reviews',
      value: `${formatPercent(pctNegative)}`,
    },
  ]

  const topY = y + 2
  boxes.forEach((b, i) => {
    const x = marginX + i * (boxW + gutter)
    doc.setDrawColor(15, 23, 42)
    doc.setLineWidth(0.8)
    roundedRectFallback(doc, x, topY, boxW, boxH, 8, 8)
    doc.setTextColor(15, 23, 42)
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(10)
    doc.text(b.title, x + 10, topY + 20)
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(13)
    doc.text(b.value, x + 10, topY + 40)
  })

  y = topY + boxH + sectionBetweenPadPt

  // SECTION 2 — Risk Assessment
  sectionTitle('Return Risk Analysis')
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(11)
  doc.setTextColor(15, 23, 42)

  bodyText(riskExplanation || 'No risk explanation was provided by the analysis.')

  const riskLineBlockYStart = y + 6
  y = riskLineBlockYStart

  const riskRows = [
    { k: 'Positive %', v: formatPercent(pctPositive) },
    { k: 'Negative %', v: formatPercent(pctNegative) },
    { k: 'Compound Score', v: avgCompoundScore.toFixed(3) },
  ]

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(11)
  let rx = marginX
  riskRows.forEach((r, idx) => {
    const label = `${r.k}: `
    doc.setFont('helvetica', 'bold')
    doc.text(label, rx, y)
    doc.setFont('helvetica', 'normal')
    doc.text(r.v, rx + doc.getTextWidth(label), y)
    if (idx < riskRows.length - 1) {
      rx = marginX
      y += 16
    }
  })

  y += sectionBetweenPadPt

  // SECTION 3 — Top Customer Topics
  sectionTitle('What Customers Are Talking About')
  if (topTopics.length === 0) {
    bodyText('No topics were available in the analysis.')
  } else {
    for (const t of topTopics) {
      const label = t.label || 'Topic'
      const count = typeof t.count === 'number' ? t.count : 0
      bodyText(`• ${label} (${count} reviews)`)
      // `bodyText` advances y already; keep spacing via line wrapping only.
    }
  }

  // SECTION 4 — AI Recommendations
  y += sectionBetweenPadPt
  sectionTitle('Recommended Actions')

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

  const recommendations = [
    // Keep the first bullet tied to risk explanation.
    typeof riskExplanation === 'string' && riskExplanation.length > 0
      ? riskNegLine
      : riskNegLine,
    ratingLine,
    gapLine,
  ]

  recommendations.forEach((rec) => {
    bodyText(`• ${rec}`)
  })

  // FOOTER
  doc.setTextColor(15, 23, 42)
  doc.setFontSize(9)
  doc.setFont('helvetica', 'normal')

  const footerY = pageH - 26 - footerBottomPadPt
  doc.text('Generated by ListingLens — listinglens-kappa.vercel.app', marginX, footerY)

  const pageCount = doc.getNumberOfPages ? doc.getNumberOfPages() : 1
  doc.text(`Page ${pageCount}`, marginX + maxContentW - 80, footerY)

  const safeFileBase = `${productName}`.replace(/[^a-z0-9]+/gi, '_').slice(0, 40)
  const filename = `${safeFileBase}_${asin}_report_${dateStr}.pdf`
  doc.save(filename)
}

