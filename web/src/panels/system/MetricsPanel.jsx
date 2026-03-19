import { useStore } from '../../core/store';
import { fmt, isWarn, pct, primaryClass, valueClass } from './shared/formatters';
import './MetricsPanel.css';

function MetricCard({ title, usagePct, warnAt = 85, primary, details }) {
  const warn = isWarn(usagePct, warnAt);

  return (
    <div className="sys-metric-card">
      <div className="sys-metric-card-header">
        <span className="sys-metric-title">{title}</span>
        <span className={primaryClass(usagePct, warnAt)}>{primary}</span>
      </div>
      {usagePct != null && (
        <div className="sys-bar-wrap">
          <div className={`sys-bar-fill ${warn ? 'warn' : ''}`} style={{ width: pct(usagePct) }} />
        </div>
      )}
      <div className="sys-metric-details">
        {details.map(([label, value, extraCls]) => (
          <div key={label} className="sys-metric-row">
            <span>{label}</span>
            <span className={`sys-metric-value ${extraCls ?? ''}`}>{value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function MetricsPanel({ className = 'sys-panel-metrics' }) {
  const systemMetrics = useStore((s) => s.systemMetrics);

  const cpu = systemMetrics?.cpu;
  const gpu = systemMetrics?.gpu;
  const ram = systemMetrics?.ram;
  const disk = systemMetrics?.disk;

  return (
    <div className={`layout-panel-body sys-panel-metrics-root ${className}`.trim()}>
      <div className="sys-metrics-body">
        <MetricCard
          title="CPU"
          usagePct={cpu?.usage_pct}
          warnAt={85}
          primary={fmt(cpu?.usage_pct, '%')}
          details={[
            ['Logical', fmt(cpu?.count_logical)],
            ['Physical', fmt(cpu?.count_physical)],
            ['Load avg', cpu?.load_avg_1_5_15?.join(' / ') ?? 'N/A'],
          ]}
        />
        <MetricCard
          title="RAM"
          usagePct={ram?.usage_pct}
          warnAt={85}
          primary={`${fmt(ram?.used_mb)} / ${fmt(ram?.total_mb)} MB`}
          details={[
            ['Usage', fmt(ram?.usage_pct, '%'), valueClass(ram?.usage_pct, 85).replace('sys-metric-value', '').trim()],
            ['Available', fmt(ram?.available_mb, ' MB')],
          ]}
        />
        <MetricCard
          title="GPU"
          usagePct={gpu?.utilization_pct}
          warnAt={90}
          primary={fmt(gpu?.utilization_pct, '%')}
          details={[
            ['Provider', fmt(gpu?.provider)],
            ['VRAM', gpu?.memory_used_mb != null ? `${gpu.memory_used_mb} / ${gpu.memory_total_mb} MB` : 'N/A'],
            ['Temp', fmt(gpu?.temperature_c, '°C'), valueClass(gpu?.temperature_c, 80).replace('sys-metric-value', '').trim()],
          ]}
        />
        <MetricCard
          title="Disk"
          usagePct={disk?.usage_pct}
          warnAt={90}
          primary={`${fmt(disk?.used_gb)} / ${fmt(disk?.total_gb)} GB`}
          details={[
            ['Usage', fmt(disk?.usage_pct, '%'), valueClass(disk?.usage_pct, 90).replace('sys-metric-value', '').trim()],
          ]}
        />
      </div>
    </div>
  );
}

export default MetricsPanel;
export { MetricsPanel };
