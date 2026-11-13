// A small label saying where a number comes from. Hover (or long-press) shows the source.
//   real        measured by a NASA mission
//   calc        calculated by the app or the planner from real data and our assumptions
//   estimate    taken from somewhere else (for example Curiosity's dose at Gale)
//   assumption  a team choice (limits, pace, start time)
//   fake        placeholder data
const TEXT = { real: 'Real', calc: 'Calc', estimate: 'Estimate', assumption: 'Assumption', fake: 'Fake' }

export default function Tag({ kind, title }) {
  return (
    <span className={`tag ${kind}`} title={title} tabIndex={title ? 0 : undefined} aria-label={title ? `${TEXT[kind]}: ${title}` : TEXT[kind]}>
      {TEXT[kind]}
    </span>
  )
}
