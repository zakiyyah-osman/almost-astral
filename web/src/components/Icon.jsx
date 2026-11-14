// Small line icons, drawn here so every control uses the same stroke and size.
const PATHS = {
  up: 'M4 10l4-4 4 4',
  down: 'M4 6l4 4 4-4',
  close: 'M4 4l8 8M12 4l-8 8',
  plus: 'M8 3v10M3 8h10',
  left: 'M10 3L5 8l5 5',
  right: 'M6 3l5 5-5 5',
  panel: 'M2.5 3.5h11v9h-11zM6.5 3.5v9',
  target: 'M8 2v3M8 11v3M2 8h3M11 8h3M8 5.5a2.5 2.5 0 1 1 0 5a2.5 2.5 0 1 1 0-5',
  flag: 'M4 14V2.5M4 3h7l-1.5 2.5L11 8H4',
  sort: 'M5 3v10M2.5 10.5L5 13l2.5-2.5M11 13V3M8.5 5.5L11 3l2.5 2.5',
  copy: 'M5.5 5.5h7v7h-7zM3.5 10.5v-7h7',
  home: 'M2.5 7.5L8 3l5.5 4.5M4 6.5V13h3V9.5h2V13h3V6.5',
  pin:'M8 14s4.5-4.2 4.5-7.5a4.5 4.5 0 0 0-9 0C3.5 9.8 8 14 8 14zM8 5a1.5 1.5 0 1 1 0 3a1.5 1.5 0 1 1 0-3',
}

export default function Icon({ name, size = 16 }) {
  return (
    <svg className="icon" width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={PATHS[name]} />
    </svg>
  )
}
