// Thin fetch helpers. Paths are relative so they work behind the /app mount and the
// Vite dev proxy alike. Trading data is read/query only here — there is no order entry.

export async function jpost<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${path} → ${r.status}: ${(await r.text()).slice(0, 200)}`);
  return r.json();
}

export async function jget<T>(path: string): Promise<T> {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  return r.json();
}

export async function jdelete(path: string): Promise<void> {
  const r = await fetch(path, { method: "DELETE" });
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
}

export async function jpatch<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(path, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  return r.json();
}

export async function uploadFile(path: string, file: File): Promise<any> {
  const fd = new FormData();
  fd.append("file", file);
  const r = await fetch(path, { method: "POST", body: fd });
  if (!r.ok) throw new Error(`${path} → ${r.status}: ${(await r.text()).slice(0, 200)}`);
  return r.json();
}

export async function postAudioForWav(path: string, file: File): Promise<{ blob: Blob; transcript: string; response: string }> {
  const fd = new FormData();
  fd.append("file", file);
  const r = await fetch(path, { method: "POST", body: fd });
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  const transcript = decodeURIComponent(r.headers.get("x-transcript") || "");
  const response = decodeURIComponent(r.headers.get("x-response-text") || "");
  return { blob: await r.blob(), transcript, response };
}
