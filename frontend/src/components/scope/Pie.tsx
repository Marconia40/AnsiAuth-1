export interface PieSlice {
  value: number;
  color: string;
}

interface Props {
  slices: PieSlice[];
  size?: number;
  strokeWidth?: number;
  center?: React.ReactNode;
  emptyColor?: string;
  trackColor?: string;
}

export function Pie({
  slices,
  size = 120,
  strokeWidth = 20,
  center,
  emptyColor = 'var(--color-panel-border)',
  trackColor = 'var(--color-panel-elev)',
}: Props) {
  const cx = size / 2;
  const cy = size / 2;
  const r = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * r;
  const total = slices.reduce((acc, s) => acc + Math.max(0, s.value), 0);

  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle
          cx={cx}
          cy={cy}
          r={r}
          fill="none"
          stroke={total === 0 ? emptyColor : trackColor}
          strokeWidth={strokeWidth}
        />
        {total > 0 && (() => {
          let cumulative = 0;
          return slices.map((slice, idx) => {
            if (slice.value <= 0) return null;
            const fraction = slice.value / total;
            const dash = fraction * circumference;
            const offset = circumference - cumulative * circumference;
            cumulative += fraction;
            return (
              <circle
                key={idx}
                cx={cx}
                cy={cy}
                r={r}
                fill="none"
                stroke={slice.color}
                strokeWidth={strokeWidth}
                strokeDasharray={`${dash} ${circumference - dash}`}
                strokeDashoffset={offset}
                transform={`rotate(-90 ${cx} ${cy})`}
              />
            );
          });
        })()}
      </svg>
      {center && (
        <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none text-center">
          {center}
        </div>
      )}
    </div>
  );
}
