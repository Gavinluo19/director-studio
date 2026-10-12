import { initialStore } from './domain.ts';
import type { Store } from './domain.ts';

const KEY = 'director-studio-b0-v1';
export function loadState(): Store {
  try { const data = JSON.parse(localStorage.getItem(KEY) || 'null'); if (data?.schema === 1 && data.projects?.length && data.settings?.models) return data; } catch { /* Keep a corrupt/old state out of the live model. */ }
  return initialStore();
}
export function saveState(state: Store) { localStorage.setItem(KEY, JSON.stringify(state)); }
export type LocalAsset = { id: string; name: string; mime: string; size: number; createdAt: string; blob: Blob };
function database(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => { const req = indexedDB.open('director-studio-assets', 1); req.onupgradeneeded = () => req.result.createObjectStore('assets', { keyPath: 'id' }); req.onsuccess = () => resolve(req.result); req.onerror = () => reject(req.error); });
}
export async function listAssets(): Promise<LocalAsset[]> {
  const db = await database(); return new Promise((resolve, reject) => { const tx = db.transaction('assets'); const req = tx.objectStore('assets').getAll(); req.onsuccess = () => resolve(req.result); req.onerror = () => reject(req.error); tx.oncomplete = () => db.close(); });
}
export async function importAsset(file: File): Promise<LocalAsset> {
  if (!/^(image\/(png|jpeg|webp)|video\/mp4|audio\/(mpeg|mp3|wav|x-wav|mp4))$/.test(file.type)) throw new Error('支持 JPG、PNG、WebP、MP4、MP3 和 WAV 文件。');
  if (file.size > 25 * 1024 * 1024) throw new Error('体验版单个文件最大 25 MB。');
  const hash = [...new Uint8Array(await crypto.subtle.digest('SHA-256', await file.arrayBuffer()))].map(x => x.toString(16).padStart(2, '0')).join('');
  const asset: LocalAsset = { id: hash, name: file.name, mime: file.type, size: file.size, createdAt: new Date().toISOString(), blob: file };
  const db = await database(); await new Promise<void>((resolve, reject) => { const tx = db.transaction('assets', 'readwrite'); tx.objectStore('assets').put(asset); tx.oncomplete = () => { db.close(); resolve(); }; tx.onerror = () => reject(tx.error); }); return asset;
}
export function downloadJson(name: string, value: unknown) { const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' })); const a = document.createElement('a'); a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
