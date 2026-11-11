// Person 5 builds the helmet HUD here.
// Ideas: heading, distance to the next stop, time back to shelter, oxygen and
// battery, radiation dose rate, alerts. Everything comes from `data.plan` and
// the files in CONTRACT.md. The placeholder below just proves the data arrives.

export default function HudView({ data }) {
  const plan = data.plan
  return (
    <div className="hud">
      <p className="hud-title">HUD (to build)</p>
      {plan ? (
        <p>
          Plan loaded: {plan.legs.length} legs, {plan.totals.total_min} min in total.
        </p>
      ) : (
        <p>No plan.json yet.</p>
      )}
    </div>
  )
}
