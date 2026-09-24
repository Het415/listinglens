'use client'

import { useEffect, useMemo, useState } from 'react'
import { usePathname, useRouter } from 'next/navigation'
import { Check, ChevronsUpDown, Home } from 'lucide-react'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from '@/components/ui/command'
import { useSession } from '@/lib/auth-client'
import { switchHref } from '@/lib/product-nav'
import { useSupportedAsins } from '@/lib/use-supported-asins'

/** The product name in the top bar, as a picker: search the supported
 *  products and jump to the same page for another one. Signed-in sellers also
 *  get the products they worked on most recently at the top. */
export function ProductSwitcher({
  asin,
  productName,
  compact = false,
}: {
  asin: string
  productName: string
  compact?: boolean
}) {
  const router = useRouter()
  const pathname = usePathname()
  const [open, setOpen] = useState(false)
  const { products, loading } = useSupportedAsins()
  const { data: session } = useSession()
  const [recentAsins, setRecentAsins] = useState<string[]>([])

  // Refreshed on every open: a chat or a save since the last open should show.
  useEffect(() => {
    if (!open || !session) return
    const controller = new AbortController()
    fetch('/api/me/recent-products', { signal: controller.signal })
      .then((res) => (res.ok ? res.json() : { products: [] }))
      .then((body: { products?: { asin: string }[] }) =>
        setRecentAsins((body.products ?? []).map((p) => p.asin)),
      )
      .catch(() => {})
    return () => controller.abort()
  }, [open, session])

  const nameOf = useMemo(() => new Map(products.map((p) => [p.asin, p.name])), [products])
  // Only products the backend can still analyze; a recent one that was
  // dropped from the supported set would lead nowhere.
  const recent = recentAsins.filter((a) => nameOf.has(a))

  const go = (target: string) => {
    setOpen(false)
    if (target !== asin) router.push(switchHref(pathname, target))
  }

  const item = (a: string, name: string, keyPrefix: string) => (
    <CommandItem key={`${keyPrefix}-${a}`} value={`${keyPrefix} ${name} ${a}`} onSelect={() => go(a)}>
      <Check className={`size-4 ${a === asin ? 'opacity-100' : 'opacity-0'}`} />
      <span className="truncate">{name}</span>
      <span className="ml-auto font-mono text-[11px] text-muted-foreground">{a}</span>
    </CommandItem>
  )

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={`Current product: ${productName}. Switch product`}
          className={`flex min-w-0 items-center gap-1.5 rounded-md px-2 py-1 text-sm text-text-primary transition-colors hover:bg-background-card ${
            compact ? 'max-w-[8.5rem]' : 'max-w-[22rem]'
          }`}
        >
          <span className="truncate">{productName}</span>
          <ChevronsUpDown className="size-3.5 shrink-0 text-text-muted" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-80 p-0">
        <Command>
          <CommandInput placeholder="Search products…" />
          <CommandList>
            <CommandEmpty>{loading ? 'Loading products…' : 'No product matches.'}</CommandEmpty>
            {recent.length > 0 && (
              <CommandGroup heading="Recent">
                {recent.map((a) => item(a, nameOf.get(a) ?? a, 'recent'))}
              </CommandGroup>
            )}
            <CommandGroup heading="All products">
              {products.map((p) => item(p.asin, p.name, 'all'))}
            </CommandGroup>
            <CommandSeparator />
            <CommandGroup>
              <CommandItem value="homepage analyze another product" onSelect={() => { setOpen(false); router.push('/') }}>
                <Home className="size-4" />
                <span>Back to the homepage</span>
              </CommandItem>
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}
