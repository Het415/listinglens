'use client'

/** `mark` is the grid alone, for tight spots like the phone top bar. */
export function Logo({ size = 'default' }: { size?: 'mark' | 'small' | 'default' }) {
  const gridSize = size === 'default' ? 'w-6 h-6' : 'w-5 h-5'
  const textSize = size === 'small' ? 'text-lg' : 'text-[22px]'
  const squareSize = size === 'default' ? 'w-2.5 h-2.5' : 'w-2 h-2'

  const grid = (
    <div className={`grid grid-cols-2 gap-0.5 ${gridSize}`}>
      <div className={`${squareSize} bg-accent-blue rounded-[2px]`} />
      <div className={`${squareSize} bg-accent-blue rounded-[2px]`} />
      <div className={`${squareSize} bg-accent-blue rounded-[2px]`} />
      <div className={`${squareSize} bg-accent-blue rounded-[2px]`} />
    </div>
  )
  if (size === 'mark') return <span aria-label="ListingLens">{grid}</span>

  return (
    <div className="flex items-center gap-3">
      {grid}
      <span className={`font-serif italic ${textSize} text-text-primary`}>
        ListingLens
      </span>
      <span className="px-2 py-0.5 text-[10px] font-medium bg-accent-teal/20 text-accent-teal rounded-full uppercase tracking-wider">
        Beta
      </span>
    </div>
  )
}
