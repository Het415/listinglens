import type { Metadata, Viewport } from 'next'
import { DM_Sans, DM_Mono, Instrument_Serif } from 'next/font/google'
import { Analytics } from '@vercel/analytics/next'
import './globals.css'

const dmSans = DM_Sans({ 
  subsets: ['latin'],
  variable: '--font-dm-sans',
  display: 'swap',
})

const dmMono = DM_Mono({ 
  subsets: ['latin'],
  weight: ['400', '500'],
  variable: '--font-dm-mono',
  display: 'swap',
})

const instrumentSerif = Instrument_Serif({ 
  subsets: ['latin'],
  weight: '400',
  style: ['normal', 'italic'],
  variable: '--font-instrument-serif',
  display: 'swap',
})

export const metadata: Metadata = {
  title: 'ListingLens - Multimodal Product Intelligence Platform',
  description: 'AI-powered analysis for Amazon sellers. Understand why products fail, predict return risk, and optimize listings with multimodal AI.',
  keywords: ['Amazon', 'seller tools', 'product analysis', 'AI', 'return prediction', 'listing optimization'],
  icons: {
    icon: '/favicon.svg',
  },
}

export const viewport: Viewport = {
  themeColor: '#0A0A0F',
  width: 'device-width',
  initialScale: 1,
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="en" className="dark">
      <body className={`${dmSans.variable} ${dmMono.variable} ${instrumentSerif.variable} font-sans antialiased bg-[#0A0A0F] text-[#F1F0F7]`}>
        {children}
        <Analytics />
      </body>
    </html>
  )
}
