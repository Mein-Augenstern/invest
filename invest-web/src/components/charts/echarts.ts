/**
 * ECharts 按需注册（tree-shaking）：只引入 13 屏用到的图表与组件，其余不进包。
 * 新增图表类型时在此登记，页面统一经 EChart.vue 使用。
 */
import * as echarts from 'echarts/core'
import { BarChart, LineChart } from 'echarts/charts'
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  MarkPointComponent,
  TooltipComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([
  LineChart,
  BarChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
  MarkLineComponent,
  MarkPointComponent,
  MarkAreaComponent,
  CanvasRenderer,
])

export { echarts }
export type { EChartsCoreOption as EChartsOption } from 'echarts/core'

/** 图表配色：主色 + 区分度足够的辅助色（多策略对比用），红绿保留给盈亏语义 */
export const SERIES_COLORS = ['#1652a8', '#d46b08', '#7a4fbf', '#0e8a9e', '#a1662b', '#5b6b7c']
export const RISE = '#d54941'
export const FALL = '#2e9e5b'
