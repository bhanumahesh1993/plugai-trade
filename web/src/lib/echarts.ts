/* Only the ECharts parts the screens use; keeps the bundle small. Add a part here before using it. */
import * as echarts from "echarts/core";
import { LineChart, BarChart, ScatterChart, HeatmapChart, CustomChart } from "echarts/charts";
import {
  GridComponent, TooltipComponent, LegendComponent, TitleComponent, MarkLineComponent, MarkAreaComponent,
  MarkPointComponent, VisualMapComponent, DataZoomComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([
  LineChart, BarChart, ScatterChart, HeatmapChart, CustomChart,
  GridComponent, TooltipComponent, LegendComponent, TitleComponent, MarkLineComponent, MarkAreaComponent,
  MarkPointComponent, VisualMapComponent, DataZoomComponent, CanvasRenderer,
]);
export { echarts };
