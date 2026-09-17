export async function measureAsync(label, task) {
  const startedAt = performance.now()
  try {
    const result = await task()
    console.info(`[PERFORMANCE] ${label}=${Math.round(performance.now() - startedAt)}ms status=success`)
    return result
  } catch (error) {
    console.warn(`[PERFORMANCE] ${label}=${Math.round(performance.now() - startedAt)}ms status=error`)
    throw error
  }
}

export function reportDuration(label, startedAt, status = 'success') {
  console.info(`[PERFORMANCE] ${label}=${Math.round(performance.now() - startedAt)}ms status=${status}`)
}
