'use client'

export function Logo({ size = 'default' }: { size?: 'small' | 'default' }) {
  const gridSize = size === 'small' ? 'w-5 h-5' : 'w-6 h-6'
  const textSize = size === 'small' ? 'text-lg' : 'text-[22px]'
  const squareSize = size === 'small' ? 'w-2 h-2' : 'w-2.5 h-2.5'

  return (
    <div className="flex items-center gap-3">
      <div className={`grid grid-cols-2 gap-0.5 ${gridSize}`}>
        <div className={`${squareSize} bg-accent-blue rounded-[2px]`} />
        <div className={`${squareSize} bg-accent-blue rounded-[2px]`} />
        <div className={`${squareSize} bg-accent-blue rounded-[2px]`} />
        <div className={`${squareSize} bg-accent-blue rounded-[2px]`} />
      </div>
      <span className={`font-serif italic ${textSize} text-text-primary`}>
        ListingLens
      </span>
      <span className="px-2 py-0.5 text-[10px] font-medium bg-accent-teal/20 text-accent-teal rounded-full uppercase tracking-wider">
        Beta
      </span>
    </div>
  )
}
