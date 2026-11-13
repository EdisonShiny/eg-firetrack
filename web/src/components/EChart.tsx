// Thin React wrapper around Apache ECharts (tree-shaken: only the charts the site uses).
import { BarChart, CustomChart, LineChart } from "echarts/charts";
import { GridComponent, MarkAreaComponent, MarkLineComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useRef, useState } from "react";
import { usePrintMode } from "../lib/printMode";

echarts.use([LineChart, BarChart, CustomChart, GridComponent, TooltipComponent, MarkLineComponent, MarkAreaComponent, CanvasRenderer]);

export type EChartsOption = echarts.EChartsCoreOption;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type ChartEvent = { componentType: string; name?: string; value?: any; data?: any; dataIndex?: number };

/** Shared look: Inter labels in secondary text colour (docs/visual.md). */
export const CHART_TEXT = { fontFamily: "Inter, Segoe UI, system-ui, sans-serif", color: "#5B6472", fontSize: 12 };
export const CHART_MONO = { fontFamily: "JetBrains Mono, Cascadia Mono, Consolas, monospace", color: "#111827", fontSize: 12 };
export const TOOLTIP_STYLE = {
  backgroundColor: "#FFFFFF",
  borderColor: "#E3E6EA",
  textStyle: { fontFamily: CHART_TEXT.fontFamily, color: "#111827", fontSize: 12.5 },
  extraCssText: "box-shadow: 0 2px 10px rgba(17,24,39,.16); border-radius: 8px;",
};

export function EChart(props: {
  option: EChartsOption;
  height: number;
  label: string;
  onClick?: (e: ChartEvent) => void;
}) {
  const print = usePrintMode();
  if (print) return <EChartImage option={props.option} height={props.height} label={props.label} />;
  return <LiveEChart {...props} />;
}

/** Print route: draw once at 2× pixel ratio, then show a plain <img> (prints reliably). */
function EChartImage(props: { option: EChartsOption; height: number; label: string }) {
  const el = useRef<HTMLDivElement>(null);
  const [img, setImg] = useState<{ option: EChartsOption; src: string } | null>(null);

  useEffect(() => {
    if (!el.current) return;
    const c = echarts.init(el.current, undefined, { renderer: "canvas", devicePixelRatio: 2 });
    c.setOption(props.option, { notMerge: true }); // synchronous render (no lazyUpdate, animation off)
    setImg({ option: props.option, src: c.getDataURL({ type: "png", pixelRatio: 2, backgroundColor: "#FFFFFF" }) });
    c.dispose();
  }, [props.option]);

  if (img && img.option === props.option)
    return <img className="echart-img" src={img.src} alt={props.label} style={{ width: "100%", height: "auto" }} />;
  return <div ref={el} className="echart" data-chart-pending="" style={{ height: props.height }} aria-hidden="true" />;
}

function LiveEChart(props: {
  option: EChartsOption;
  height: number;
  label: string;
  onClick?: (e: ChartEvent) => void;
}) {
  const el = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  const onClick = useRef(props.onClick);
  onClick.current = props.onClick;

  useEffect(() => {
    if (!el.current) return;
    const c = echarts.init(el.current, undefined, { renderer: "canvas" });
    chart.current = c;
    c.on("click", (e) => onClick.current?.(e as unknown as ChartEvent));
    const ro = new ResizeObserver(() => c.resize());
    ro.observe(el.current);
    return () => {
      ro.disconnect();
      c.dispose();
      chart.current = null;
    };
  }, []);

  useEffect(() => {
    chart.current?.setOption(props.option, { notMerge: true });
  }, [props.option]);

  return <div ref={el} className="echart" style={{ height: props.height }} role="img" aria-label={props.label} />;
}
