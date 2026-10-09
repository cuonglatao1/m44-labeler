const json = (r) => {
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
  return r.json()
}

// pilot mode: every per-frame read / write goes to that person's own draft (see backend store.pilot_key)
let pilotQuery = ''
const withPilot = (url) => (pilotQuery ? `${url}${url.includes('?') ? '&' : '?'}${pilotQuery}` : url)

export const api = {
  setPilot: (name, assist) => { pilotQuery = `pilot=${encodeURIComponent(name)}&assist=${assist ? 1 : 0}` },
  frames: () => fetch('/api/frames').then(json),
  frame: (i, init = 'gt', source = 'auto') => fetch(withPilot(`/api/frames/${i}?init=${init}&source=${source}`)).then(json),
  points: (i) => fetch(`/api/frames/${i}/points`).then((r) => r.arrayBuffer()).then((b) => new Float32Array(b)),
  imageUrl: (i, cam) => `/api/frames/${i}/image/${cam}`,
  check: (i, boxes) =>
    fetch(withPilot(`/api/frames/${i}/check`), {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ boxes }),
    }).then(json),
  save: (i, boxes) =>
    fetch(withPilot(`/api/frames/${i}/boxes`), {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ boxes }),
    }).then(json),
  propose: (i, cam, bbox, cls) =>
    fetch(withPilot(`/api/frames/${i}/propose`), {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ cam, bbox, cls }),
    }).then(json),
  proposeMissing: (i, boxes) =>
    fetch(withPilot(`/api/frames/${i}/propose_missing`), {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ boxes }),
    }).then(json),
  exportUrl: (fmt) => `/api/export?fmt=${fmt}`,
  pilotSubmit: (i, boxes) =>
    fetch(withPilot(`/api/frames/${i}/pilot_submit`), {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ boxes }),
    }).then(json),
  event: (i, kind, data) =>
    fetch(withPilot(`/api/frames/${i}/events`), {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ kind, data }),
    }).then(json),
}

export const config = () => fetch('/api/config').then(json)

export const suggestFix = (i, flag, boxes) =>
  fetch(`/api/frames/${i}/suggest`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ flag, boxes }),
  }).then(json)

// one chat turn: POST, then read the server-sent events from the body (EventSource cannot POST)
export async function chatStream(body, onEvent) {
  const r = await fetch('/api/assistant/chat', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  })
  if (!r.ok) {
    const detail = await r.json().catch(() => ({}))
    throw new Error(detail.detail || `${r.status} ${r.statusText}`)
  }
  const reader = r.body.getReader()
  const dec = new TextDecoder()
  let buf = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buf += dec.decode(value, { stream: true })
    let k
    while ((k = buf.indexOf('\n\n')) >= 0) {
      const chunk = buf.slice(0, k)
      buf = buf.slice(k + 2)
      const line = chunk.split('\n').find((l) => l.startsWith('data: '))
      if (line) onEvent(JSON.parse(line.slice(6)))
    }
  }
}

export const resetChat = (session_id) =>
  fetch('/api/assistant/reset', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ session_id }),
  }).then(json)
