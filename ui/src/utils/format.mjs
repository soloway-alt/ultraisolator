import { PRIORITY_CLASS_LABELS } from '../constants/processes.mjs';
import { EFFICIENCY_LABELS } from '../constants/topology.mjs';

export function formatTimerResolution(value) {
  if (typeof value !== 'number' || value <= 0) {
    return 'Inactive';
  }
  const milliseconds = value / 10000;
  return `${milliseconds.toFixed(3).replace(/0+$/, '').replace(/\.$/, '')} ms`;
}

export function formatPartitions(partitions = {}, labels = {}) {
  const game = partitions.game_cores ?? partitions.game ?? 0;
  const background = partitions.background ?? 0;
  const housekeeping = partitions.housekeeping ?? 0;
  return `${labels.game || 'Game'} ${game} · ${labels.background || 'Background'} ${background} · ${labels.system || 'System'} ${housekeeping}`;
}

export function formatPriorityClass(priorityClass) {
  if (typeof priorityClass !== 'number') {
    return 'Default';
  }
  return PRIORITY_CLASS_LABELS[priorityClass] || `Class ${priorityClass}`;
}

export function formatCpuSets(cpuSetIds, affinityMask) {
  if (Array.isArray(cpuSetIds) && cpuSetIds.length > 0) {
    const visible = cpuSetIds.slice(0, 8).join(', ');
    return cpuSetIds.length > 8 ? `${visible}, +${cpuSetIds.length - 8}` : visible;
  }
  if (typeof affinityMask === 'number') {
    return `Mask 0x${affinityMask.toString(16).toUpperCase()}`;
  }
  return 'None';
}

export function formatCacheSize(bytes) {
  if (typeof bytes !== 'number' || bytes <= 0) {
    return 'L3 not reported';
  }
  if (bytes >= 1024 * 1024) {
    return `${Math.round(bytes / (1024 * 1024))} MiB L3`;
  }
  if (bytes >= 1024) {
    return `${Math.round(bytes / 1024)} KiB L3`;
  }
  return `${bytes} B L3`;
}

export function formatCoreLabel(core) {
  const type = EFFICIENCY_LABELS[core?.efficiency_type] || 'Core';
  return core?.parked ? `${type} / Parked` : type;
}
