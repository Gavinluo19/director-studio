import { useEffect, useRef } from 'react';
import type { ReactNode } from 'react';
import { X, ArrowRight, Image, Film, Check, AlertCircle, Clock3 } from 'lucide-react';
import { money, totals } from './domain.ts';
import type { Project, Shot } from './domain.ts';

export function Button({ children, onClick, disabled, kind = '', className = '', type = 'button' }: { children: ReactNode; onClick?: () => void; disabled?: boolean; kind?: string; className?: string; type?: 'button' | 'submit' }) { return <button type={type} className={`btn ${kind} ${className}`} disabled={disabled} onClick={onClick}>{children}</button>; }
export function Tag({ children, tone = '' }: { children: ReactNode; tone?: string }) { return <span className={`tag ${tone}`}>{children}</span>; }
export function Empty({ title, children }: { title: string; children?: ReactNode }) { return <div className="empty"><Image size={25} strokeWidth={1.3} /><strong>{title}</strong><p>{children}</p></div>; }
export function Modal({ title, children, onClose, wide = false }: { title: string; children: ReactNode; onClose: () => void; wide?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { ref.current?.showModal(); return () => ref.current?.close(); }, []);
  return <dialog ref={ref} className={`dialog ${wide ? 'wide' : ''}`} onCancel={onClose} onClick={e => { if (e.target === ref.current) onClose(); }}><header><h2>{title}</h2><button className="icon-button" aria-label="关闭对话框" onClick={onClose}><X size={18} /></button></header><div className="dialog-body">{children}</div></dialog>;
}
export function PageTitle({ eyebrow, title, children, action }: { eyebrow: string; title: string; children: ReactNode; action?: ReactNode }) { return <div className="page-title"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1><p>{children}</p></div>{action}</div>; }
export function NextAction({ title, detail, children }: { title: string; detail?: string; children: ReactNode }) { return <div className="next-action"><div><strong>{title}</strong>{detail && <p>{detail}</p>}</div><div className="action-group">{children}</div></div>; }
export function Notice({ children, tone = '' }: { children: ReactNode; tone?: string }) { return <div className={`notice ${tone}`}><AlertCircle size={16} /><div>{children}</div></div>; }
export function BudgetStrip({ project, onOpen }: { project: Project; onOpen: () => void }) { const t = totals(project); return <button className="budget-strip" onClick={onOpen} aria-label="查看预算与费用"><span><small>媒体预算 · 模拟</small><b>{money(t.spent)} <em>/ {money(project.totalLimit)}</em></b></span><span className="budget-track"><i style={{ width: `${Math.min(100, t.spent / project.totalLimit * 100)}%` }} /><i className="reserved" style={{ width: `${Math.min(100 - Math.min(100, t.spent / project.totalLimit * 100), t.reserved / project.totalLimit * 100)}%` }} /></span><span className="budget-detail">在途 {money(t.reserved)} <ArrowRight size={13} /></span></button>; }
export function FrameVisual({ shot, imageUrl, index, large = false }: { shot?: Shot; imageUrl?: string; index: number; large?: boolean }) { return <div className={`frame-visual frame-${index % 3} ${large ? 'large' : ''}`}>
  {imageUrl ? <img src={imageUrl} alt={shot?.title || '上传的参考图片'} /> : <div className="frame-placeholder"><Image size={large ? 36 : 22} strokeWidth={1} /><span>参考画面待上传</span></div>}
  <span className="frame-number">{String(index + 1).padStart(2, '0')}</span><span className="frame-label">{imageUrl ? '用户原图 · 示意' : '画面占位 · 非生成'}</span>
</div>; }
export function StatusIcon({ status }: { status: string }) { return status === 'succeeded' ? <Check size={16} /> : status === 'unknown' ? <AlertCircle size={16} /> : status === 'running' ? <Clock3 size={16} className="pulse" /> : <Film size={16} />; }
