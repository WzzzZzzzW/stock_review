import { useEffect, useRef } from 'react'
import {
  createChart,
  ColorType,
  CrosshairMode,
  type IChartApi,
  type ISeriesApi,
  type CandlestickData,
  type HistogramData,
  type SeriesMarker,
  type Time,
} from 'lightweight-charts'
import type { OhlcvBar } from '../types'

export interface KeyEvent {
  date:      string
  pct_chg:   number
  close:     number
  vol_ratio: number
  direction: string   // 大涨 | 大跌 | 上涨 | 下跌
}

interface Props {
  data:       OhlcvBar[]
  keyEvents?: KeyEvent[]
}

export default function CandlestickChart({ data, keyEvents }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const candleRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const volumeRef = useRef<ISeriesApi<'Histogram'> | null>(null)

  useEffect(() => {
    if (!containerRef.current) return

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#0f172a' },
        textColor: '#94a3b8',
      },
      grid: {
        vertLines: { color: '#1e293b' },
        horzLines: { color: '#1e293b' },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: '#1e293b' },
      timeScale: { borderColor: '#1e293b', timeVisible: true },
      width: containerRef.current.clientWidth,
      height: 360,
    })

    const candleSeries = chart.addCandlestickSeries({
      upColor: '#ef4444',
      downColor: '#22c55e',
      borderUpColor: '#ef4444',
      borderDownColor: '#22c55e',
      wickUpColor: '#ef4444',
      wickDownColor: '#22c55e',
    })

    const volumeSeries = chart.addHistogramSeries({
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    })
    chart.priceScale('volume').applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    })

    chartRef.current = chart
    candleRef.current = candleSeries
    volumeRef.current = volumeSeries

    const handleResize = () => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth })
      }
    }
    window.addEventListener('resize', handleResize)
    return () => {
      window.removeEventListener('resize', handleResize)
      chart.remove()
    }
  }, [])

  useEffect(() => {
    if (!candleRef.current || !volumeRef.current || !data.length) return

    const candleData: CandlestickData[] = data.map((d) => ({
      time: d.date.slice(0, 10) as Time,
      open: d.open,
      high: d.high,
      low: d.low,
      close: d.close,
    }))

    const volumeData: HistogramData[] = data.map((d) => ({
      time: d.date.slice(0, 10) as Time,
      value: d.volume,
      color: d.pct_change >= 0 ? '#ef444460' : '#22c55e60',
    }))

    candleRef.current.setData(candleData)
    volumeRef.current.setData(volumeData)
    chartRef.current?.timeScale().fitContent()
  }, [data])

  // 在 K 线上标出量价异动节点（放量大涨▲ / 放量大跌▼）
  useEffect(() => {
    if (!candleRef.current) return
    const evs = keyEvents ?? []
    if (!evs.length) { candleRef.current.setMarkers([]); return }

    const markers: SeriesMarker<Time>[] = evs
      .map(e => {
        const up = e.pct_chg >= 0
        const big = e.direction === '大涨' || e.direction === '大跌'
        const sign = e.pct_chg > 0 ? '+' : ''
        return {
          time: e.date.slice(0, 10) as Time,
          position: up ? 'belowBar' : 'aboveBar',
          color: up ? '#ef4444' : '#22c55e',
          shape: up ? 'arrowUp' : 'arrowDown',
          // 只给「大涨/大跌」显示文字，避免小异动把图挤花
          text: big ? `${sign}${e.pct_chg.toFixed(1)}%` : undefined,
        } as SeriesMarker<Time>
      })
      .sort((a, b) => (a.time < b.time ? -1 : a.time > b.time ? 1 : 0))

    candleRef.current.setMarkers(markers)
  }, [keyEvents, data])

  return <div ref={containerRef} className="w-full rounded-lg overflow-hidden" />
}
