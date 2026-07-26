export function MetricCard({
  label,
  value,
  detail = null,
  tone = 'neutral',
  highlight = false,
  className = ''
}) {
  // The stylesheet styles KPI cells via .kpi-label / .kpi-value / .kpi-baseline
  // and colors the value per tone via `.kpi-cell.<tone> .kpi-value`, so emit
  // those class names (the tone stays a class on the root next to the caller's
  // .kpi-cell). Earlier this component emitted .metric-card-* names the
  // stylesheet never defined, so the text rendered unstyled and tone was inert.
  const classes = [tone, highlight ? 'highlight' : '', className].filter(Boolean).join(' ');

  return (
    <div className={classes}>
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{value}</div>
      {detail ? <div className="kpi-baseline">{detail}</div> : null}
    </div>
  );
}
