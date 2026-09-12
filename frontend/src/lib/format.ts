import type { Amount } from './types';

export function amount(value: Amount | undefined, decimals = 2, signed = false): string {
  if (value === null || value === undefined || value === '') return '—';
  const num = Number(value);
  if (!Number.isFinite(num)) return '—';
  return new Intl.NumberFormat('it-IT', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
    signDisplay: signed ? 'exceptZero' : 'auto',
  }).format(num);
}
export function pnlClass(value: Amount | undefined): string {
  if (value === null || value === undefined) return 'text-muted';
  return Number(value) < 0 ? 'text-negative' : Number(value) > 0 ? 'text-positive' : '';
}
export function timeLabel(time: string): string {
  const parsed = new Date(time);
  return Number.isNaN(parsed.getTime())
    ? time
    : parsed.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}
export function dateLabel(time: string): string {
  const parsed = new Date(time);
  return Number.isNaN(parsed.getTime())
    ? ''
    : parsed.toLocaleDateString('it-IT', { day: 'numeric', month: 'long' });
}
