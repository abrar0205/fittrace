import type { SVGProps } from 'react'

const base = { width: 18, height: 18, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.6,
  strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const, 'aria-hidden': true }

type P = SVGProps<SVGSVGElement>
export const IconOverview = (p: P) => (<svg {...base} {...p}><rect x="3" y="3" width="8" height="8" /><rect x="13" y="3" width="8" height="5" /><rect x="13" y="10" width="8" height="11" /><rect x="3" y="13" width="8" height="8" /></svg>)
export const IconInspect = (p: P) => (<svg {...base} {...p}><rect x="3" y="5" width="7" height="14" /><rect x="14" y="5" width="7" height="14" /><path d="M10 12h4M10 9v6M14 9v6" /></svg>)
export const IconChart = (p: P) => (<svg {...base} {...p}><path d="M3 20h18" /><path d="M3 8h18" strokeDasharray="2 3" /><path d="M4 15l4-3 3 2 4-6 3 3 2-2" /></svg>)
export const IconTrace = (p: P) => (<svg {...base} {...p}><circle cx="5" cy="12" r="2" /><circle cx="12" cy="12" r="2" /><circle cx="19" cy="12" r="2" /><path d="M7 12h3M14 12h3" /><path d="M12 4v6M12 14v6" strokeDasharray="1.5 2.5" /></svg>)
export const IconInvestigate = (p: P) => (<svg {...base} {...p}><circle cx="10.5" cy="10.5" r="6" /><path d="M15 15l5.5 5.5" /><path d="M7.5 11.5l2 2 4-5" /></svg>)
export const IconPipeline = (p: P) => (<svg {...base} {...p}><path d="M3 6h6v4H3zM15 14h6v4h-6zM9 8h3v8h3" /></svg>)
export const IconMethod = (p: P) => (<svg {...base} {...p}><path d="M4 20V4h11l5 5v11z" /><path d="M8 13h8M8 16h5M8 10h4" /></svg>)
export const IconPlay = (p: P) => (<svg {...base} {...p}><path d="M7 5l12 7-12 7z" /></svg>)
export const IconCheck = (p: P) => (<svg {...base} {...p}><path d="M5 12.5l4.5 4.5L19 7.5" /></svg>)
export const IconWarn = (p: P) => (<svg {...base} {...p}><path d="M12 3l9.5 17h-19z" /><path d="M12 10v4.5M12 17.5v.5" /></svg>)
export const IconX = (p: P) => (<svg {...base} {...p}><path d="M6 6l12 12M18 6L6 18" /></svg>)
export const IconReset = (p: P) => (<svg {...base} {...p}><path d="M4 12a8 8 0 1 0 2.4-5.7" /><path d="M4 4v4h4" /></svg>)
export const IconDownload = (p: P) => (<svg {...base} {...p}><path d="M12 4v11M7 10l5 5 5-5M5 20h14" /></svg>)
export const IconArrow = (p: P) => (<svg {...base} {...p}><path d="M15 6l-6 6 6 6" /></svg>)

export function Logo(p: P) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden {...p}>
      <rect width="32" height="32" rx="6" fill="#2c353d" />
      <rect x="6" y="7" width="8" height="18" fill="#c9d3d9" />
      <rect x="18" y="7" width="8" height="18" fill="#c9d3d9" />
      <path d="M14 16h4M14 12.5v7M18 12.5v7" stroke="#2fd0d9" strokeWidth="1.5" />
    </svg>
  )
}
