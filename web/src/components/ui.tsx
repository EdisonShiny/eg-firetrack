import type { ReactNode } from "react";

export function Card(props: {
  title: ReactNode;
  meta?: ReactNode;
  metaAccent?: boolean;
  highlight?: boolean;
  foot?: ReactNode;
  children: ReactNode;
  className?: string;
  labelledBy?: string;
}) {
  const id = props.labelledBy;
  return (
    <section className={`card${props.highlight ? " highlight" : ""} ${props.className ?? ""}`} aria-labelledby={id}>
      <div className="card-head">
        <h2 className="card-title" id={id}>
          {props.title}
        </h2>
        {props.meta && <div className={`card-meta${props.metaAccent ? " accent" : ""}`}>{props.meta}</div>}
      </div>
      {props.children}
      {props.foot && <div className="card-foot">{props.foot}</div>}
    </section>
  );
}

export function StatTile(props: { label: string; value: string; note?: ReactNode; tone?: "up" | "down" }) {
  return (
    <div className="tile">
      <div className="tile-label">{props.label}</div>
      <div className={`tile-value${props.tone ? " " + props.tone : ""}`}>{props.value}</div>
      {props.note && <div className="tile-note">{props.note}</div>}
    </div>
  );
}

export function SegmentedControl<T extends string>(props: {
  label: string;
  options: { id: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
  small?: boolean;
}) {
  return (
    <div className={`segmented${props.small ? " small" : ""}`} role="group" aria-label={props.label}>
      {props.options.map((o) => (
        <button key={o.id} type="button" aria-pressed={o.id === props.value} onClick={() => props.onChange(o.id)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Skeleton(props: { height: number | string; width?: number | string }) {
  return <div className="skeleton" style={{ height: props.height, width: props.width ?? "100%" }} aria-hidden="true" />;
}

export function SampleBadge(props: { note?: string }) {
  return (
    <span className="sample-badge" title={props.note ?? "Sample data: synthetic detections, not real fires."}>
      sample data
    </span>
  );
}
