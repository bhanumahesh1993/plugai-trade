/* ECharts with a click handler (the kit's EChart has none): click a bar to inspect it. */
import ReactEChartsCore from "echarts-for-react/esm/core";
import { echarts } from "@/lib/echarts";
import { useTheme } from "@/components/theme";

export function ClickChart({ option, onPick, height = 220 }: {
  option: Record<string, unknown>; onPick: (dataIndex: number) => void; height?: number;
}) {
  const { theme } = useTheme();
  return (
    <ReactEChartsCore echarts={echarts} key={theme} notMerge style={{ height, width: "100%" }}
      option={{ animation: false, textStyle: { fontFamily: "IBM Plex Sans" }, ...option }}
      onEvents={{ click: (p: { dataIndex: number }) => onPick(p.dataIndex) }} />
  );
}
