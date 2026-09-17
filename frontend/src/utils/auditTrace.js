let trace = null
export function startTrace() { trace = crypto.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`; return trace }
export function getTrace() { return trace ?? startTrace() }
export function audit(stage, data) {
  if (!import.meta.env.DEV) return
  const record = { trace_id: getTrace(), timestamp: new Date().toISOString(), stage, ...data }
  const entries = window.__KOALA_AUDIT__ ?? []
  entries.push(record)
  window.__KOALA_AUDIT__ = entries.slice(-200)
  window.exportKoalaAudit = () => window.__KOALA_AUDIT__.map((entry) => JSON.stringify(entry)).join('\n')
  if (data.warnings?.length) console.error('[KOALA contract]', record)
  else console.debug('[KOALA audit]', record)
}
