function safeLocation(value) {
  const text = String(value || '');
  try {
    const url = new URL(text);
    url.username = '';
    url.password = '';
    url.search = '';
    url.hash = '';
    return url.toString();
  } catch {
    return text.replace(/([?&](?:token|secret|signature|key|cookie|authorization)=)[^&\s]+/gi, '$1[REDACTED]');
  }
}

export function annotateError(error, context = {}) {
  const target = error instanceof Error ? error : new Error(String(error));
  if (context.location) target.requestLocation = safeLocation(context.location);
  if (context.attempt != null) target.attempt = context.attempt;
  if (context.maxAttempts != null) target.maxAttempts = context.maxAttempts;
  return target;
}

export async function writeErrorLog(error, context = {}) {
  console.error(JSON.stringify({
    event: context.event || 'error',
    location: safeLocation(context.location || error?.requestLocation),
    status: Number(error?.status || 0),
    message: String(error?.message || error || '').slice(0, 500),
  }));
}
